import ast
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class ASTNode:
    type: str
    name: str
    line: int
    col: int
    end_line: int
    children: List['ASTNode'] = None
    attributes: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.attributes is None:
            self.attributes = {}

class PythonASTExtractor(ast.NodeVisitor):
    """Extract structured information from Python AST"""
    
    def __init__(self):
        self.functions = []
        self.classes = []
        self.imports = []
        self.exports = []
        self.variables = []
        self.scopes = []
        self.current_class = None
        self._function_depth = 0
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        func = {
            "type": "function",
            "name": node.name,
            "line": node.lineno,
            "col": node.col_offset,
            "end_line": node.end_lineno,
            "args": [arg.arg for arg in node.args.args],
            "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
            "returns": self._extract_annotation(node.returns),
            "docstring": ast.get_docstring(node)
        }
        
        if self.current_class:
            func["parent_class"] = self.current_class
        
        self.functions.append(func)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        func = {
            "type": "async_function",
            "name": node.name,
            "line": node.lineno,
            "col": node.col_offset,
            "end_line": node.end_lineno,
            "args": [arg.arg for arg in node.args.args],
            "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
            "returns": self._extract_annotation(node.returns),
            "docstring": ast.get_docstring(node)
        }
        if self.current_class:
            func["parent_class"] = self.current_class
        self.functions.append(func)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1
    
    def visit_ClassDef(self, node: ast.ClassDef):
        class_info = {
            "type": "class",
            "name": node.name,
            "line": node.lineno,
            "col": node.col_offset,
            "end_line": node.end_lineno,
            "bases": [self._extract_expr(base) for base in node.bases],
            "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
            "docstring": ast.get_docstring(node),
            "methods": []
        }
        
        self.classes.append(class_info)
        
        prev_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev_class
    
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append({
                "type": "import",
                "module": alias.name,
                "as": alias.asname,
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            })
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            self.imports.append({
                "type": "from_import",
                "module": node.module,
                "name": alias.name,
                "as": alias.asname,
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            })
    
    def visit_Assign(self, node: ast.Assign):
        # Only module-level assignments (not inside functions or class bodies)
        if self._function_depth > 0 or self.current_class:
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.variables.append({
                    "type": "variable",
                    "name": target.id,
                    "line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "value_type": self._extract_expr(node.value)
                })
    
    def visit_AnnAssign(self, node: ast.AnnAssign):
        if self._function_depth > 0 or self.current_class:
            return
        if isinstance(node.target, ast.Name):
            self.variables.append({
                "type": "variable",
                "name": node.target.id,
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "value_type": self._extract_expr(node.value) if node.value else None,
            })
    
    def _extract_annotation(self, annotation) -> str:
        if annotation is None:
            return None
        if isinstance(annotation, ast.Name):
            return annotation.id
        if isinstance(annotation, ast.Constant):
            return str(annotation.value)
        return str(ast.unparse(annotation))
    
    def _extract_expr(self, expr) -> str:
        if expr is None:
            return None
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Constant):
            return str(expr.value)
        try:
            return ast.unparse(expr)
        except:
            return "unknown"

class ASTService:
    """
    Service for parsing code and extracting AST information.
    Supports Python and JavaScript/TypeScript (via tree-sitter).
    """
    
    def __init__(self):
        try:
            import tree_sitter_javascript
            from tree_sitter import Language, Parser
            
            self.has_tree_sitter = True
            self.js_language = Language(tree_sitter_javascript.language())
            self.js_parser = Parser(self.js_language)
        except ImportError:
            self.has_tree_sitter = False
            logger.warning("tree-sitter not available, falling back to ast module for Python only")
    
    def parse_file(self, content: str, language: str) -> Optional[Dict[str, Any]]:
        """
        Parse file content and return structured AST data
        """
        try:
            if language == "python":
                return self._parse_python(content)
            elif language in ["javascript", "typescript"]:
                if self.has_tree_sitter:
                    return self._parse_javascript(content, language)
                else:
                    logger.warning(f"tree-sitter not available for {language}")
                    return None
            else:
                return None
        except Exception as e:
            logger.error(f"Error parsing {language} file: {e}")
            return None
    
    def _parse_python(self, content: str) -> Dict[str, Any]:
        """Parse Python code using ast module"""
        try:
            tree = ast.parse(content)
            extractor = PythonASTExtractor()
            extractor.visit(tree)
            
            return {
                "language": "python",
                "functions": extractor.functions,
                "classes": extractor.classes,
                "imports": extractor.imports,
                "variables": extractor.variables,
                "exports": extractor.exports
            }
        except SyntaxError as e:
            logger.error(f"Python syntax error: {e}")
            return None
    
    def _parse_javascript(self, content: str, language: str) -> Dict[str, Any]:
        """Parse JavaScript/TypeScript using tree-sitter"""
        try:
            tree = self.js_parser.parse(content.encode('utf-8'))
            
            functions = self._extract_js_functions(tree.root_node, content)
            classes = self._extract_js_classes(tree.root_node, content)
            imports = self._extract_js_imports(tree.root_node, content)
            exports = self._extract_js_exports(tree.root_node, content)
            
            return {
                "language": language,
                "functions": functions,
                "classes": classes,
                "imports": imports,
                "exports": exports
            }
        except Exception as e:
            logger.error(f"JavaScript parsing error: {e}")
            return None
    
    def _extract_js_functions(
        self,
        node,
        content: str,
        functions: List[Dict] = None,
        parent_class: str = None,
    ) -> List[Dict]:
        """Extract function definitions from JS/TS AST"""
        if functions is None:
            functions = []

        current_class = parent_class
        if node.type == "class_declaration":
            current_class = self._get_js_identifier(node, content) or parent_class

        if node.type in ("function_declaration", "generator_function_declaration"):
            name = self._get_js_identifier(node, content) or "anonymous"
            functions.append({
                "type": "method" if current_class else "function",
                "name": name,
                "line": node.start_point[0] + 1,
                "col": node.start_point[1],
                "end_line": node.end_point[0] + 1,
                "parent_class": current_class,
            })
        elif node.type == "method_definition":
            name = self._get_js_identifier(node, content) or "anonymous"
            functions.append({
                "type": "method",
                "name": name,
                "line": node.start_point[0] + 1,
                "col": node.start_point[1],
                "end_line": node.end_point[0] + 1,
                "parent_class": current_class,
            })
        elif node.type == "lexical_declaration":
            # const foo = () => {} / const foo = function() {}
            for child in node.children:
                if child.type == "variable_declarator":
                    init = None
                    name = None
                    for part in child.children:
                        if part.type == "identifier" and name is None:
                            name = content[part.start_byte:part.end_byte]
                        if part.type in (
                            "arrow_function",
                            "function",
                            "function_expression",
                            "generator_function",
                        ):
                            init = part
                    if name and init is not None:
                        functions.append({
                            "type": "function",
                            "name": name,
                            "line": node.start_point[0] + 1,
                            "col": node.start_point[1],
                            "end_line": node.end_point[0] + 1,
                            "parent_class": current_class,
                        })

        for child in node.children:
            self._extract_js_functions(child, content, functions, current_class)

        return functions

    def _extract_js_classes(self, node, content: str, classes: List[Dict] = None) -> List[Dict]:
        """Extract class definitions from JS/TS AST"""
        if classes is None:
            classes = []

        if node.type == "class_declaration":
            name = self._get_js_identifier(node, content) or "anonymous"
            classes.append({
                "type": "class",
                "name": name,
                "line": node.start_point[0] + 1,
                "col": node.start_point[1],
                "end_line": node.end_point[0] + 1,
            })

        for child in node.children:
            self._extract_js_classes(child, content, classes)

        return classes

    def _extract_js_imports(self, node, content: str, imports: List[Dict] = None) -> List[Dict]:
        """Extract import statements from JS/TS AST"""
        if imports is None:
            imports = []

        if node.type == "import_statement":
            import_text = self._get_node_text(node, content)
            imports.append({
                "type": "import",
                "text": import_text,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
            })

        for child in node.children:
            self._extract_js_imports(child, content, imports)

        return imports

    def _extract_js_exports(self, node, content: str, exports: List[Dict] = None) -> List[Dict]:
        """Extract export statements from JS/TS AST"""
        if exports is None:
            exports = []

        if node.type == "export_statement":
            export_text = self._get_node_text(node, content)
            exports.append({
                "type": "export",
                "text": export_text,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
            })

        for child in node.children:
            self._extract_js_exports(child, content, exports)

        return exports

    def _get_js_identifier(self, node, content: str) -> Optional[str]:
        """Get the identifier name for a JS declaration/method node."""
        # Prefer named child "name" when available
        try:
            name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
            if name_node is not None:
                return content[name_node.start_byte:name_node.end_byte].strip()
        except Exception:
            pass

        for child in node.children:
            if child.type in ("identifier", "property_identifier", "private_property_identifier"):
                return content[child.start_byte:child.end_byte].strip()
            if child.type == "variable_declarator":
                for part in child.children:
                    if part.type == "identifier":
                        return content[part.start_byte:part.end_byte].strip()
        return None

    def _get_node_text(self, node, content: str, child_type: str = None) -> str:
        """Extract text from tree-sitter node"""
        try:
            if child_type:
                for child in node.children:
                    if child.type == child_type or (
                        child_type == "name"
                        and child.type in ("identifier", "property_identifier")
                    ):
                        start = child.start_byte
                        end = child.end_byte
                        return content[start:end].strip()

            start = node.start_byte
            end = node.end_byte
            return content[start:end].strip()[:100]
        except Exception:
            return "unknown"

    def iter_symbols(self, ast_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize AST data into a flat list of symbols with spans for chunking.
        Each item: name, type, line, end_line, parent_class (optional).
        """
        if not ast_data:
            return []

        symbols: List[Dict[str, Any]] = []

        for func in ast_data.get("functions", []):
            parent = func.get("parent_class")
            sym_type = func.get("type") or "function"
            if parent and sym_type == "function":
                sym_type = "method"
            symbols.append({
                "name": func.get("name") or "anonymous",
                "type": sym_type,
                "line": func.get("line") or 1,
                "end_line": func.get("end_line") or func.get("line") or 1,
                "parent_class": parent or "",
            })

        for cls in ast_data.get("classes", []):
            symbols.append({
                "name": cls.get("name") or "anonymous",
                "type": "class",
                "line": cls.get("line") or 1,
                "end_line": cls.get("end_line") or cls.get("line") or 1,
                "parent_class": "",
            })

        for var in ast_data.get("variables", []):
            symbols.append({
                "name": var.get("name") or "anonymous",
                "type": "variable",
                "line": var.get("line") or 1,
                "end_line": var.get("end_line") or var.get("line") or 1,
                "parent_class": "",
            })

        imports = ast_data.get("imports") or []
        exports = ast_data.get("exports") or []
        if imports or exports:
            lines = []
            for item in imports + exports:
                if item.get("line"):
                    lines.append(item["line"])
                if item.get("end_line"):
                    lines.append(item["end_line"])
            if lines:
                symbols.append({
                    "name": "__module_header__",
                    "type": "module_header",
                    "line": min(lines),
                    "end_line": max(lines),
                    "parent_class": "",
                })

        # Sort by start line for stable chunk ordering
        symbols.sort(key=lambda s: (s.get("line") or 0, s.get("end_line") or 0))
        return symbols
    
    def find_symbol(self, ast_data: Dict[str, Any], symbol_name: str) -> Optional[Dict[str, Any]]:
        """Find a symbol (function, class, variable) in AST"""
        # Search functions
        for func in ast_data.get("functions", []):
            if func["name"] == symbol_name:
                return func
        
        # Search classes
        for cls in ast_data.get("classes", []):
            if cls["name"] == symbol_name:
                return cls
        
        # Search variables
        for var in ast_data.get("variables", []):
            if var["name"] == symbol_name:
                return var
        
        return None
    
    def find_references(self, ast_data: Dict[str, Any], symbol_name: str) -> List[Dict[str, Any]]:
        """Find all references to a symbol (simplified)"""
        references = []
        
        # Find in function args and bodies
        for func in ast_data.get("functions", []):
            if symbol_name in str(func):
                references.append({
                    "type": "function_reference",
                    "function": func["name"],
                    "line": func["line"]
                })
        
        return references