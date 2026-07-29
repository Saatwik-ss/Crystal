import logging
import asyncio
import json
import re
from typing import AsyncIterator, Dict, List, Any, Optional, Tuple
import os

from services.tool_executor import AGENT_TOOL_NAMES

logger = logging.getLogger(__name__)

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
        """
        Process user request using agent planning:
        1. Understand the goal
        2. Plan the workflow
        3. Execute tools as needed
        4. Generate response
        """
        
        if conversation_history is None:
            conversation_history = []
        
        try:
            # Build messages for LLM
            system_prompt = self._build_agent_system_prompt(context, selected_file, selected_code)
            
            messages = [{"role": "system", "content": system_prompt}, *conversation_history]
            messages.append({
                "role": "user",
                "content": message
            })
            
            # Local / no-repo sessions: answer directly without tools
            has_repo = repo_id not in ("local", "none", "__none__", None, "")
            has_indexed_files = bool((context or {}).get("total_files"))
            use_tools = has_repo and has_indexed_files
            
            # If no API key, use basic chat
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
            
            # Get tool schemas for function calling
            tools = self.tool_executor.get_agent_tool_schemas()
            
            # Call LLM with tools
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=2048,
                    temperature=0,
                )
            except Exception as api_error:
                recovered = self._recover_failed_tool_generation(str(api_error))
                if recovered:
                    tool_name, tool_args = recovered
                    async for event in self._execute_recovered_tool(
                        repo_id, tool_name, tool_args, messages
                    ):
                        yield event
                    yield {"type": "end"}
                    return

                async for event in self._fallback_chat_response(messages):
                    yield event
                return
            
            # Process response
            assistant_message = response.choices[0].message
            
            # Check for tool calls
            if assistant_message.tool_calls:
                yield {
                    "type": "planning",
                    "content": "Planning actions..."
                }
                
                # Execute tool calls
                tool_results = []
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    raw_arguments = tool_call.function.arguments
                    # #region agent log
                    from debug_log import debug_log
                    debug_log("B", "agent_planner.py:tool_call", "received tool call", {
                        "tool_name": tool_name,
                        "raw_arguments": raw_arguments,
                        "raw_arguments_type": type(raw_arguments).__name__ if raw_arguments is not None else "NoneType",
                    })
                    # #endregion
                    tool_args = json.loads(raw_arguments) if raw_arguments else {}
                    if not isinstance(tool_args, dict):
                        tool_args = {}
                    
                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args
                    }
                    
                    # Execute tool
                    result = await self.tool_executor.execute_tool(
                        tool_name,
                        repo_id,
                        **(tool_args or {})
                    )
                    
                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })
                    
                    yield {
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": result
                    }
                
                # Follow-up call with tool results
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
                
                # Add tool results to messages
                for result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result["tool_call_id"],
                        "content": result["content"]
                    })
                
                # Stream final response
                async for event in self._stream_final_response(messages):
                    yield event
            else:
                # No tool calls, just respond
                # #region agent log
                from debug_log import debug_log
                debug_log("D", "agent_planner.py:no_tool_calls", "assistant responded without structured tool_calls", {
                    "content_preview": (assistant_message.content or "")[:300],
                    "has_function_markup": "<function" in (assistant_message.content or ""),
                })
                # #endregion
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

    def _recover_failed_tool_generation(self, error_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Recover tool calls from Groq's failed_generation payload when present."""
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
    ) -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "planning", "content": "Planning actions..."}
        yield {"type": "tool_call", "tool": tool_name, "args": tool_args}

        result = await self.tool_executor.execute_tool(tool_name, repo_id, **(tool_args or {}))
        yield {"type": "tool_result", "tool": tool_name, "result": result}

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

        async for event in self._stream_final_response(messages):
            yield event

    async def _fallback_chat_response(
        self,
        messages: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Fall back to a normal chat response when tool calling fails."""
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
        """Build system prompt for agent with context"""
        
        has_repo_files = bool((repository_context or {}).get("total_files"))
        if has_repo_files:
            prompt = """You are an expert AI coding agent. Your job is to:
1. Understand user requests related to code
2. Use tools to gather information about the repository
3. Make decisions about what tools to call
4. Provide helpful, accurate responses

You have access to tools for:
- Searching the repository semantically
- Reading and writing files
- Analyzing code with AST
- Finding references and dependencies
- Executing safe commands

IMPORTANT RULES:
- Never guess about repository structure or file content
- Always use search_repository or read_file tools to get information
- When editing multiple files, show diffs first
- For refactoring, understand the code first, then plan changes
- For bug fixes, analyze the error and context thoroughly

When you need to take action:
1. First understand the codebase (use search or read tools)
2. Plan your approach
3. Execute specific tool calls
4. Report results to the user
"""
        else:
            prompt = """You are an expert AI coding assistant.
Help the user with coding questions, explanations, and writing code.
No repository is indexed right now — answer from general knowledge and any selected file/code the user shares.
Respond clearly. When writing code, prefer complete, ready-to-paste snippets without unnecessary markdown fences unless helpful.
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
            prompt += f"\nSelected code:\n```\n{selected_code[:500]}\n```\n"
        
        return prompt
    
    async def plan_refactoring(
        self,
        code: str,
        goal: str,
        language: str
    ) -> Dict[str, Any]:
        """Plan refactoring without executing"""
        
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
        
        # Use basic chat for planning
        messages = [{"role": "user", "content": prompt}]
        
        # Return planning response
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
        """Analyze error and suggest fixes"""
        
        yield {
            "type": "analysis",
            "content": "Analyzing error..."
        }
        
        # First, understand the context
        prompt = f"""Analyze this {language} error:

Error message:
{error}

Code causing error:
```{language}
{code}
```

First, explain what the error means and why it's happening."""
        
        messages = [{"role": "user", "content": prompt}]
        
        # Stream analysis
        async for response in self.chat_service.stream_chat(messages):
            data = json.loads(response)
            if data.get("type") == "content":
                yield {
                    "type": "analysis",
                    "content": data["content"]
                }
        
        # Then suggest fix
        yield {
            "type": "suggestion",
            "content": "Suggesting fixes..."
        }
        
        prompt2 = f"""Now suggest how to fix this error.
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
