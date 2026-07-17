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
        self.generic_visit(node)
    
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
        self.functions.append(func)
        self.generic_visit(node)
    
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
        
        # Visit class methods
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
                "line": node.lineno
            })
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            self.imports.append({
                "type": "from_import",
                "module": node.module,
                "name": alias.name,
                "as": alias.asname,
                "line": node.lineno
            })
    
    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.variables.append({
                    "type": "variable",
                    "name": target.id,
                    "line": node.lineno,
                    "value_type": self._extract_expr(node.value)
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
            import tree_sitter_python
            from tree_sitter import Language, Parser
            
            self.has_tree_sitter = True
            self.parser = Parser()
            self.js_language = Language(tree_sitter_javascript.language())
            self.py_language = Language(tree_sitter_python.language())
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
            if language == "typescript":
                self.parser.set_language(self.js_language)  # Tree-sitter JS handles TS
            else:
                self.parser.set_language(self.js_language)
            
            tree = self.parser.parse(content.encode('utf-8'))
            
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
    
    def _extract_js_functions(self, node, content: str, functions: List[Dict] = None) -> List[Dict]:
        """Extract function definitions from JS/TS AST"""
        if functions is None:
            functions = []
        
        if node.type in ["function_declaration", "arrow_function", "method_definition"]:
            name = self._get_node_text(node, content, "name")
            functions.append({
                "type": "function",
                "name": name,
                "line": node.start_point[0] + 1,
                "col": node.start_point[1],
                "end_line": node.end_point[0] + 1
            })
        
        for child in node.children:
            self._extract_js_functions(child, content, functions)
        
        return functions
    
    def _extract_js_classes(self, node, content: str, classes: List[Dict] = None) -> List[Dict]:
        """Extract class definitions from JS/TS AST"""
        if classes is None:
            classes = []
        
        if node.type == "class_declaration":
            name = self._get_node_text(node, content, "name")
            classes.append({
                "type": "class",
                "name": name,
                "line": node.start_point[0] + 1,
                "col": node.start_point[1],
                "end_line": node.end_point[0] + 1
            })
        
        for child in node.children:
            self._extract_js_classes(child, content, classes)
        
        return classes
    
    def _extract_js_imports(self, node, content: str, imports: List[Dict] = None) -> List[Dict]:
        """Extract import statements from JS/TS AST"""
        if imports is None:
            imports = []
        
        if node.type in ["import_statement"]:
            import_text = self._get_node_text(node, content)
            imports.append({
                "type": "import",
                "text": import_text,
                "line": node.start_point[0] + 1
            })
        
        for child in node.children:
            self._extract_js_imports(child, content, imports)
        
        return imports
    
    def _extract_js_exports(self, node, content: str, exports: List[Dict] = None) -> List[Dict]:
        """Extract export statements from JS/TS AST"""
        if exports is None:
            exports = []
        
        if node.type in ["export_statement"]:
            export_text = self._get_node_text(node, content)
            exports.append({
                "type": "export",
                "text": export_text,
                "line": node.start_point[0] + 1
            })
        
        for child in node.children:
            self._extract_js_exports(child, content, exports)
        
        return exports
    
    def _get_node_text(self, node, content: str, child_type: str = None) -> str:
        """Extract text from tree-sitter node"""
        try:
            if child_type:
                for child in node.children:
                    if child.type == child_type:
                        start = child.start_byte
                        end = child.end_byte
                        return content[start:end].strip()
            
            start = node.start_byte
            end = node.end_byte
            return content[start:end].strip()[:100]  # Limit length
        except:
            return "unknown"
    
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