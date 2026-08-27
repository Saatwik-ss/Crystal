import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL") or "llama-3.3-70b-versatile"
DEFAULT_API_KEY = os.getenv("GROQ_API_KEY") or ""

# Groq free/dev tiers often reject requests when (prompt + max_tokens) exceeds TPM.
# 413 "Payload Too Large" / "Request Entity Too Large" is commonly this budget.
REQUEST_TOKEN_BUDGET = int(os.getenv("GROQ_REQUEST_TOKEN_BUDGET") or "64000")
TOOL_MAX_TOKENS = int(os.getenv("GROQ_TOOL_MAX_TOKENS") or "4096")
# propose_edit must emit full file content in tool args — needs more room.
EDIT_TOOL_MAX_TOKENS = int(os.getenv("GROQ_EDIT_TOOL_MAX_TOKENS") or "16384")
CHAT_MAX_TOKENS = int(os.getenv("GROQ_CHAT_MAX_TOKENS") or "4096")
# Keep file context modest so tool-call requests stay under TPM.
SELECTED_CODE_CHAR_CAP = int(os.getenv("GROQ_SELECTED_CODE_CHAR_CAP") or "8000")
MAX_AGENT_STEPS = int(os.getenv("GROQ_MAX_AGENT_STEPS") or "12")
TOOL_RESULT_CHAR_CAP = int(os.getenv("GROQ_TOOL_RESULT_CHAR_CAP") or "16000")

# Models that are chat/completions-capable (used for settings + validation).
CHAT_MODEL_CHOICES: List[str] = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct",
]

# Groq compound uses built-in tools, not Crystal's function-calling tools.
_NO_TOOLS_SUBSTRINGS = (
    "compound",
    "whisper",
    "orpheus",
    "prompt-guard",
)

# Known max completion tokens (conservative defaults when unknown).
_MODEL_MAX_COMPLETION: Dict[str, int] = {
    "llama-3.3-70b-versatile": 32768,
    "llama-3.1-8b-instant": 8192,
    "openai/gpt-oss-120b": 65536,
    "openai/gpt-oss-20b": 65536,
    "openai/gpt-oss-safeguard-20b": 65536,
    "meta-llama/llama-4-scout-17b-16e-instruct": 8192,
    "meta-llama/llama-4-maverick-17b-128e-instruct": 8192,
    "meta-llama/llama-prompt-guard-2-22m": 512,
    "meta-llama/llama-prompt-guard-2-86m": 512,
    "qwen/qwen3-32b": 40960,
    "qwen/qwen3.6-27b": 16384,
    "moonshotai/kimi-k2-instruct": 16384,
    "groq/compound": 8192,
    "groq/compound-mini": 8192,
}

# Not usable with chat.completions
_NON_CHAT_PREFIXES = (
    "whisper",
    "canopylabs/orpheus",
)
_NON_CHAT_SUBSTRINGS = (
    "whisper",
    "orpheus",
    "prompt-guard",
)


def resolve_api_key(user_key: Optional[str] = None) -> str:
    custom = (user_key or "").strip()
    return custom or DEFAULT_API_KEY


def is_chat_model(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    if any(name.startswith(p) for p in _NON_CHAT_PREFIXES):
        return False
    if any(s in name for s in _NON_CHAT_SUBSTRINGS):
        return False
    return True


def supports_tools(model: Optional[str]) -> bool:
    """Whether Crystal can pass function-calling `tools=` to this Groq model."""
    name = (model or "").strip().lower()
    if not name or not is_chat_model(name):
        return False
    if any(s in name for s in _NO_TOOLS_SUBSTRINGS):
        return False
    return True


def is_tools_not_supported_error(error: Any) -> bool:
    text = str(error).lower()
    return (
        "tool calling" in text and "not supported" in text
    ) or (
        "tools" in text and "not supported" in text and "model" in text
    )


def model_max_completion_tokens(model: Optional[str]) -> int:
    name = (model or "").strip()
    if not name:
        return 8192
    if name in _MODEL_MAX_COMPLETION:
        return _MODEL_MAX_COMPLETION[name]
    lower = name.lower()
    for key, value in _MODEL_MAX_COMPLETION.items():
        if key.lower() == lower:
            return value
    # Safe default for unknown Groq chat models
    return 8192


def resolve_model(user_model: Optional[str] = None) -> str:
    custom = (user_model or "").strip()
    if not custom:
        return DEFAULT_MODEL
    if not is_chat_model(custom):
        logger.warning(
            "Model %r is not chat-capable; falling back to %s",
            custom,
            DEFAULT_MODEL,
        )
        return DEFAULT_MODEL
    return custom


def merge_system_prompt(default_prompt: str, user_prompt: Optional[str] = None) -> str:
    extra = (user_prompt or "").strip()
    if not extra:
        return default_prompt
    return f"User instructions:\n{extra}\n\n---\n\n{default_prompt}"


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars/4). Good enough for budgeting."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif content is not None:
            total += estimate_tokens(str(content))
        # tool_calls / name / role overhead
        total += 8
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            total += estimate_tokens(str(fn.get("name") or ""))
            total += estimate_tokens(str(fn.get("arguments") or ""))
    return total


def estimate_tools_tokens(tools: Optional[List[Dict[str, Any]]]) -> int:
    if not tools:
        return 0
    # Schemas are JSON-ish; char/4 is fine plus small overhead per tool
    return estimate_tokens(str(tools)) + 16 * len(tools)


def truncate_text(text: str, max_chars: int) -> str:
    if not text or len(text) <= max_chars:
        return text or ""
    return text[: max(0, max_chars - 20)].rstrip() + "\n...[truncated]"


def fit_max_tokens(
    messages: List[Dict[str, Any]],
    desired: int,
    budget: int = REQUEST_TOKEN_BUDGET,
    minimum: int = 256,
    model: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Choose max_tokens so prompt + tools + completion stays under Groq request budget."""
    model_cap = model_max_completion_tokens(model)
    prompt_tokens = estimate_messages_tokens(messages) + estimate_tools_tokens(tools)
    available = budget - prompt_tokens
    if available < minimum:
        capped = min(desired, model_cap, minimum)
        return max(1, capped)
    return max(minimum, min(desired, available, model_cap))


def trim_messages_to_budget(
    messages: List[Dict[str, Any]],
    budget: int = REQUEST_TOKEN_BUDGET,
    reserve_completion: int = 1024,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Shrink message contents so prompt fits under (budget - reserve_completion - tools).
    Keeps system + latest user message; truncates oversized contents.
    """
    tool_overhead = estimate_tools_tokens(tools)
    target = max(512, budget - reserve_completion - tool_overhead)
    trimmed = [dict(m) for m in messages]

    def _total() -> int:
        return estimate_messages_tokens(trimmed)

    # First pass: hard-cap any huge content fields
    for msg in trimmed:
        content = msg.get("content")
        if isinstance(content, str) and estimate_tokens(content) > target // 2:
            msg["content"] = truncate_text(content, (target // 2) * 4)

    if _total() <= target:
        return trimmed

    # Drop middle history (keep system + last 2 messages)
    if len(trimmed) > 3:
        system = [m for m in trimmed if m.get("role") == "system"][:1]
        rest = [m for m in trimmed if m.get("role") != "system"]
        trimmed = system + rest[-2:]

    if _total() <= target:
        return trimmed

    # Last resort: truncate every string content proportionally
    for msg in trimmed:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > 600:
            msg["content"] = truncate_text(content, 600)

    return trimmed


def is_payload_too_large_error(error: Any) -> bool:
    text = str(error).lower()
    return (
        "413" in text
        or "payload too large" in text
        or "request too large" in text
        or "request entity too large" in text
    )


def is_unsupported_chat_model_error(error: Any) -> bool:
    text = str(error).lower()
    return (
        "does not support chat completions" in text
        or "not a chat model" in text
    )


def is_tool_use_failed_error(error: Any) -> bool:
    text = str(error).lower()
    return (
        "tool_use_failed" in text
        or "failed to call a function" in text
        or "invalid tool call" in text
        or "tool choice is required" in text
        or "tool choice is none" in text
        or "tool_choice is none" in text
        or "model called a tool" in text
        or "output_parse_failed" in text
        or "tools should have a name" in text
        or "failed to render tokens with harmony" in text
    )


def sanitize_messages_for_chat(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare messages for direct chat completion where tools are not active.
    1. Removes tool-specific instructions from system prompts.
    2. Appends an explicit directive instructing the model to reply in plain markdown text.
    3. Transforms assistant tool_calls and tool-role result messages into plain text summaries.
    """
    clean_messages: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")

        if role == "system":
            text = content or ""
            # Strip tool-specific directives if present
            text = re.sub(
                r"For code changes \(edit current file or create a new file\):.*?(Keep changes minimal|$)",
                "",
                text,
                flags=re.DOTALL,
            )
            text = re.sub(r"1\.\s*Prefer apply_patch.*?(?=\n\n|\Z)", "", text, flags=re.DOTALL)
            text = re.sub(r"2\.\s*Use propose_edit.*?(?=\n\n|\Z)", "", text, flags=re.DOTALL)
            text = re.sub(r"3\.\s*Call finish.*?(?=\n\n|\Z)", "", text, flags=re.DOTALL)
            text = re.sub(r"4\.\s*Do NOT call create_plan.*?(?=\n\n|\Z)", "", text, flags=re.DOTALL)
            text = text.strip()

            chat_directive = (
                "\n\nIMPORTANT: You are in direct chat mode without tool execution capabilities. "
                "Provide all answers and code snippets directly as standard markdown text or code blocks. "
                "Do NOT attempt to call tools, invoke functions, or output tool call tags (e.g. <tool_call>, <function=...>, or JSON schemas)."
            )
            clean_messages.append({"role": "system", "content": (text + chat_directive).strip()})
        elif role == "assistant":
            if tool_calls and not content:
                call_summaries = []
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    call_summaries.append(f"[Called tool {fn.get('name', 'unknown')}]")
                clean_messages.append({"role": "assistant", "content": " ".join(call_summaries)})
            else:
                clean_messages.append({"role": "assistant", "content": content or ""})
        elif role == "tool":
            clean_messages.append({
                "role": "user",
                "content": f"[Tool execution result]: {content or ''}",
            })
        else:
            clean_messages.append(dict(msg))
    return clean_messages


def extract_failed_generation(error: Any) -> Optional[str]:
    """Pull Groq's failed_generation payload from an exception, if present."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or body
        if isinstance(err, dict) and err.get("failed_generation") is not None:
            fg = err["failed_generation"]
            return fg if isinstance(fg, str) else json_dumps_safe(fg)

    # httpx/groq often put JSON in response.json()
    response = getattr(error, "response", None)
    if response is not None:
        try:
            data = response.json()
            err = (data or {}).get("error") or data
            if isinstance(err, dict) and err.get("failed_generation") is not None:
                fg = err["failed_generation"]
                return fg if isinstance(fg, str) else json_dumps_safe(fg)
        except Exception:
            pass

    text = str(error)
    # Prefer a JSON object after failed_generation (common for tool_use_failed)
    marker = "failed_generation"
    idx = text.find(marker)
    if idx >= 0:
        rest = text[idx + len(marker):].lstrip(" ':\"=")
        if rest.startswith("{"):
            try:
                obj, _ = __import__("json").JSONDecoder().raw_decode(rest)
                return json_dumps_safe(obj) if not isinstance(obj, str) else obj
            except Exception:
                pass
        # Quoted JSON string value
        if rest.startswith("'") or rest.startswith('"'):
            quote = rest[0]
            # Find matching end is hard with escapes; try json.loads on a reconstructed string
            try:
                # Slice from first { inside the quoted region
                brace = rest.find("{")
                if brace >= 0:
                    obj, _ = __import__("json").JSONDecoder().raw_decode(rest[brace:])
                    return json_dumps_safe(obj) if not isinstance(obj, str) else obj
            except Exception:
                pass

    match = re.search(
        r"failed_generation['\"]?\s*:\s*(\{.*\})",
        text,
        re.DOTALL,
    )
    if match:
        return match.group(1)
    return None


def normalize_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Map common model aliases (path/content) onto Crystal schema names."""
    if not isinstance(args, dict):
        return {}
    out = dict(args)
    if "path" in out and "file_path" not in out:
        out["file_path"] = out.pop("path")
    if tool_name in ("propose_edit", "write_file"):
        if "content" in out and "new_content" not in out:
            out["new_content"] = out.pop("content")
    if tool_name == "run_terminal" and "cmd" in out and "command" not in out:
        out["command"] = out.pop("cmd")
    return out


def json_dumps_safe(value: Any) -> str:
    try:
        import json as _json
        return _json.dumps(value)
    except Exception:
        return str(value)


def parse_max_tokens_limit(error: Any) -> Optional[int]:
    """Extract allowed max_tokens from Groq 400 errors when present."""
    text = str(error)
    match = re.search(
        r"max_tokens[`'\"]?\s*must be less than or equal to\s*`?(\d+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    match = re.search(r"less than or equal to\s*`?(\d+)`?", text, re.IGNORECASE)
    if match and "max_tokens" in text.lower():
        return int(match.group(1))
    return None


def friendly_llm_error(error: Any, model: Optional[str] = None) -> str:
    text = str(error).lower()
    if "tool choice is none" in text or "tool_choice is none" in text or "model called a tool" in text:
        return (
            f"The model attempted to format a tool call when tools were disabled. "
            "Please retry or switch to an agent-capable model."
        )
    if is_unsupported_chat_model_error(error):
        return (
            f"Model `{model or 'selected'}` does not support chat. "
            f"Pick a chat model in Settings (e.g. {DEFAULT_MODEL}), or clear the model field."
        )
    if is_tools_not_supported_error(error):
        return (
            f"Model `{model or 'selected'}` does not support Crystal tool calling. "
            "Use llama-3.3-70b-versatile or openai/gpt-oss-120b for agent edits."
        )
    limit = parse_max_tokens_limit(error)
    if limit is not None:
        return (
            f"Model `{model or 'selected'}` only allows max_tokens ≤ {limit}. "
            "Choose a coding chat model in Settings, or clear the model field to use the default."
        )
    if is_payload_too_large_error(error):
        return (
            "Request was too large for Groq (context/TPM limit). "
            "Try a shorter message, a smaller open file, or clear chat history."
        )
    return str(error)


def get_groq_client(
    user_key: Optional[str] = None,
    user_model: Optional[str] = None,
    fallback_client: Any = None,
    fallback_key: Optional[str] = None,
) -> Tuple[Any, str, bool]:
    """
    Return (client, model_name, initialized).
    Uses the user-provided key when present; otherwise the server default.
    Rejects non-chat models (whisper, TTS, prompt-guard) and falls back to default.
    """
    key = resolve_api_key(user_key)
    model_name = resolve_model(user_model)
    if not key:
        return None, model_name, False

    if (
        fallback_client is not None
        and fallback_key
        and key == fallback_key
    ):
        return fallback_client, model_name, True

    try:
        from groq import Groq
        return Groq(api_key=key), model_name, True
    except ImportError:
        return None, model_name, False
