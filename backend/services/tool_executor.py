import logging
import asyncio
import json
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
    "propose_edit",
}

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
    
    def __init__(self, repository_manager, ast_service, search_service):
        self.repository_manager = repository_manager
        self.ast_service = ast_service
        self.search_service = search_service
        
        # Register built-in tools
        self.tools: Dict[str, Tool] = {}
        self._register_builtin_tools()
    
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

        # Propose edit (staged; does not write disk)
        self.register_tool(
            "propose_edit",
            "Propose a complete file replacement. Pass the FULL new file content. Does not write until the user applies the diff.",
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
        # #region agent log
        from debug_log import debug_log
        debug_log("B", "tool_executor.py:execute_tool", "executing tool", {
            "tool_name": tool_name,
            "repo_id": repo_id,
            "kwargs": kwargs,
        })
        # #endregion

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

        if tool_name in self.tools:
            allowed = set(self.tools[tool_name].parameters.keys())
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
        return await self.repository_manager.read_file(repo_id, file_path)
    
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
        """Propose a full-file edit without writing to disk."""
        import difflib

        file_path = (file_path or "").replace("\\", "/")
        original = ""
        try:
            original = await self.repository_manager.read_file(repo_id, file_path)
        except FileNotFoundError:
            original = ""
        except Exception:
            # Local / missing repo — treat as new or empty
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
        # unified_diff with lineterm="" still needs newlines between lines for display
        diff_text = "\n".join(line.rstrip("\n") for line in diff_lines)

        return {
            "file_path": file_path,
            "original": original,
            "proposed": proposed,
            "diff": diff_text,
            "rationale": rationale or "",
            "validation": validation,
            "is_new_file": original == "" and proposed != "",
        }
    
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
        """Execute terminal command safely"""
        
        # Security: prevent dangerous commands
        dangerous_patterns = [
            "rm ", "rmdir ", "del ", "format ", "dd ",
            "mkfs ", "fdisk ", "sudo ", "chown ", "chmod "
        ]
        
        for pattern in dangerous_patterns:
            if pattern in command.lower():
                return {
                    "status": "error",
                    "error": f"Command not allowed: {pattern}"
                }
        
        try:
            import subprocess
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.repository_manager.upload_dir / repo_id),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return {
                "status": "success",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": "Command timeout"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
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
                    }
                }
            })
        return schemas

    def get_agent_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for the curated agent tool set"""
        return self.get_tool_schemas(AGENT_TOOL_NAMES)