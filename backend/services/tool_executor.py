import logging
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Core tools exposed to the agent (fewer tools = more reliable tool calling)
AGENT_TOOL_NAMES = {
    "search_repository",
    "read_file",
    "list_files",
    "ast_lookup",
    "find_references",
    "create_plan",
    "update_todo",
    "apply_patch",
    "propose_edit",
    "run_terminal",
    "finish",
}

# Allowlisted terminal command prefixes (lowercase match on stripped command)
TERMINAL_ALLOWLIST_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "python -m py_compile",
    "python -m compileall",
    "python -c ",
    "npm test",
    "npm run ",
    "npx ",
    "pnpm test",
    "pnpm run ",
    "yarn test",
    "yarn ",
    "tsc",
    "eslint",
    "ruff ",
    "ruff.",
    "mypy ",
    "cargo test",
    "cargo check",
    "go test",
    "dotnet test",
    "dotnet build",
    "pip show",
    "pip list",
    "node ",
    "ls",
    "dir",
    "type ",
    "cat ",
    "head ",
    "wc ",
    "git status",
    "git diff",
    "git log",
)

@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable

class ToolExecutor:
    """
    Manages tool execution for LLM.
    Allows LLM to call tools without guessing about repository state.
    """
    
    def __init__(self, repository_manager, ast_service, search_service, edit_history=None):
        self.repository_manager = repository_manager
        self.ast_service = ast_service
        self.search_service = search_service
        self.edit_history = edit_history
        # Per-request agent session state (set by AgentPlanner)
        self.session_request_id: Optional[str] = None
        self.session_repo_id: str = ""
        self.session_soft_apply: bool = False
        self.session_plan: Optional[Dict[str, Any]] = None
        self.session_snapshots: List[Dict[str, str]] = []
        # Browser-only files are available to tools for the lifetime of one
        # agent request, but are never persisted by local sessions.
        self.session_virtual_files: Dict[str, str] = {}

        # Register built-in tools
        self.tools: Dict[str, Tool] = {}
        self._register_builtin_tools()

    def begin_session(
        self,
        request_id: str,
        repo_id: str = "",
        soft_apply: bool = False,
        selected_file: Optional[str] = None,
        selected_code: Optional[str] = None,
    ) -> None:
        self.session_request_id = request_id
        self.session_repo_id = repo_id
        self.session_soft_apply = soft_apply
        self.session_plan = None
        self.session_snapshots = []
        self.session_virtual_files = {}
        if selected_file and selected_code is not None:
            self.session_virtual_files[self._normalize_file_path(selected_file)] = selected_code

    def end_session(self) -> Dict[str, Any]:
        saved = False
        if (
            self.edit_history
            and self.session_request_id
            and self.session_snapshots
            and self.session_repo_id
            and self.session_repo_id not in ("local", "none", "__none__", "")
        ):
            self.edit_history.save_snapshot(
                self.session_repo_id,
                self.session_request_id,
                [
                    {
                        "file_path": s["file_path"],
                        "before": s["before"],
                        "after": s["after"],
                    }
                    for s in self.session_snapshots
                ],
            )
            saved = True
        info = {
            "request_id": self.session_request_id,
            "snapshots": list(self.session_snapshots),
            "saved": saved,
        }
        self.session_request_id = None
        self.session_repo_id = ""
        self.session_soft_apply = False
        self.session_plan = None
        self.session_snapshots = []
        self.session_virtual_files = {}
        return info

    @staticmethod
    def _normalize_file_path(file_path: str) -> str:
        """Normalize relative editor and repository paths for session lookups."""
        return (file_path or "").replace("\\", "/").lstrip("./")

    async def _resolve_file_content(self, repo_id: str, file_path: str) -> str:
        """Read the session buffer first, then fall back to the repository."""
        normalized_path = self._normalize_file_path(file_path)
        if normalized_path in self.session_virtual_files:
            return self.session_virtual_files[normalized_path]
        return await self.repository_manager.read_file(repo_id, normalized_path)

    def _update_virtual_file(self, file_path: str, content: str) -> None:
        """Keep dependent local tool calls in sync with a successful edit."""
        normalized_path = self._normalize_file_path(file_path)
        if normalized_path in self.session_virtual_files:
            self.session_virtual_files[normalized_path] = content

    async def _soft_write(
        self, repo_id: str, file_path: str, before: str, after: str
    ) -> bool:
        """Write file during agent session and record snapshot for undo."""
        if not self.session_soft_apply:
            return False
        if repo_id in ("local", "none", "__none__", None, ""):
            return False
        await self.repository_manager.write_file(repo_id, file_path, after)
        # Keep first "before" if same file patched multiple times
        existing = next(
            (s for s in self.session_snapshots if s["file_path"] == file_path),
            None,
        )
        if existing:
            existing["after"] = after
        else:
            self.session_snapshots.append({
                "file_path": file_path,
                "before": before,
                "after": after,
                "repo_id": repo_id,
            })
        return True
    
    def _register_builtin_tools(self):
        """Register all built-in tools"""
        
        # Repository search
        self.register_tool(
            "search_repository",
            "Search repository semantically or by keyword",
            {
                "query": {"type": "string", "description": "Search query"},
                "search_type": {
                    "type": "string",
                    "enum": ["semantic", "keyword", "hybrid"],
                    "default": "semantic"
                },
                "top_k": {"type": "integer", "description": "Number of results", "default": 5}
            },
            self._search_repository
        )
        
        # Semantic search
        self.register_tool(
            "semantic_search",
            "Perform semantic search in repository",
            {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "default": 5}
            },
            self._semantic_search
        )
        
        # Read file
        self.register_tool(
            "read_file",
            "Read file content from repository",
            {
                "file_path": {"type": "string", "description": "Path to file"}
            },
            self._read_file
        )
        
        # Write file (registered but not in AGENT_TOOL_NAMES — apply goes through HTTP)
        self.register_tool(
            "write_file",
            "Write content to file",
            {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "File content"}
            },
            self._write_file
        )

        # Propose edit (staged; may soft-apply during agent sessions)
        self.register_tool(
            "propose_edit",
            "Propose a complete file replacement for NEW or tiny files. Prefer apply_patch for existing files. Pass FULL new file content.",
            {
                "file_path": {"type": "string", "description": "Path to file to edit"},
                "new_content": {"type": "string", "description": "Complete new file content"},
                "rationale": {
                    "type": "string",
                    "description": "Brief reason for the change",
                    "default": "",
                },
            },
            self._propose_edit,
        )

        self.register_tool(
            "apply_patch",
            "Apply an exact search/replace patch to an existing file. REQUIRED param name is file_path (not path). old_string must uniquely match once.",
            {
                "file_path": {
                    "type": "string",
                    "description": "Path to existing file (use key file_path, never path)",
                },
                "old_string": {"type": "string", "description": "Exact text to find (must be unique)"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "rationale": {
                    "type": "string",
                    "description": "Brief reason for the change",
                    "default": "",
                },
            },
            self._apply_patch,
        )

        self.register_tool(
            "create_plan",
            "Create an implementation plan with ordered todos for non-trivial work. Call once early before editing.",
            {
                "goal": {"type": "string", "description": "One-sentence goal"},
                "steps": {
                    "type": "array",
                    "description": "Ordered steps",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                        },
                        "required": ["id", "title"],
                    },
                },
            },
            self._create_plan,
        )

        self.register_tool(
            "update_todo",
            "Update a plan step status as you work.",
            {
                "id": {"type": "string", "description": "Step id from create_plan"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                },
                "note": {
                    "type": "string",
                    "description": "Optional short note",
                    "default": "",
                },
            },
            self._update_todo,
        )

        self.register_tool(
            "run_terminal",
            "Run an allowlisted verify command (pytest, npm test, tsc, eslint, ruff, mypy, cargo test, go test, etc.) in the repo root.",
            {
                "command": {"type": "string", "description": "Full command to run"},
            },
            self._run_terminal,
        )

        self.register_tool(
            "finish",
            "Call when the implementation is done (or cannot proceed). Ends the agent loop.",
            {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what changed or why stopping",
                    "default": "",
                },
            },
            self._finish,
        )

        # List files
        self.register_tool(
            "list_files",
            "List all files in repository",
            {},
            self._list_files
        )
        
        # AST lookup
        self.register_tool(
            "ast_lookup",
            "Look up symbol in AST (functions, classes, etc.)",
            {
                "symbol": {"type": "string", "description": "Symbol name"},
                "file_path": {"type": "string", "description": "File to search in"}
            },
            self._ast_lookup
        )
        
        # Find references
        self.register_tool(
            "find_references",
            "Find all references to a symbol",
            {
                "symbol": {"type": "string", "description": "Symbol name"},
                "file_path": {"type": "string", "description": "File to search in"}
            },
            self._find_references
        )
        
        # Build dependency graph
        self.register_tool(
            "build_dependency_graph",
            "Build dependency graph for repository",
            {},
            self._build_dependency_graph
        )
        
        # Generate embeddings
        self.register_tool(
            "generate_embeddings",
            "Generate embeddings for repository",
            {},
            self._generate_embeddings
        )
        
        # Reindex repository
        self.register_tool(
            "reindex_repository",
            "Reindex repository after changes",
            {},
            self._reindex_repository
        )
        
        # Execute terminal
        self.register_tool(
            "execute_terminal",
            "Execute safe terminal command",
            {
                "command": {"type": "string", "description": "Command to execute"}
            },
            self._execute_terminal
        )
    
    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable
    ):
        """Register a new tool"""
        self.tools[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler
        )
        logger.info(f"Tool registered: {name}")
    
    async def execute_tool(
        self,
        tool_name: str,
        repo_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute a tool with given parameters"""
        if not isinstance(kwargs, dict):
            kwargs = {}

        if tool_name == "read_file" and "path" in kwargs and "file_path" not in kwargs:
            kwargs["file_path"] = kwargs.pop("path")
        if tool_name == "write_file" and "path" in kwargs and "file_path" not in kwargs:
            kwargs["file_path"] = kwargs.pop("path")
        if tool_name == "propose_edit" and "path" in kwargs and "file_path" not in kwargs:
            kwargs["file_path"] = kwargs.pop("path")
        if tool_name == "propose_edit" and "content" in kwargs and "new_content" not in kwargs:
            kwargs["new_content"] = kwargs.pop("content")
        if tool_name == "apply_patch" and "path" in kwargs and "file_path" not in kwargs:
            kwargs["file_path"] = kwargs.pop("path")
        if tool_name == "run_terminal" and "cmd" in kwargs and "command" not in kwargs:
            kwargs["command"] = kwargs.pop("cmd")

        if tool_name in self.tools:
            allowed = set(self.tools[tool_name].parameters.keys())
            # create_plan steps is required; allow empty properties tools
            if allowed:
                kwargs = {key: value for key, value in kwargs.items() if key in allowed}
        
        if tool_name not in self.tools:
            return {
                "status": "error",
                "error": f"Tool not found: {tool_name}"
            }
        
        try:
            tool = self.tools[tool_name]
            result = await tool.handler(repo_id, **kwargs)
            return {
                "status": "success",
                "result": result
            }
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    # Tool implementations
    
    async def _search_repository(
        self,
        repo_id: str,
        query: str,
        search_type: str = "semantic",
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search repository"""
        return await self.search_service.search_repository(
            repo_id, query, search_type, top_k
        )
    
    async def _semantic_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Semantic search"""
        return await self.search_service._semantic_search(repo_id, query, top_k)
    
    async def _read_file(self, repo_id: str, file_path: str) -> str:
        """Read file"""
        return await self._resolve_file_content(repo_id, file_path)
    
    async def _write_file(
        self,
        repo_id: str,
        file_path: str,
        content: str
    ) -> Dict[str, Any]:
        """Write file"""
        return await self.repository_manager.write_file(repo_id, file_path, content)

    def _detect_language(self, file_path: str) -> str:
        lower = file_path.lower()
        if lower.endswith(".py"):
            return "python"
        if lower.endswith((".ts", ".tsx")):
            return "typescript"
        if lower.endswith((".js", ".jsx")):
            return "javascript"
        return "unknown"

    def _validate_proposed_content(
        self,
        file_path: str,
        original: str,
        proposed: str,
    ) -> Dict[str, Any]:
        """Syntax/AST validation for proposed file content."""
        language = self._detect_language(file_path)
        errors: List[str] = []

        if language == "python":
            try:
                compile(proposed, file_path, "exec")
            except SyntaxError as e:
                errors.append(f"Python syntax error: {e.msg} (line {e.lineno})")
            if self.ast_service:
                parsed = self.ast_service.parse_file(proposed, "python")
                if parsed is None and original.strip():
                    # Original may also fail; only fail if proposed is unparsable
                    try:
                        compile(proposed, file_path, "exec")
                    except SyntaxError:
                        pass  # already recorded
                    else:
                        # compile ok but parse_file failed — still ok
                        pass
            return {
                "ok": len(errors) == 0,
                "errors": errors,
                "language": language,
                "skipped": False,
            }

        if language in ("javascript", "typescript"):
            if self.ast_service and self.ast_service.has_tree_sitter:
                parsed = self.ast_service.parse_file(proposed, language)
                # tree-sitter usually returns a tree even for broken code;
                # treat empty/None as failure
                if parsed is None:
                    errors.append(f"{language} parse failed")
                return {
                    "ok": len(errors) == 0,
                    "errors": errors,
                    "language": language,
                    "skipped": False,
                }
            return {
                "ok": True,
                "errors": [],
                "language": language,
                "skipped": True,
            }

        return {
            "ok": True,
            "errors": [],
            "language": language,
            "skipped": True,
        }

    async def _propose_edit(
        self,
        repo_id: str,
        file_path: str,
        new_content: str,
        rationale: str = "",
    ) -> Dict[str, Any]:
        """Propose a full-file edit; soft-apply during agent sessions when enabled."""
        import difflib

        file_path = self._normalize_file_path(file_path)
        original = ""
        try:
            original = await self._resolve_file_content(repo_id, file_path)
        except FileNotFoundError:
            original = ""
        except Exception:
            original = ""

        proposed = new_content if new_content is not None else ""
        validation = self._validate_proposed_content(file_path, original, proposed)

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )
        diff_text = "\n".join(line.rstrip("\n") for line in diff_lines)

        applied = False
        if validation.get("ok", True):
            applied = await self._soft_write(repo_id, file_path, original, proposed)
            self._update_virtual_file(file_path, proposed)

        return {
            "file_path": file_path,
            "original": original,
            "proposed": proposed,
            "diff": diff_text,
            "rationale": rationale or "",
            "validation": validation,
            "is_new_file": original == "" and proposed != "",
            "applied": applied,
        }

    async def _apply_patch(
        self,
        repo_id: str,
        file_path: str,
        old_string: str,
        new_string: str,
        rationale: str = "",
    ) -> Dict[str, Any]:
        """Apply unique search/replace and optionally soft-write."""
        import difflib

        file_path = self._normalize_file_path(file_path)
        try:
            original = await self._resolve_file_content(repo_id, file_path)
        except Exception as e:
            return {
                "file_path": file_path,
                "error": f"Cannot read file: {e}",
                "validation": {"ok": False, "errors": [str(e)]},
                "applied": False,
            }

        if not old_string:
            return {
                "file_path": file_path,
                "error": "old_string is empty",
                "validation": {"ok": False, "errors": ["old_string is empty"]},
                "applied": False,
            }

        count = original.count(old_string)
        if count == 0:
            return {
                "file_path": file_path,
                "error": "old_string not found in file",
                "validation": {"ok": False, "errors": ["old_string not found"]},
                "applied": False,
                "original": original,
            }
        if count > 1:
            return {
                "file_path": file_path,
                "error": f"old_string matched {count} times; must be unique",
                "validation": {
                    "ok": False,
                    "errors": [f"old_string matched {count} times"],
                },
                "applied": False,
            }

        proposed = original.replace(old_string, new_string if new_string is not None else "", 1)
        validation = self._validate_proposed_content(file_path, original, proposed)
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                lineterm="",
            )
        )
        diff_text = "\n".join(line.rstrip("\n") for line in diff_lines)

        applied = False
        if validation.get("ok", True):
            applied = await self._soft_write(repo_id, file_path, original, proposed)
            self._update_virtual_file(file_path, proposed)

        return {
            "file_path": file_path,
            "original": original,
            "proposed": proposed,
            "diff": diff_text,
            "rationale": rationale or "",
            "validation": validation,
            "is_new_file": False,
            "applied": applied,
        }

    async def _create_plan(
        self, repo_id: str, goal: str, steps: Any = None
    ) -> Dict[str, Any]:
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                steps = []
        if not isinstance(steps, list):
            steps = []
        todos = []
        for i, step in enumerate(steps):
            if isinstance(step, str):
                todos.append({
                    "id": f"step-{i + 1}",
                    "title": step,
                    "status": "pending",
                    "note": "",
                })
            elif isinstance(step, dict):
                todos.append({
                    "id": str(step.get("id") or f"step-{i + 1}"),
                    "title": str(step.get("title") or step.get("name") or f"Step {i + 1}"),
                    "status": "pending",
                    "note": "",
                })
        plan = {"goal": goal or "", "todos": todos}
        self.session_plan = plan
        return plan

    async def _update_todo(
        self,
        repo_id: str,
        id: str,
        status: str,
        note: str = "",
    ) -> Dict[str, Any]:
        if not self.session_plan:
            self.session_plan = {"goal": "", "todos": []}
        todos = self.session_plan.get("todos") or []
        found = False
        for todo in todos:
            if todo.get("id") == id:
                todo["status"] = status
                if note:
                    todo["note"] = note
                found = True
                break
        if not found:
            todos.append({
                "id": id,
                "title": id,
                "status": status,
                "note": note or "",
            })
            self.session_plan["todos"] = todos
        return {
            "id": id,
            "status": status,
            "note": note or "",
            "plan": self.session_plan,
        }

    async def _run_terminal(self, repo_id: str, command: str) -> Dict[str, Any]:
        return await self._execute_terminal(repo_id, command)

    async def _finish(self, repo_id: str, summary: str = "") -> Dict[str, Any]:
        return {"done": True, "summary": summary or ""}

    async def _list_files(self, repo_id: str) -> List[Dict[str, Any]]:
        """List files"""
        return await self.repository_manager.list_files(repo_id)
    
    async def _ast_lookup(
        self,
        repo_id: str,
        symbol: str,
        file_path: str
    ) -> Optional[Dict[str, Any]]:
        """Look up symbol in AST"""
        content = await self.repository_manager.read_file(repo_id, file_path)
        language = "python" if file_path.endswith(".py") else "javascript"
        ast_data = self.ast_service.parse_file(content, language)
        
        if ast_data:
            return self.ast_service.find_symbol(ast_data, symbol)
        return None
    
    async def _find_references(
        self,
        repo_id: str,
        symbol: str,
        file_path: str
    ) -> List[Dict[str, Any]]:
        """Find references"""
        content = await self.repository_manager.read_file(repo_id, file_path)
        language = "python" if file_path.endswith(".py") else "javascript"
        ast_data = self.ast_service.parse_file(content, language)
        
        if ast_data:
            return self.ast_service.find_references(ast_data, symbol)
        return []
    
    async def _build_dependency_graph(self, repo_id: str) -> Dict[str, Any]:
        """Build dependency graph"""
        # This is already done during indexing
        return {"status": "already_indexed"}
    
    async def _generate_embeddings(self, repo_id: str) -> Dict[str, Any]:
        """Generate embeddings"""
        return {"status": "already_generated_during_indexing"}
    
    async def _reindex_repository(self, repo_id: str) -> Dict[str, Any]:
        """Reindex repository"""
        asyncio.create_task(self.repository_manager.index_repository(repo_id))
        return {"status": "reindexing_started"}
    
    async def _execute_terminal(self, repo_id: str, command: str) -> Dict[str, Any]:
        """Execute allowlisted terminal command in the repo directory."""
        import subprocess

        cmd = (command or "").strip()
        if not cmd:
            return {"status": "error", "error": "Empty command", "returncode": 1}

        dangerous_patterns = [
            "rm -rf", "rmdir ", "del /", "format ", "dd ",
            "mkfs ", "fdisk ", "sudo ", "chown ", "chmod ",
            ">|", "curl ", "wget ", "Invoke-WebRequest",
        ]
        lower = cmd.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in lower:
                return {
                    "status": "error",
                    "error": f"Command not allowed: {pattern}",
                    "returncode": 1,
                }

        allowed = any(
            lower == p.rstrip() or lower.startswith(p)
            for p in TERMINAL_ALLOWLIST_PREFIXES
        )
        if not allowed:
            return {
                "status": "error",
                "error": (
                    "Command not on allowlist. Use pytest, npm test/run, tsc, "
                    "eslint, ruff, mypy, cargo test, go test, etc."
                ),
                "returncode": 1,
            }

        if repo_id in ("local", "none", "__none__", None, ""):
            cwd = str(Path.cwd())
        else:
            cwd = str(self.repository_manager.upload_dir / repo_id)

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            stdout = (result.stdout or "")[:8000]
            stderr = (result.stderr or "")[:4000]
            return {
                "status": "success" if result.returncode == 0 else "failed",
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
                "command": cmd,
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": "Command timeout (60s)",
                "returncode": 1,
                "command": cmd,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "returncode": 1,
                "command": cmd,
            }
    
    def get_tool_schemas(self, tool_names: set[str] | None = None) -> List[Dict[str, Any]]:
        """Get schemas for tools (for LLM function calling)"""
        schemas = []
        for tool_name, tool in self.tools.items():
            if tool_names is not None and tool_name not in tool_names:
                continue

            properties = {}
            required = []
            for key, spec in tool.parameters.items():
                properties[key] = {k: v for k, v in spec.items() if k != "default"}
                if "default" not in spec:
                    required.append(key)

            schemas.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    }
                }
            })
        return schemas

    def get_agent_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for the curated agent tool set"""
        return self.get_tool_schemas(AGENT_TOOL_NAMES)
