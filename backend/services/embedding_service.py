import logging
from typing import List, Dict, Any, Optional
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Service for generating embeddings and storing them in ChromaDB.
    Uses sentence-transformers for embedding generation.
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
            import chromadb

            self.model = SentenceTransformer(model_name)

            # Create persistent Chroma database
            chroma_path = Path("./chroma_db")
            chroma_path.mkdir(parents=True, exist_ok=True)

            # New ChromaDB 0.5+ API
            self.client = chromadb.PersistentClient(
                path=str(chroma_path)
            )

            self.collections = {}

            logger.info(f"EmbeddingService initialized with model: {model_name}")

        except ImportError as e:
            logger.error(f"Failed to initialize EmbeddingService: {e}")
            raise
        
    async def embed_text(self, text: str) -> List[float]:
        """Generate embedding for text"""
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self.model.encode(text).tolist()
        )
        return embedding
    
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self.model.encode(texts).tolist()
        )
        return embeddings
    
    def get_or_create_collection(self, repo_id: str) -> Any:
        """Get or create ChromaDB collection for repository"""
        if repo_id not in self.collections:
            self.collections[repo_id] = self.client.get_or_create_collection(
                name=f"repo_{repo_id}",
                metadata={"repo_id": repo_id}
            )
        return self.collections[repo_id]
    
    async def store_file_embeddings(
        self,
        repo_id: str,
        file_path: str,
        chunks: List[str]
    ) -> None:
        """
        Store embeddings for file chunks in ChromaDB
        """
        try:
            collection = self.get_or_create_collection(repo_id)
            
            # Generate embeddings
            embeddings = await self.embed_texts(chunks)
            
            # Prepare documents for ChromaDB
            ids = [f"{file_path}_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    "repo_id": repo_id,
                    "file_path": file_path,
                    "chunk_index": i
                }
                for i in range(len(chunks))
            ]
            
            # Store in ChromaDB
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas
            )
            
            logger.info(f"Stored {len(chunks)} embeddings for {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to store embeddings: {e}")
            raise
    
    async def semantic_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search in repository
        """
        try:
            collection = self.get_or_create_collection(repo_id)
            
            # Generate query embedding
            query_embedding = await self.embed_text(query)
            
            # Search in ChromaDB
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            # Format results
            formatted_results = []
            if results["documents"] and len(results["documents"]) > 0:
                for i, (doc, metadata, distance) in enumerate(
                    zip(
                        results["documents"][0],
                        results["metadatas"][0],
                        results["distances"][0]
                    )
                ):
                    formatted_results.append({
                        "file_path": metadata.get("file_path"),
                        "chunk_index": metadata.get("chunk_index"),
                        "content": doc,
                        "similarity": 1 - distance  # Convert distance to similarity
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
    
    async def batch_semantic_search(
        self,
        repo_id: str,
        queries: List[str],
        top_k: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Perform semantic search for multiple queries
        """
        results = {}
        for query in queries:
            results[query] = await self.semantic_search(repo_id, query, top_k)
        return results
    
    def delete_collection(self, repo_id: str) -> None:
        """Delete collection for repository"""
        try:
            if repo_id in self.collections:
                self.client.delete_collection(f"repo_{repo_id}")
                del self.collections[repo_id]
                logger.info(f"Deleted collection for {repo_id}")
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
    
    async def close(self) -> None:
        """Close ChromaDB connection"""
        try:
            # ChromaDB connections are typically managed internally
            pass
        except Exception as e:
            logger.error(f"Failed to close EmbeddingService: {e}")