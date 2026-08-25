import logging
import json
import re
import uuid
import difflib
from typing import AsyncIterator, Dict, List, Any, Optional, Tuple

from services.tool_executor import AGENT_TOOL_NAMES
from services.llm_config import (
    CHAT_MAX_TOKENS,
    DEFAULT_API_KEY,
    DEFAULT_MODEL,
    EDIT_TOOL_MAX_TOKENS,
    MAX_AGENT_STEPS,
    SELECTED_CODE_CHAR_CAP,
    TOOL_MAX_TOKENS,
    TOOL_RESULT_CHAR_CAP,
    extract_failed_generation,
    fit_max_tokens,
    friendly_llm_error,
    get_groq_client,
    is_payload_too_large_error,
    is_tool_use_failed_error,
    is_tools_not_supported_error,
    is_unsupported_chat_model_error,
    merge_system_prompt,
    normalize_tool_args,
    parse_max_tokens_limit,
    sanitize_messages_for_chat,
    supports_tools,
    trim_messages_to_budget,
    truncate_text,
)

logger = logging.getLogger(__name__)

LOCAL_EDIT_TOOLS = {
    "propose_edit",
    "apply_patch",
    "create_plan",
    "update_todo",
    "run_terminal",
    "finish",
    "read_file",
}

PLANNING_TOOLS = {"create_plan", "update_todo"}

# Direct (Plan-off) edits: change/create files without formal planning.
DIRECT_EDIT_TOOLS = {
    "propose_edit",
    "apply_patch",
    "read_file",
    "finish",
}

DIRECT_REPO_TOOLS = AGENT_TOOL_NAMES - PLANNING_TOOLS

DIRECT_MAX_STEPS = 6

IMPL_HINTS = re.compile(
    r"\b(make|create|implement|build|code|write|generate|develop|author|produce|"
    r"refactor|fix|add|update|change|rewrite|migrate|debug|patch|edit|remove|"
    r"delete|rename|test|script|program|app|module|function|class|file|calculator|readme)\b",
    re.IGNORECASE,
)

# #region agent log
_DEBUG_LOG_PATH = r"C:\Users\saatw\Downloads\crystal\debug-afc31b.log"


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: Dict[str, Any]) -> None:
    try:
        import time
        payload = {
            "sessionId": "afc31b",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass
# #endregion


class AgentPlanner:
    """
    Multi-step agent: plan → explore → patch → verify → finish.
    """

    def __init__(self, tool_executor, chat_service):
        self.tool_executor = tool_executor
        self.chat_service = chat_service
        self.model_name = DEFAULT_MODEL
        self.api_key = DEFAULT_API_KEY
        self.client, _, self.initialized = get_groq_client()

    async def process_user_request(
        self,
        message: str,
        repo_id: str,
        context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
        conversation_history: List[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        user_system_prompt: Optional[str] = None,
        enable_planning: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        if conversation_history is None:
            conversation_history = []

        client, model_name, initialized = get_groq_client(
            user_key=api_key,
            user_model=model,
            fallback_client=self.client,
            fallback_key=self.api_key,
        )

        request_id = str(uuid.uuid4())
        proposed_edits: List[Dict[str, Any]] = []

        try:
            has_repo = repo_id not in ("local", "none", "__none__", None, "")
            has_indexed_files = bool((context or {}).get("total_files"))
            local_edit_mode = (not has_indexed_files) and bool(selected_file)
            local_session = not has_indexed_files
            wants_impl = bool(IMPL_HINTS.search(message or ""))
            model_supports_tools = supports_tools(model_name)
            use_tools = (
                model_supports_tools
                and (
                    (has_repo and has_indexed_files)
                    or local_edit_mode
                    or (has_repo and wants_impl)
                    or (local_session and wants_impl)
                )
            )

            if not use_tools:
                base_prompt = self._build_direct_chat_system_prompt(
                    context, selected_file, selected_code
                )
            elif enable_planning:
                base_prompt = self._build_agent_system_prompt(
                    context, selected_file, selected_code
                )
            else:
                base_prompt = self._build_chat_system_prompt(
                    context, selected_file, selected_code
                )
            system_prompt = merge_system_prompt(base_prompt, user_system_prompt)

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                *conversation_history,
                {"role": "user", "content": message},
            ]

            if not initialized:
                yield {
                    "type": "message",
                    "content": "Mock response. Configure GROQ_API_KEY for full agent capabilities.",
                }
                return

            if not use_tools:
                if not model_supports_tools:
                    yield {
                        "type": "planning",
                        "content": (
                            f"{model_name} does not support Crystal tools — "
                            "answering in chat mode. Use llama-3.3-70b-versatile "
                            "or openai/gpt-oss-120b for agent edits."
                        ),
                    }
                async for event in self._stream_final_response(
                    messages, client, model_name
                ):
                    yield event
                yield {"type": "end"}
                return

            if enable_planning:
                if local_session:
                    tool_names = set(LOCAL_EDIT_TOOLS)
                else:
                    tool_names = set(AGENT_TOOL_NAMES)
                max_steps = MAX_AGENT_STEPS
            else:
                if local_session:
                    tool_names = set(DIRECT_EDIT_TOOLS)
                else:
                    tool_names = set(DIRECT_REPO_TOOLS)
                max_steps = min(DIRECT_MAX_STEPS, MAX_AGENT_STEPS)

            tools = self.tool_executor.get_tool_schemas(tool_names)

            soft_apply = has_repo and has_indexed_files
            self.tool_executor.begin_session(
                request_id,
                repo_id=repo_id or "",
                soft_apply=soft_apply,
                selected_file=selected_file,
                selected_code=selected_code,
            )

            if enable_planning:
                yield {"type": "planning", "content": "Starting agent loop…"}

            done = False

            for step in range(1, max_steps + 1):
                if enable_planning:
                    yield {
                        "type": "step",
                        "step": step,
                        "max_steps": max_steps,
                        "content": f"Step {step}/{max_steps}",
                    }

                desired_max = (
                    EDIT_TOOL_MAX_TOKENS if local_edit_mode else TOOL_MAX_TOKENS
                )
                step_messages = trim_messages_to_budget(
                    messages, reserve_completion=desired_max, tools=tools
                )
                tool_max_tokens = fit_max_tokens(
                    step_messages,
                    desired_max,
                    model=model_name,
                    tools=tools,
                )

                response = None
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=step_messages,
                        tools=tools,
                        tool_choice="auto",
                        max_tokens=tool_max_tokens,
                        temperature=0.1,
                    )
                except Exception as api_error:
                    logger.warning(
                        "Agent step %s tool call failed (%s): %s",
                        step,
                        model_name,
                        api_error,
                    )

                    # #region agent log
                    _agent_dbg(
                        "A",
                        "agent_planner.py:tool_error",
                        "step tool call failed",
                        {
                            "step": step,
                            "model": model_name,
                            "enable_planning": enable_planning,
                            "error_head": str(api_error)[:400],
                            "is_tool_use_failed": is_tool_use_failed_error(api_error),
                            "has_path_schema_error": "additionalProperties 'path'" in str(api_error)
                            or "missing properties: 'file_path'" in str(api_error),
                            "has_harmony_name_error": "Tools should have a name" in str(api_error),
                            "n_tools": len(tools),
                            "tool_names": [
                                (t.get("function") or {}).get("name") for t in tools
                            ],
                        },
                    )
                    # #endregion

                    if is_tools_not_supported_error(api_error) or (
                        is_unsupported_chat_model_error(api_error)
                    ):
                        yield {
                            "type": "error",
                            "error": friendly_llm_error(api_error, model_name),
                        }
                        self.tool_executor.end_session()
                        return

                    recovered = self._recover_failed_tool_generation(
                        str(api_error), error=api_error
                    )
                    # #region agent log
                    _agent_dbg(
                        "B",
                        "agent_planner.py:recovery",
                        "failed_generation recovery attempt",
                        {
                            "step": step,
                            "recovered": bool(recovered),
                            "tool_name": recovered[0] if recovered else None,
                            "arg_keys": list((recovered[1] or {}).keys()) if recovered else None,
                            "failed_generation_head": (
                                (extract_failed_generation(api_error) or "")[:300]
                            ),
                            "body_type": type(getattr(api_error, "body", None)).__name__,
                        },
                    )
                    # #endregion
                    if recovered:
                        tool_name, tool_args = recovered
                        tool_args = normalize_tool_args(tool_name, tool_args)
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
                        async for event in self._run_single_tool(
                            repo_id,
                            tool_name,
                            tool_args,
                            "recovered_call",
                            messages,
                            proposed_edits,
                            selected_file=selected_file,
                            selected_code=selected_code,
                        ):
                            yield event
                        if tool_name == "finish":
                            done = True
                            break
                        continue

                    limit = parse_max_tokens_limit(api_error)
                    if limit is not None:
                        tool_max_tokens = min(tool_max_tokens, limit)
                        try:
                            response = client.chat.completions.create(
                                model=model_name,
                                messages=step_messages,
                                tools=tools,
                                tool_choice="auto",
                                max_tokens=tool_max_tokens,
                                temperature=0.2,
                            )
                        except Exception as retry_error:
                            yield {
                                "type": "error",
                                "error": friendly_llm_error(retry_error, model_name),
                            }
                            self.tool_executor.end_session()
                            return
                    elif is_payload_too_large_error(api_error):
                        step_messages = trim_messages_to_budget(
                            messages, reserve_completion=768, tools=tools
                        )
                        try:
                            response = client.chat.completions.create(
                                model=model_name,
                                messages=step_messages,
                                tools=tools,
                                tool_choice="auto",
                                max_tokens=fit_max_tokens(
                                    step_messages, 768, model=model_name, tools=tools
                                ),
                                temperature=0.2,
                            )
                        except Exception:
                            async for event in self._fallback_chat_response(
                                messages, client, model_name
                            ):
                                yield event
                            self.tool_executor.end_session()
                            return
                    elif is_tool_use_failed_error(api_error):
                        # #region agent log
                        _agent_dbg(
                            "C",
                            "agent_planner.py:tool_use_failed_retry",
                            "coaching model instead of blind retry",
                            {
                                "step": step,
                                "n_messages": len(messages),
                                "tool_names": [
                                    (t.get("function") or {}).get("name") for t in tools
                                ],
                            },
                        )
                        # #endregion
                        messages.append({
                            "role": "user",
                            "content": (
                                "Your last tool call was rejected by the API. "
                                "Use exact parameter names from the tool schema: "
                                "file_path (never path), new_content (never content), "
                                "old_string/new_string for apply_patch. Retry the tool call."
                            ),
                        })
                        continue
                    else:
                        async for event in self._fallback_chat_response(
                            messages, client, model_name
                        ):
                            yield event
                        self.tool_executor.end_session()
                        return

                if response is None:
                    break

                assistant_message = response.choices[0].message
                tool_calls = assistant_message.tool_calls or []

                if not tool_calls:
                    if assistant_message.content:
                        yield {
                            "type": "message",
                            "content": assistant_message.content,
                        }
                    done = True
                    break

                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                verify_failures: List[str] = []

                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    raw_arguments = tool_call.function.arguments
                    try:
                        tool_args = json.loads(raw_arguments) if raw_arguments else {}
                    except json.JSONDecodeError:
                        tool_args = {}
                    if not isinstance(tool_args, dict):
                        tool_args = {}
                    tool_args = normalize_tool_args(tool_name, tool_args)

                    async for event in self._run_single_tool(
                        repo_id,
                        tool_name,
                        tool_args,
                        tool_call.id,
                        messages,
                        proposed_edits,
                        selected_file=selected_file,
                        selected_code=selected_code,
                        collect_failures=verify_failures if enable_planning else None,
                    ):
                        yield event

                    if tool_name == "finish":
                        done = True

                if done:
                    break

                if enable_planning and verify_failures:
                    messages.append({
                        "role": "user",
                        "content": (
                            "Fix the failures below, then re-verify with run_terminal "
                            "or call finish if blocked:\n"
                            + "\n".join(verify_failures[:5])
                        ),
                    })

            session_info = self.tool_executor.end_session()

            if proposed_edits:
                by_path: Dict[str, Dict[str, Any]] = {}
                for edit in proposed_edits:
                    path = edit.get("file_path") or ""
                    if path in by_path:
                        by_path[path] = {
                            **edit,
                            "original": by_path[path].get("original", edit.get("original")),
                            "proposed": edit.get("proposed"),
                            "diff": edit.get("diff"),
                        }
                    else:
                        by_path[path] = edit
                yield {
                    "type": "edit_proposal",
                    "request_id": session_info.get("request_id") or request_id,
                    "edits": list(by_path.values()),
                    "applied": soft_apply,
                }

            if not done:
                if enable_planning:
                    messages.append({
                        "role": "user",
                        "content": (
                            "Max steps reached. Summarize progress and remaining work. "
                            "Do not invent unapplied code."
                        ),
                    })
                    async for event in self._stream_final_response(
                        messages, client, model_name
                    ):
                        yield event
                elif not proposed_edits:
                    async for event in self._stream_final_response(
                        messages, client, model_name
                    ):
                        yield event

            yield {"type": "end"}

        except Exception as e:
            logger.error(f"Agent processing error: {e}")
            try:
                self.tool_executor.end_session()
            except Exception:
                pass
            if "tool_use_failed" in str(e).lower() or is_tools_not_supported_error(e) or is_tool_use_failed_error(e):
                async for event in self._fallback_chat_response(
                    messages if "messages" in locals() else [
                        {"role": "user", "content": message or ""}
                    ],
                    client,
                    model_name,
                ):
                    yield event
                return
            yield {"type": "error", "error": str(e)}

    async def _run_single_tool(
        self,
        repo_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: str,
        messages: List[Dict[str, Any]],
        proposed_edits: List[Dict[str, Any]],
        selected_file: str = None,
        selected_code: str = None,
        collect_failures: Optional[List[str]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        safe_args = {
            k: v for k, v in (tool_args or {}).items()
            if k not in ("new_content", "old_string", "new_string")
        }
        yield {"type": "tool_call", "tool": tool_name, "args": safe_args}

        result = await self.tool_executor.execute_tool(
            tool_name, repo_id, **(tool_args or {})
        )

        payload = result.get("result") if result.get("status") == "success" else result

        if tool_name in ("propose_edit", "apply_patch") and result.get("status") == "success":
            edit = payload if isinstance(payload, dict) else {}
            if tool_name == "propose_edit":
                edit = self._enrich_edit_original(edit, selected_file, selected_code)
            if edit.get("file_path"):
                proposed_edits.append(edit)
            validation = (edit or {}).get("validation") or {}
            if not validation.get("ok", True) and collect_failures is not None:
                errs = validation.get("errors") or [edit.get("error") or "validation failed"]
                collect_failures.append(
                    f"{edit.get('file_path')}: " + "; ".join(str(e) for e in errs)
                )

        if tool_name == "create_plan" and isinstance(payload, dict):
            yield {"type": "plan", "goal": payload.get("goal"), "todos": payload.get("todos")}

        if tool_name == "update_todo" and isinstance(payload, dict):
            yield {
                "type": "todo_update",
                "id": payload.get("id"),
                "status": payload.get("status"),
                "note": payload.get("note"),
                "plan": payload.get("plan"),
            }

        if tool_name == "run_terminal":
            term = payload if isinstance(payload, dict) else {"error": str(payload)}
            yield {
                "type": "terminal",
                "command": term.get("command") or tool_args.get("command"),
                "returncode": term.get("returncode"),
                "stdout": truncate_text(term.get("stdout") or "", 4000),
                "stderr": truncate_text(term.get("stderr") or "", 2000),
                "status": term.get("status") or result.get("status"),
                "error": term.get("error"),
            }
            if collect_failures is not None and (
                term.get("returncode") not in (0, None)
                or term.get("status") in ("failed", "error")
            ):
                collect_failures.append(
                    f"Terminal `{term.get('command')}` exit {term.get('returncode')}: "
                    f"{(term.get('stderr') or term.get('error') or term.get('stdout') or '')[:800]}"
                )

        if tool_name == "finish" and isinstance(payload, dict) and payload.get("summary"):
            yield {"type": "message", "content": payload["summary"]}

        tool_content = self._compact_tool_result(tool_name, result)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_content,
        })

        yield {
            "type": "tool_result",
            "tool": tool_name,
            "result": self._public_tool_result(tool_name, result),
        }

    def _compact_tool_result(self, tool_name: str, result: Dict[str, Any]) -> str:
        data = result.get("result") if result.get("status") == "success" else result
        if tool_name in ("propose_edit", "apply_patch") and isinstance(data, dict):
            slim = {
                "file_path": data.get("file_path"),
                "applied": data.get("applied"),
                "validation": data.get("validation"),
                "rationale": data.get("rationale"),
                "is_new_file": data.get("is_new_file"),
                "error": data.get("error"),
                "diff_preview": truncate_text(data.get("diff") or "", 1500),
            }
            return truncate_text(json.dumps(slim), TOOL_RESULT_CHAR_CAP)
        if tool_name == "read_file" and isinstance(data, str):
            return truncate_text(data, TOOL_RESULT_CHAR_CAP)
        if tool_name == "run_terminal" and isinstance(data, dict):
            slim = {
                "command": data.get("command"),
                "returncode": data.get("returncode"),
                "status": data.get("status"),
                "stdout": truncate_text(data.get("stdout") or "", 3000),
                "stderr": truncate_text(data.get("stderr") or "", 1500),
                "error": data.get("error"),
            }
            return truncate_text(json.dumps(slim), TOOL_RESULT_CHAR_CAP)
        try:
            return truncate_text(json.dumps(data, default=str), TOOL_RESULT_CHAR_CAP)
        except Exception:
            return truncate_text(str(data), TOOL_RESULT_CHAR_CAP)

    def _public_tool_result(self, tool_name: str, result: Dict[str, Any]) -> Any:
        if result.get("status") != "success":
            return result
        data = result.get("result")
        if tool_name in ("propose_edit", "apply_patch") and isinstance(data, dict):
            return {
                "file_path": data.get("file_path"),
                "applied": data.get("applied"),
                "validation": data.get("validation"),
                "rationale": data.get("rationale"),
                "is_new_file": data.get("is_new_file"),
                "error": data.get("error"),
            }
        if tool_name == "read_file" and isinstance(data, str):
            return truncate_text(data, 2000)
        return data

    def _enrich_edit_original(
        self,
        edit: Dict[str, Any],
        selected_file: Optional[str],
        selected_code: Optional[str],
    ) -> Dict[str, Any]:
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

    def _recover_failed_tool_generation(
        self,
        error_text: str,
        error: Any = None,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        candidates = [error_text]
        failed = extract_failed_generation(error) if error is not None else None
        if failed:
            candidates.insert(0, failed)

        for blob in candidates:
            if not blob:
                continue

            # 1. Check for XML tool_call tags: <tool_call>...</tool_call>
            tc_match = re.search(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", blob, re.DOTALL)
            if tc_match:
                inner = tc_match.group(1).strip()
                try:
                    parsed = json.loads(inner)
                    if isinstance(parsed, dict):
                        tool_name = parsed.get("name") or parsed.get("tool") or ""
                        raw_args = parsed.get("arguments") or parsed.get("parameters") or {}
                        if tool_name in AGENT_TOOL_NAMES:
                            if isinstance(raw_args, str):
                                try:
                                    raw_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    raw_args = {}
                            if isinstance(raw_args, dict):
                                return tool_name, normalize_tool_args(tool_name, raw_args)
                except Exception:
                    pass

            # 2. Check for <function=name>{args}</function>
            tool_match = re.search(r"<function=(\w+)\s*>?\s*", blob)
            if tool_match:
                tool_name = tool_match.group(1)
                rest = blob[tool_match.end():].lstrip()
                if tool_name in AGENT_TOOL_NAMES and rest.startswith("{"):
                    try:
                        args, _ = json.JSONDecoder().raw_decode(rest)
                        if isinstance(args, dict):
                            return tool_name, normalize_tool_args(tool_name, args)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Could not parse recovered tool arguments for %s",
                            tool_name,
                        )

            # 3. Direct JSON parsing
            try:
                parsed = json.loads(blob) if blob.strip().startswith("{") else None
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                tool_name = parsed.get("name") or parsed.get("tool") or ""
                raw_args = parsed.get("arguments") or parsed.get("parameters") or {}
                if tool_name in AGENT_TOOL_NAMES:
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            raw_args = {}
                    if isinstance(raw_args, dict):
                        return tool_name, normalize_tool_args(tool_name, raw_args)

            # 4. Search for any JSON object containing tool name in blob
            for match_obj in re.finditer(r'\{\s*"name"\s*:\s*"(\w+)"', blob):
                potential_name = match_obj.group(1)
                if potential_name in AGENT_TOOL_NAMES:
                    start_pos = match_obj.start()
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(blob[start_pos:])
                        if isinstance(obj, dict):
                            raw_args = obj.get("arguments") or obj.get("parameters") or {}
                            if isinstance(raw_args, str):
                                try:
                                    raw_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    raw_args = {}
                            if isinstance(raw_args, dict):
                                return potential_name, normalize_tool_args(potential_name, raw_args)
                    except Exception:
                        pass

            # 5. Bare function call: read_file(...)
            bare = re.search(
                r"\b("
                + "|".join(
                    re.escape(n) for n in sorted(AGENT_TOOL_NAMES, key=len, reverse=True)
                )
                + r")\s*\(\s*",
                blob,
            )
            if bare:
                tool_name = bare.group(1)
                rest = blob[bare.end():].lstrip()
                if rest.startswith("{"):
                    try:
                        args, _ = json.JSONDecoder().raw_decode(rest)
                        if isinstance(args, dict):
                            return tool_name, normalize_tool_args(tool_name, args)
                    except json.JSONDecodeError:
                        pass

        return None

    async def _fallback_chat_response(
        self,
        messages: List[Dict[str, Any]],
        client=None,
        model_name: str = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        logger.warning("Tool calling failed; falling back to direct chat response")
        async for event in self._stream_chat_completion(
            messages, client, model_name, end=True
        ):
            yield event

    async def _stream_final_response(
        self,
        messages: List[Dict[str, Any]],
        client=None,
        model_name: str = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for event in self._stream_chat_completion(
            messages, client, model_name, end=False
        ):
            yield event

    async def _stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        client=None,
        model_name: str = None,
        end: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "response", "content": ""}

        llm = client or self.client
        model = model_name or self.model_name
        sanitized = sanitize_messages_for_chat(messages)
        safe_messages = trim_messages_to_budget(
            sanitized, reserve_completion=CHAT_MAX_TOKENS
        )
        max_out = fit_max_tokens(safe_messages, CHAT_MAX_TOKENS, model=model)

        try:
            stream = llm.chat.completions.create(
                model=model,
                messages=safe_messages,
                stream=True,
                max_tokens=max_out,
                temperature=0.2,
            )
        except Exception as api_error:
            if is_tool_use_failed_error(api_error):
                fg = extract_failed_generation(api_error)
                if fg:
                    clean_fg = re.sub(r"^<tool_call>\s*", "", fg, flags=re.IGNORECASE)
                    clean_fg = re.sub(r"\s*</tool_call>$", "", clean_fg, flags=re.IGNORECASE)
                    try:
                        parsed_json = json.loads(clean_fg)
                        if isinstance(parsed_json, dict) and ("name" in parsed_json or "arguments" in parsed_json):
                            args = parsed_json.get("arguments") or {}
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    pass
                            content_val = args.get("new_content") or args.get("content") or clean_fg
                            yield {"type": "content", "content": str(content_val)}
                            if end:
                                yield {"type": "end"}
                            return
                    except Exception:
                        pass
                    yield {"type": "content", "content": clean_fg}
                    if end:
                        yield {"type": "end"}
                    return
            limit = parse_max_tokens_limit(api_error)
            if limit is not None:
                try:
                    stream = llm.chat.completions.create(
                        model=model,
                        messages=safe_messages,
                        stream=True,
                        max_tokens=min(max_out, limit),
                        temperature=0.2,
                    )
                except Exception as retry_error:
                    yield {
                        "type": "error",
                        "error": friendly_llm_error(retry_error, model),
                    }
                    if end:
                        yield {"type": "end"}
                    return
            elif is_payload_too_large_error(api_error):
                tighter = trim_messages_to_budget(
                    safe_messages, reserve_completion=512
                )
                try:
                    stream = llm.chat.completions.create(
                        model=model,
                        messages=tighter,
                        stream=True,
                        max_tokens=fit_max_tokens(tighter, 512, model=model),
                        temperature=0.2,
                    )
                except Exception as retry_error:
                    yield {
                        "type": "error",
                        "error": friendly_llm_error(retry_error, model),
                    }
                    if end:
                        yield {"type": "end"}
                    return
            else:
                yield {
                    "type": "error",
                    "error": friendly_llm_error(api_error, model),
                }
                if end:
                    yield {"type": "end"}
                return

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "type": "content",
                    "content": chunk.choices[0].delta.content,
                }

        if end:
            yield {"type": "end"}

    def _append_context(
        self,
        prompt: str,
        repository_context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
    ) -> str:
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
            clipped = truncate_text(selected_code, SELECTED_CODE_CHAR_CAP)
            prompt += (
                "\nThe current file may be unsaved and absent from the repository. "
                "read_file and apply_patch use its editor buffer during this request. "
                "Current file contents (use as reference; "
                "if truncated, preserve omitted sections when suggesting edits):\n"
                f"```\n{clipped}\n```\n"
            )

        return prompt

    def _build_direct_chat_system_prompt(
        self,
        repository_context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
    ) -> str:
        """Pure chat response without any tool directives."""
        prompt = """You are an expert AI coding assistant.
Answer questions and provide solutions directly in chat with clear explanations and code blocks.
Do NOT attempt to call tools, invoke functions, or output tool call tags (e.g. <tool_call>, <function=...>, or JSON schemas).
"""
        return self._append_context(
            prompt, repository_context, selected_file, selected_code
        )

    def _build_chat_system_prompt(
        self,
        repository_context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
    ) -> str:
        """Direct chat + edits — no formal plan / step checklist."""
        prompt = """You are an expert AI coding assistant.

For code requests (e.g. creating a new file, program, script, feature, or editing existing code):
1. ALWAYS create new files using propose_edit with full new_content (e.g. calculator.py, README.md). Include complete, working code and thorough docstrings/comments.
2. For existing files, prefer apply_patch for surgical edits (exact unique old_string → new_string).
3. Do NOT dump full code blocks or entire files into the chat message when creating or editing files with tools. The user expects code in new/edited files in their editor.
4. Call finish with a concise summary once all edits/new files are proposed.
5. Do NOT call create_plan or update_todo in direct edit mode.

For purely conceptual or informational questions with no file creation: answer clearly in chat.
"""
        return self._append_context(
            prompt, repository_context, selected_file, selected_code
        )

    def _build_agent_system_prompt(
        self,
        repository_context: Dict[str, Any] = None,
        selected_file: str = None,
        selected_code: str = None,
    ) -> str:
        has_repo_files = bool((repository_context or {}).get("total_files"))
        if has_repo_files:
            prompt = """You are an expert AI coding agent working in a real repository.

Workflow (follow this for non-trivial work):
1. Explore with search_repository / read_file / list_files / ast_lookup / find_references. Never guess file contents.
2. Call create_plan with a clear goal and ordered steps for multi-file or non-trivial changes.
3. Work one step at a time. Call update_todo as you start/finish each step.
4. For new files or scripts, use propose_edit with full new_content. Prefer apply_patch (exact unique old_string → new_string) for existing files.
5. After edits, verify with run_terminal when a test/lint command is obvious (pytest, npm test, tsc, eslint, ruff, mypy, etc.). Fix failures before finishing.
6. Call finish with a short summary when done. Do NOT dump large code samples in chat.

CRITICAL RULES:
- Never invent illustrative toy files.
- Never skip reading a file before patching it.
- Keep patches minimal and correct.
- Soft-applied edits are already on disk for verification; still be careful.
"""
        else:
            prompt = """You are an expert AI coding assistant.

For code changes or creating new files:
1. Call create_plan for multi-step work, then update_todo as you go.
2. For new files or scripts (e.g. calculator.py, README.md), ALWAYS use propose_edit with full new_content.
3. Prefer apply_patch for surgical edits to existing files.
4. You may run_terminal for quick checks when useful.
5. Call finish with a brief overview when done. Do NOT paste huge code blocks in chat.

For questions only, answer clearly without tools.
"""

        return self._append_context(
            prompt, repository_context, selected_file, selected_code
        )

    async def plan_refactoring(
        self,
        code: str,
        goal: str,
        language: str,
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
        return {"type": "plan", "plan": prompt}

    async def analyze_error(
        self,
        error: str,
        code: str,
        language: str,
        repo_id: str,
        repository_context: Dict[str, Any] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "analysis", "content": "Analyzing error..."}

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
                yield {"type": "analysis", "content": data["content"]}

        yield {"type": "suggestion", "content": "Suggesting fixes..."}

        prompt2 = """Now suggest how to fix this error.
Provide the corrected code."""

        messages.append({"role": "assistant", "content": ""})
        messages.append({"role": "user", "content": prompt2})

        async for response in self.chat_service.stream_chat(messages):
            data = json.loads(response)
            if data.get("type") == "content":
                yield {"type": "fix", "content": data["content"]}
