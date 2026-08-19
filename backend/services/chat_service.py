import logging
from typing import AsyncIterator, Dict, List, Any, Optional
import json

from services.llm_config import (
    DEFAULT_API_KEY,
    DEFAULT_MODEL,
    SELECTED_CODE_CHAR_CAP,
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

class ChatService:
    """
    Service for managing chat interactions with LLM.
    Supports streaming responses and maintains conversation history.
    """
    
    def __init__(self):
        self.model_name = DEFAULT_MODEL
        self.api_key = DEFAULT_API_KEY
        self.client, _, self.initialized = get_groq_client()
        if self.initialized:
            logger.info(f"ChatService initialized with model: {self.model_name}")
        else:
            logger.warning("GROQ_API_KEY not set or Groq unavailable, using mock responses")
    
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        user_system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream chat response from LLM
        
        Args:
            messages: List of message dicts with "role" and "content"
            system_prompt: System prompt for the model
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
        """
        
        client, model_name, initialized = get_groq_client(
            user_key=api_key,
            user_model=model,
            fallback_client=self.client,
            fallback_key=self.api_key,
        )
        if not initialized:
            yield json.dumps({
                "type": "content",
                "content": "Mock LLM response. Configure GROQ_API_KEY to enable real responses."
            })
            return
        
        try:
            combined_prompt = merge_system_prompt(system_prompt or "", user_system_prompt)
            if combined_prompt.strip():
                messages = [
                    {"role": "system", "content": combined_prompt},
                    *messages
                ]

            messages = trim_messages_to_budget(messages, reserve_completion=max_tokens)
            max_out = fit_max_tokens(messages, max_tokens, model=model_name)
            try:
                stream = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=max_out,
                    temperature=temperature,
                    stream=True,
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
                    )
                elif is_payload_too_large_error(api_error):
                    messages = trim_messages_to_budget(messages, reserve_completion=512)
                    stream = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        max_tokens=fit_max_tokens(messages, 512, model=model_name),
                        temperature=temperature,
                        stream=True,
                    )
                else:
                    raise

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield json.dumps({
                        "type": "content",
                        "content": chunk.choices[0].delta.content
                    })

            # Signal end of stream
            yield json.dumps({"type": "end"})

        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield json.dumps({
                "type": "error",
                "error": friendly_llm_error(e, model_name if "model_name" in locals() else None),
            })
    
    async def chat_with_context(
        self,
        query: str,
        repository_context: Dict[str, Any],
        conversation_history: List[Dict[str, str]] = None,
        selected_file: str = None,
        selected_code: str = None
    ) -> AsyncIterator[str]:
        """
        Chat with full repository context
        
        Args:
            query: User message
            repository_context: Repository information (files, AST, etc.)
            conversation_history: Previous messages
            selected_file: Currently open file
            selected_code: Selected code snippet
        """
        
        # Build system prompt with context
        system_prompt = self._build_system_prompt(
            repository_context,
            selected_file,
            selected_code,
        )
        
        # Build message list
        messages = conversation_history or []
        messages.append({"role": "user", "content": query})
        
        # Stream response
        async for response in self.stream_chat(messages, system_prompt):
            yield response
    
    def _build_system_prompt(
        self,
        repository_context: Dict[str, Any],
        selected_file: str = None,
        selected_code: str = None
    ) -> str:
        """Build comprehensive system prompt with repository context"""
        
        prompt = """You are an expert AI coding assistant. You have deep knowledge of the repository and can help with:
- Explaining code
- Refactoring code
- Generating new code
- Fixing bugs
- Optimizing performance
- Writing tests
- Reviewing security
- Documenting code

Use the repository context provided to give accurate, contextual responses.
"""
        
        # Add repository overview
        if repository_context:
            files = repository_context.get("files", [])
            languages = repository_context.get("languages", [])
            
            prompt += f"\n\nRepository Overview:\n"
            prompt += f"- Total files: {repository_context.get('total_files', 0)}\n"
            prompt += f"- Languages: {', '.join(languages)}\n"
            
            # Add file structure
            if files and len(files) <= 20:  # Only include if not too many files
                prompt += f"\nKey files:\n"
                for f in files[:10]:
                    prompt += f"- {f['path']} ({f['language']})\n"
        
        # Add selected file context
        if selected_file:
            prompt += f"\n\nCurrently viewing file: {selected_file}\n"
        
        # Add selected code
        if selected_code:
            clipped = truncate_text(selected_code, SELECTED_CODE_CHAR_CAP)
            prompt += f"\nSelected code:\n```\n{clipped}\n```\n"
        
        return prompt
    
    async def explain_code(
        self,
        code: str,
        language: str,
        repository_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Explain what code does"""
        
        prompt = f"Explain this {language} code:\n\n```{language}\n{code}\n```\n\nBe concise and explain what it does, key concepts, and any important details."
        
        messages = [{"role": "user", "content": prompt}]
        
        async for response in self.stream_chat(messages):
            yield response
    
    async def generate_refactoring(
        self,
        code: str,
        language: str,
        instruction: str = None,
        repository_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Generate refactored code"""
        
        prompt = f"Refactor this {language} code"
        if instruction:
            prompt += f" to {instruction}"
        prompt += f":\n\n```{language}\n{code}\n```\n\nProvide only the refactored code without explanation."
        
        messages = [{"role": "user", "content": prompt}]
        
        async for response in self.stream_chat(messages):
            yield response
    
    async def generate_code(
        self,
        description: str,
        language: str,
        repository_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Generate code based on description"""
        
        prompt = f"Generate {language} code for: {description}\n\nProvide clean, well-structured code. Only provide the code block without explanation."
        
        messages = [{"role": "user", "content": prompt}]
        
        async for response in self.stream_chat(messages):
            yield response
    
    async def fix_errors(
        self,
        code: str,
        language: str,
        error_message: str,
        repository_context: Dict[str, Any] = None
    ) -> AsyncIterator[str]:
        """Fix code errors"""
        
        prompt = f"""Fix the following {language} code error:

Code:
```{language}
{code}
```

Error:
{error_message}

Provide the corrected code and explain the fix."""
        
        messages = [{"role": "user", "content": prompt}]
        
        async for response in self.stream_chat(messages):
            yield response
