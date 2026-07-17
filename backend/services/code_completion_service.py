import logging
import asyncio
from typing import AsyncIterator, Dict, List, Any, Optional
import os
import json

logger = logging.getLogger(__name__)

class CodeCompletionService:
    """
    Service for AI-powered code completion.
    Provides streaming completions with repository context.
    """
    
    def __init__(self):
        self.model_name = os.getenv("GROQ_MODEL") or os.getenv("LLM_MODEL") or "llama-3.3-70b-versatile"
        self.api_key = os.getenv("GROQ_API_KEY")
        
        if self.api_key:
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key)
                self.initialized = True
                logger.info(f"CodeCompletionService initialized")
            except ImportError:
                logger.warning("Groq client not available")
                self.initialized = False
        else:
            logger.warning("GROQ_API_KEY not set")
            self.initialized = False
    
    async def stream_completion(
        self,
        prompt: str,
        file_path: str = None,
        language: str = "javascript",
        repo_context: Dict[str, Any] = None,
        max_tokens: int = 256,
        temperature: float = 0.5
    ) -> AsyncIterator[str]:
        """
        Stream code completion based on prompt
        
        Args:
            prompt: Current code prompt
            file_path: Current file path
            language: Programming language
            repo_context: Repository context
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        """
        
        if not self.initialized:
            # Mock completion for testing
            yield json.dumps({
                "type": "completion",
                "text": "// Mock completion\nfunction example() {\n  return 'completion';\n}"
            })
            return
        
        try:
            # Build completion prompt
            system_prompt = self._build_completion_system_prompt(
                language, file_path, repo_context
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            # Stream from Groq
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True
            )
            
            completion_text = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    completion_text += text
                    yield json.dumps({
                        "type": "completion",
                        "text": text
                    })
            
            # Analyze completion for improvements
            imports = self._extract_missing_imports(completion_text, language)
            if imports:
                yield json.dumps({
                    "type": "imports",
                    "imports": imports
                })
            
            # Signal end
            yield json.dumps({"type": "end"})
            
        except Exception as e:
            logger.error(f"Completion error: {e}")
            yield json.dumps({
                "type": "error",
                "error": str(e)
            })
    
    def _build_completion_system_prompt(
        self,
        language: str,
        file_path: str = None,
        repo_context: Dict[str, Any] = None
    ) -> str:
        """Build system prompt for code completion"""
        
        prompt = f"You are an expert {language} code completion assistant. "
        prompt += "Provide only the code completion without explanation. "
        prompt += "Generate clean, efficient, and idiomatic code. "
        prompt += "Do not include markdown formatting or code blocks."
        
        if file_path:
            prompt += f"\nCurrent file: {file_path}\n"
        
        if repo_context:
            languages = repo_context.get("languages", [])
            if languages:
                prompt += f"Repository uses: {', '.join(languages)}\n"
        
        return prompt
    
    def _extract_missing_imports(self, code: str, language: str) -> List[str]:
        """Extract potential missing imports from generated code"""
        
        imports = []
        
        if language == "python":
            # Extract Python imports
            if "import " in code or "from " in code:
                lines = code.split('\n')
                for line in lines:
                    if line.strip().startswith(("import ", "from ")):
                        imports.append(line.strip())
        
        elif language in ["javascript", "typescript"]:
            # Extract JavaScript/TypeScript imports
            if "import " in code:
                lines = code.split('\n')
                for line in lines:
                    if line.strip().startswith("import "):
                        imports.append(line.strip())
        
        return imports
    
    async def complete_function(
        self,
        function_signature: str,
        language: str,
        docstring: str = None,
        repo_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Complete function body"""
        
        prompt = f"Complete the {language} function:\n\n"
        if docstring:
            prompt += f'"""{docstring}"""\n'
        prompt += function_signature
        prompt += "\n\nProvide only the function body."
        
        async for completion in self.stream_completion(
            prompt, language=language, repo_context=repo_context
        ):
            yield completion
    
    async def complete_line(
        self,
        file_content: str,
        cursor_position: int,
        language: str,
        repo_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Complete current line"""
        
        # Extract context around cursor
        lines = file_content.split('\n')
        line_num = file_content[:cursor_position].count('\n')
        col = cursor_position - file_content[:cursor_position].rfind('\n') - 1
        
        # Get surrounding context
        start_line = max(0, line_num - 5)
        end_line = min(len(lines), line_num + 2)
        context = '\n'.join(lines[start_line:end_line])
        
        # Mark cursor position
        prompt = context[:context.rfind('\n', 0, cursor_position - file_content[:cursor_position].rfind('\n'))] + "<CURSOR>"
        
        async for completion in self.stream_completion(
            prompt, language=language, repo_context=repo_context
        ):
            yield completion
    
    async def complete_block(
        self,
        block_start: str,
        language: str,
        context: str = None,
        repo_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Complete a code block (if/for/class/function body)"""
        
        prompt = f"Complete the {language} code block:\n\n{block_start}\n\nProvide the complete block."
        
        if context:
            prompt = f"Context:\n{context}\n\n" + prompt
        
        async for completion in self.stream_completion(
            prompt, language=language, repo_context=repo_context
        ):
            yield completion
