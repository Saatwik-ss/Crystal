import logging
import re
from typing import AsyncIterator, Dict, List, Any, Optional
import json

from services.llm_config import (
    DEFAULT_API_KEY,
    DEFAULT_MODEL,
    fit_max_tokens,
    friendly_llm_error,
    get_groq_client,
    is_payload_too_large_error,
    merge_system_prompt,
    parse_max_tokens_limit,
    trim_messages_to_budget,
    truncate_text,
)

logger = logging.getLogger(__name__)

# Keep completion prompts small for latency + TPM.
PREFIX_CHAR_CAP = 3500
SUFFIX_CHAR_CAP = 1200
DEFAULT_COMPLETION_MAX_TOKENS = 96


class CodeCompletionService:
    """
    Service for AI-powered inline code completion (ghost text).
    """

    def __init__(self):
        self.model_name = DEFAULT_MODEL
        self.api_key = DEFAULT_API_KEY
        self.client, _, self.initialized = get_groq_client()
        if self.initialized:
            logger.info("CodeCompletionService initialized")
        else:
            logger.warning("GROQ_API_KEY not set")

    async def stream_completion(
        self,
        prompt: str,
        file_path: str = None,
        language: str = "javascript",
        repo_context: Dict[str, Any] = None,
        max_tokens: int = DEFAULT_COMPLETION_MAX_TOKENS,
        temperature: float = 0.15,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        user_system_prompt: Optional[str] = None,
        suffix: str = "",
    ) -> AsyncIterator[str]:
        """
        Stream code completion based on prefix (+ optional suffix for FIM-style fill).
        """
        client, model_name, initialized = get_groq_client(
            user_key=api_key,
            user_model=model,
            fallback_client=self.client,
            fallback_key=self.api_key,
        )
        if not initialized:
            yield json.dumps({
                "type": "completion",
                "text": "",
            })
            yield json.dumps({"type": "end"})
            return

        try:
            system_prompt = merge_system_prompt(
                self._build_completion_system_prompt(language, file_path, repo_context),
                user_system_prompt,
            )

            user_prompt = self._build_user_prompt(prompt or "", suffix or "", language)
            messages = trim_messages_to_budget(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                reserve_completion=max_tokens,
            )
            max_out = fit_max_tokens(messages, max_tokens, model=model_name)

            try:
                stream = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=max_out,
                    temperature=temperature,
                    stream=True,
                    stop=["\n\n\n", "```"],
                )
            except Exception as api_error:
                limit = parse_max_tokens_limit(api_error)
                if limit is not None:
                    stream = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        max_tokens=min(max_out, limit),
                        temperature=temperature,
                        stream=True,
                        stop=["\n\n\n", "```"],
                    )
                elif is_payload_too_large_error(api_error):
                    messages = trim_messages_to_budget(messages, reserve_completion=64)
                    stream = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        max_tokens=fit_max_tokens(messages, 64, model=model_name),
                        temperature=temperature,
                        stream=True,
                        stop=["\n\n\n", "```"],
                    )
                else:
                    raise

            completion_text = ""
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    completion_text += text
                    yield json.dumps({
                        "type": "completion",
                        "text": text,
                    })

            cleaned = self._clean_completion(completion_text, prompt or "")
            # If cleaning removed everything after streaming chunks, send a replace
            # marker so the client can prefer the cleaned full text.
            if cleaned != completion_text:
                yield json.dumps({
                    "type": "completion_final",
                    "text": cleaned,
                })

            yield json.dumps({"type": "end"})

        except Exception as e:
            logger.error(f"Completion error: {e}")
            yield json.dumps({
                "type": "error",
                "error": friendly_llm_error(
                    e, model_name if "model_name" in locals() else None
                ),
            })

    def _build_user_prompt(self, prefix: str, suffix: str, language: str) -> str:
        # Keep text nearest the cursor (end of prefix, start of suffix)
        if len(prefix) > PREFIX_CHAR_CAP:
            prefix = prefix[-PREFIX_CHAR_CAP:]
        if len(suffix) > SUFFIX_CHAR_CAP:
            suffix = suffix[:SUFFIX_CHAR_CAP]

        if suffix.strip():
            return (
                f"Language: {language}\n"
                "Complete the code at <CURSOR>. Return ONLY the text to insert "
                "at the cursor (do not repeat code before the cursor).\n\n"
                f"{prefix}<CURSOR>{suffix}"
            )
        return (
            f"Language: {language}\n"
            "Continue the code from the end of the snippet. Return ONLY the "
            "continuation (do not repeat existing code).\n\n"
            f"{prefix}"
        )

    def _build_completion_system_prompt(
        self,
        language: str,
        file_path: str = None,
        repo_context: Dict[str, Any] = None,
    ) -> str:
        prompt = (
            f"You are an expert {language} inline code-completion engine "
            "(like Copilot ghost text).\n"
            "Rules:\n"
            "- Output ONLY the code to insert at the cursor.\n"
            "- No markdown fences, no explanations, no quotes around the code.\n"
            "- Prefer a short completion (often the rest of the current line, "
            "sometimes a few following lines).\n"
            "- Match indentation and style of the surrounding code.\n"
            "- Never rewrite code that already appears before the cursor.\n"
        )

        if file_path:
            prompt += f"Current file: {file_path}\n"

        if repo_context:
            languages = repo_context.get("languages", [])
            if languages:
                prompt += f"Repository uses: {', '.join(languages)}\n"

        return prompt

    def _clean_completion(self, text: str, prefix: str) -> str:
        if not text:
            return ""

        cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"^```[\w+-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        cleaned = cleaned.replace("<CURSOR>", "")

        # Drop accidental echo of the last prefix line
        last_line = prefix.rsplit("\n", 1)[-1] if prefix else ""
        if last_line and cleaned.startswith(last_line):
            cleaned = cleaned[len(last_line):]

        # Cap runaway multi-paragraph dumps
        parts = cleaned.split("\n\n")
        if len(parts) > 2:
            cleaned = "\n\n".join(parts[:2])

        lines = cleaned.split("\n")
        if len(lines) > 12:
            cleaned = "\n".join(lines[:12])

        return cleaned

    def _extract_missing_imports(self, code: str, language: str) -> List[str]:
        imports: List[str] = []

        if language == "python":
            if "import " in code or "from " in code:
                for line in code.split("\n"):
                    if line.strip().startswith(("import ", "from ")):
                        imports.append(line.strip())
        elif language in ["javascript", "typescript"]:
            if "import " in code:
                for line in code.split("\n"):
                    if line.strip().startswith("import "):
                        imports.append(line.strip())

        return imports
