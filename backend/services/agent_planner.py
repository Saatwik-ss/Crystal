import logging
import json
import re
import uuid
import difflib
from typing import AsyncIterator, Dict, List, Any, Optional, Tuple
import os

from services.tool_executor import AGENT_TOOL_NAMES

logger = logging.getLogger(__name__)

LOCAL_EDIT_TOOLS = {"propose_edit"}


class AgentPlanner:
    """
    Orchestrates agent workflows using LLM and tools.
    Plans actions, calls tools, and streams responses.
    """

    def __init__(self, tool_executor, chat_service):
        self.tool_executor = tool_executor
        self.chat_service = chat_service
        self.model_name = os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL") or "llama-3.3-70b-versatile"
        self.api_key = os.getenv("GROQ_API_KEY")

        if self.api_key:
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key)
                self.initialized = True
            except ImportError:
                self.initialized = False
        else:
            self.initialized = False

    async def process_user_request(
        self,
        message: str,
        repo_id: str,
        context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
        conversation_history: List[Dict[str, str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        if conversation_history is None:
            conversation_history = []

        try:
            system_prompt = self._build_agent_system_prompt(context, selected_file, selected_code)

            messages = [{"role": "system", "content": system_prompt}, *conversation_history]
            messages.append({
                "role": "user",
                "content": message
            })

            has_repo = repo_id not in ("local", "none", "__none__", None, "")
            has_indexed_files = bool((context or {}).get("total_files"))
            local_edit_mode = (not has_indexed_files) and bool(selected_file)
            use_tools = (has_repo and has_indexed_files) or local_edit_mode

            if not self.initialized:
                yield {
                    "type": "message",
                    "content": "Mock response. Configure GROQ_API_KEY for full agent capabilities."
                }
                return

            if not use_tools:
                async for event in self._stream_final_response(messages):
                    yield event
                yield {"type": "end"}
                return

            if local_edit_mode:
                tools = self.tool_executor.get_tool_schemas(LOCAL_EDIT_TOOLS)
            else:
                tools = self.tool_executor.get_agent_tool_schemas()

            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=8192,
                    temperature=0,
                )
            except Exception as api_error:
                recovered = self._recover_failed_tool_generation(str(api_error))
                if recovered:
                    tool_name, tool_args = recovered
                    async for event in self._execute_recovered_tool(
                        repo_id, tool_name, tool_args, messages,
                        selected_file=selected_file,
                        selected_code=selected_code,
                    ):
                        yield event
                    return

                async for event in self._fallback_chat_response(messages):
                    yield event
                return

            assistant_message = response.choices[0].message

            if assistant_message.tool_calls:
                yield {
                    "type": "planning",
                    "content": "Planning actions..."
                }

                tool_results = []
                proposed_edits: List[Dict[str, Any]] = []

                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    raw_arguments = tool_call.function.arguments
                    tool_args = json.loads(raw_arguments) if raw_arguments else {}
                    if not isinstance(tool_args, dict):
                        tool_args = {}

                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": {k: v for k, v in tool_args.items() if k != "new_content"},
                    }

                    result = await self.tool_executor.execute_tool(
                        tool_name,
                        repo_id,
                        **(tool_args or {})
                    )

                    if tool_name == "propose_edit" and result.get("status") == "success":
                        edit = result.get("result") or {}
                        edit = self._enrich_edit_original(
                            edit, selected_file, selected_code
                        )
                        result = {**result, "result": edit}
                        proposed_edits.append(edit)

                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })

                    yield {
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": result
                    }

                request_id = str(uuid.uuid4())
                if proposed_edits:
                    yield {
                        "type": "edit_proposal",
                        "request_id": request_id,
                        "edits": proposed_edits,
                    }

                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })

                for result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result["tool_call_id"],
                        "content": result["content"]
                    })

                invalid = [
                    e for e in proposed_edits
                    if not (e.get("validation") or {}).get("ok", True)
                ]
                overview_hint = (
                    "Provide a brief overview of the proposed edits only "
                    "(which files, what changed). Do NOT paste example or "
                    "sample code. The user will review a diff UI to apply."
                )
                if invalid:
                    paths = ", ".join(e.get("file_path", "?") for e in invalid)
                    overview_hint += (
                        f" Note that validation failed for: {paths}. "
                        "Mention that briefly so the user can Reject or fix."
                    )

                messages.append({
                    "role": "user",
                    "content": overview_hint,
                })

                async for event in self._stream_final_response(messages):
                    yield event
            else:
                if assistant_message.content:
                    yield {
                        "type": "message",
                        "content": assistant_message.content
                    }

            yield {
                "type": "end"
            }

        except Exception as e:
            logger.error(f"Agent processing error: {e}")
            if "tool_use_failed" in str(e):
                async for event in self._fallback_chat_response(messages):
                    yield event
                return
            yield {
                "type": "error",
                "error": str(e)
            }

    def _enrich_edit_original(
        self,
        edit: Dict[str, Any],
        selected_file: Optional[str],
        selected_code: Optional[str],
    ) -> Dict[str, Any]:
        """Fill original from editor buffer when disk file is missing (local)."""
        if not edit:
            return edit
        original = edit.get("original") or ""
        file_path = (edit.get("file_path") or "").replace("\\", "/")
        sel = (selected_file or "").replace("\\", "/")
        if original == "" and selected_code and file_path and (
            file_path == sel or file_path.endswith("/" + sel) or sel.endswith(file_path)
        ):
            proposed = edit.get("proposed") or ""
            diff_lines = list(
                difflib.unified_diff(
                    selected_code.splitlines(keepends=True),
                    proposed.splitlines(keepends=True),
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    lineterm="",
                )
            )
            edit = {
                **edit,
                "original": selected_code,
                "diff": "\n".join(line.rstrip("\n") for line in diff_lines),
                "is_new_file": False,
            }
        return edit

    def _recover_failed_tool_generation(self, error_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        tool_match = re.search(
            r"<function=(\w+)\s*(\{.*?\})\s*</function>",
            error_text,
            re.DOTALL,
        )
        if not tool_match:
            return None

        tool_name, raw_args = tool_match.group(1), tool_match.group(2)
        if tool_name not in AGENT_TOOL_NAMES:
            return None

        try:
            return tool_name, json.loads(raw_args)
        except json.JSONDecodeError:
            logger.warning("Could not parse recovered tool arguments: %s", raw_args)
            return None

    async def _execute_recovered_tool(
        self,
        repo_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        messages: List[Dict[str, Any]],
        selected_file: str = None,
        selected_code: str = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "planning", "content": "Planning actions..."}
        yield {
            "type": "tool_call",
            "tool": tool_name,
            "args": {k: v for k, v in (tool_args or {}).items() if k != "new_content"},
        }

        result = await self.tool_executor.execute_tool(tool_name, repo_id, **(tool_args or {}))
        proposed_edits = []
        if tool_name == "propose_edit" and result.get("status") == "success":
            edit = self._enrich_edit_original(
                result.get("result") or {}, selected_file, selected_code
            )
            result = {**result, "result": edit}
            proposed_edits.append(edit)

        yield {"type": "tool_result", "tool": tool_name, "result": result}

        if proposed_edits:
            yield {
                "type": "edit_proposal",
                "request_id": str(uuid.uuid4()),
                "edits": proposed_edits,
            }

        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "recovered_call",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(tool_args),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": "recovered_call",
            "content": json.dumps(result),
        })
        messages.append({
            "role": "user",
            "content": (
                "Provide a brief overview of the proposed edits only. "
                "Do NOT paste example code."
            ),
        })

        async for event in self._stream_final_response(messages):
            yield event
        yield {"type": "end"}

    async def _fallback_chat_response(
        self,
        messages: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        logger.warning("Tool calling failed; falling back to direct chat response")
        yield {"type": "response", "content": ""}

        stream = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            max_tokens=2048,
            temperature=0.2,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "type": "content",
                    "content": chunk.choices[0].delta.content,
                }

        yield {"type": "end"}

    async def _stream_final_response(
        self,
        messages: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "response", "content": ""}

        stream = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            max_tokens=2048,
            temperature=0.2,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "type": "content",
                    "content": chunk.choices[0].delta.content,
                }

    def _build_agent_system_prompt(
        self,
        repository_context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None
    ) -> str:
        has_repo_files = bool((repository_context or {}).get("total_files"))
        if has_repo_files:
            prompt = """You are an expert AI coding agent that edits real project files.

Workflow:
1. Use search_repository / read_file / list_files / ast_lookup to understand the code. Never guess file contents.
2. When the user wants a code change, call propose_edit with the COMPLETE new file content (full file, not a snippet).
3. You may call propose_edit multiple times for multiple files.
4. After tools finish, give a short overview of what will change. Do NOT paste example code, sample snippets, or "for example" demos.

CRITICAL RULES:
- Never invent illustrative example files or toy snippets.
- propose_edit.new_content must be the entire file ready to replace the original.
- Only edit files that are needed for the request.
- Do not call write_file; the user applies changes from a diff UI after review.
"""
        else:
            prompt = """You are an expert AI coding assistant.

If the user is viewing a file and asks for a change, call propose_edit with that file_path and the COMPLETE updated file content.
Do NOT paste illustrative examples or "for example" sample code in your reply.
After proposing, give only a brief overview of the change. The user will review a diff UI to apply.

If they are only asking a question (no edit), answer clearly without dumping unnecessary code samples.
"""

        if repository_context:
            files = repository_context.get("files", [])
            languages = repository_context.get("languages", [])

            prompt += f"\nRepository Context:\n"
            prompt += f"- Total files: {repository_context.get('total_files', 0)}\n"
            prompt += f"- Languages: {', '.join(languages)}\n"

            if files and len(files) <= 30:
                prompt += "\nKey files:\n"
                for f in files[:15]:
                    prompt += f"- {f['path']}\n"

        if selected_file:
            prompt += f"\nCurrently viewing: {selected_file}\n"

        if selected_code:
            prompt += f"\nCurrent file contents (use this as the base for propose_edit):\n```\n{selected_code[:12000]}\n```\n"

        return prompt

    async def plan_refactoring(
        self,
        code: str,
        goal: str,
        language: str
    ) -> Dict[str, Any]:
        prompt = f"""Plan a {language} refactoring with this goal:
{goal}

Code to refactor:
```{language}
{code}
```

Provide a structured plan with:
1. What needs to change
2. Why each change is necessary
3. Order of changes
4. Potential risks
"""
        return {
            "type": "plan",
            "plan": prompt
        }

    async def analyze_error(
        self,
        error: str,
        code: str,
        language: str,
        repo_id: str,
        repository_context: Dict[str, Any] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {
            "type": "analysis",
            "content": "Analyzing error..."
        }

        prompt = f"""Analyze this {language} error:

Error message:
{error}

Code causing error:
```{language}
{code}
```

First, explain what the error means and why it's happening."""

        messages = [{"role": "user", "content": prompt}]

        async for response in self.chat_service.stream_chat(messages):
            data = json.loads(response)
            if data.get("type") == "content":
                yield {
                    "type": "analysis",
                    "content": data["content"]
                }

        yield {
            "type": "suggestion",
            "content": "Suggesting fixes..."
        }

        prompt2 = """Now suggest how to fix this error.
Provide the corrected code."""

        messages.append({"role": "assistant", "content": ""})
        messages.append({"role": "user", "content": prompt2})

        async for response in self.chat_service.stream_chat(messages):
            data = json.loads(response)
            if data.get("type") == "content":
                yield {
                    "type": "fix",
                    "content": data["content"]
                }
