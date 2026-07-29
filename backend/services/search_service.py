import logging
from typing import List, Dict, Any, Optional
import re

logger = logging.getLogger(__name__)

class SearchService:
    """
    Service for searching repository with semantic and keyword search.
    Combines embedding-based semantic search with keyword matching.
    """
    
    def __init__(self, embedding_service):
        self.embedding_service = embedding_service
    
    async def search_repository(
        self,
        repo_id: str,
        query: str,
        search_type: str = "semantic",
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search repository using semantic or keyword search
        
        Args:
            repo_id: Repository ID
            query: Search query
            search_type: "semantic", "keyword", or "hybrid"
            top_k: Number of results to return
        """
        
        if search_type == "semantic":
            return await self._semantic_search(repo_id, query, top_k)
        elif search_type == "keyword":
            return await self._keyword_search(repo_id, query, top_k)
        elif search_type == "hybrid":
            return await self._hybrid_search(repo_id, query, top_k)
        else:
            raise ValueError(f"Unknown search type: {search_type}")
    
    async def _semantic_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Semantic search using AST-symbol embeddings (with neighbor context)."""
        try:
            results = await self.embedding_service.semantic_search(
                repo_id, query, top_k
            )
            return results
        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []
    
    async def _keyword_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Simple keyword search"""
        # TODO: Implement actual keyword search against database
        logger.warning("Keyword search not yet implemented")
        return []
    
    async def _hybrid_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining semantic and keyword"""
        # Semantic results
        semantic_results = await self._semantic_search(repo_id, query, top_k)
        
        # Keyword results (when implemented)
        keyword_results = []
        
        # Merge and deduplicate
        seen_files = set()
        merged_results = []
        
        for result in semantic_results:
            file_path = result.get("file_path")
            if file_path not in seen_files:
                merged_results.append(result)
                seen_files.add(file_path)
        
        return merged_results[:top_k]
    
    async def search_symbols(
        self,
        repo_id: str,
        query: str,
        symbol_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        Search for specific symbols (functions, classes, variables)
        
        Args:
            repo_id: Repository ID
            query: Symbol name or pattern
            symbol_type: "function", "class", "variable", or None for all
        """
        # TODO: Implement symbol search against database
        # This would search AST data for matching symbols
        logger.warning("Symbol search not yet implemented")
        return []
    
    async def find_in_files(
        self,
        repo_id: str,
        pattern: str,
        file_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find pattern in files (like grep)
        
        Args:
            repo_id: Repository ID
            pattern: Regex pattern to search
            file_types: List of file extensions to search (e.g., [".py", ".js"])
        """
        # TODO: Implement file content search
        logger.warning("File pattern search not yet implemented")
        return []
    
    def _extract_context(self, content: str, keyword: str, window: int = 2) -> str:
        """Extract context around keyword"""
        lines = content.split('\n')
        context_lines = []
        
        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                start = max(0, i - window)
                end = min(len(lines), i + window + 1)
                context_lines.extend(lines[start:end])
        
        return '\n'.join(context_lines) if context_lines else ""