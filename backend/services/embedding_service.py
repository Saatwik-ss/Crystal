import logging
from typing import List, Dict, Any, Optional
import asyncio
import re
from pathlib import Path

from .chunking_service import truncate_to_tokens, CONTEXT_TOKEN_CAP

logger = logging.getLogger(__name__)


def _sanitize_id_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._\-]+", "_", value)[:120] or "x"


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

            chroma_path = Path("./chroma_db")
            chroma_path.mkdir(parents=True, exist_ok=True)

            self.client = chromadb.PersistentClient(path=str(chroma_path))
            self.collections = {}

            logger.info(f"EmbeddingService initialized with model: {model_name}")

        except ImportError as e:
            logger.error(f"Failed to initialize EmbeddingService: {e}")
            raise

    async def embed_text(self, text: str) -> List[float]:
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self.model.encode(text).tolist()
        )
        return embedding

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self.model.encode(texts).tolist()
        )
        return embeddings

    def get_or_create_collection(self, repo_id: str) -> Any:
        if repo_id not in self.collections:
            self.collections[repo_id] = self.client.get_or_create_collection(
                name=f"repo_{repo_id}",
                metadata={"repo_id": repo_id}
            )
        return self.collections[repo_id]

    def reset_collection(self, repo_id: str) -> None:
        """Delete and recreate collection so reindex does not duplicate chunks."""
        name = f"repo_{repo_id}"
        try:
            if repo_id in self.collections:
                del self.collections[repo_id]
            try:
                self.client.delete_collection(name)
            except Exception:
                pass
            self.collections[repo_id] = self.client.get_or_create_collection(
                name=name,
                metadata={"repo_id": repo_id},
            )
            logger.info(f"Reset Chroma collection for {repo_id}")
        except Exception as e:
            logger.error(f"Failed to reset collection for {repo_id}: {e}")
            raise

    async def store_file_embeddings(
        self,
        repo_id: str,
        file_path: str,
        chunks: List[str]
    ) -> None:
        """Legacy string-chunk storage (kept for compatibility)."""
        structured = [
            {
                "content": chunk,
                "file_path": file_path,
                "symbol_name": f"chunk_{i}",
                "symbol_type": "file_chunk",
                "parent_symbol": "",
                "language": "unknown",
                "start_line": i + 1,
                "end_line": i + 1,
                "chunk_index": i,
                "sub_chunk_index": 0,
                "sub_chunk_count": 1,
            }
            for i, chunk in enumerate(chunks)
        ]
        await self.store_symbol_embeddings(repo_id, structured)

    async def store_symbol_embeddings(
        self,
        repo_id: str,
        chunks: List[Dict[str, Any]],
    ) -> None:
        """Store AST/symbol chunks with rich flat metadata in ChromaDB."""
        if not chunks:
            return

        try:
            collection = self.get_or_create_collection(repo_id)
            documents = [c["content"] for c in chunks]
            embeddings = await self.embed_texts(documents)

            ids = []
            metadatas = []
            for c in chunks:
                file_path = c.get("file_path") or "unknown"
                symbol_name = c.get("symbol_name") or "anonymous"
                start_line = int(c.get("start_line") or 1)
                sub_idx = int(c.get("sub_chunk_index") or 0)
                chunk_id = (
                    f"{_sanitize_id_part(file_path)}::"
                    f"{_sanitize_id_part(symbol_name)}::"
                    f"{start_line}::{sub_idx}"
                )
                ids.append(chunk_id)
                metadatas.append({
                    "repo_id": str(repo_id),
                    "file_path": str(file_path),
                    "symbol_name": str(symbol_name),
                    "symbol_type": str(c.get("symbol_type") or "file_chunk"),
                    "parent_symbol": str(c.get("parent_symbol") or ""),
                    "language": str(c.get("language") or "unknown"),
                    "start_line": int(c.get("start_line") or 1),
                    "end_line": int(c.get("end_line") or 1),
                    "chunk_index": int(c.get("chunk_index") or 0),
                    "sub_chunk_index": int(c.get("sub_chunk_index") or 0),
                    "sub_chunk_count": int(c.get("sub_chunk_count") or 1),
                })

            # Upsert to avoid duplicate-id errors on partial reindex
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Stored {len(chunks)} symbol embeddings for repo {repo_id}")

        except Exception as e:
            logger.error(f"Failed to store symbol embeddings: {e}")
            raise

    def _list_file_chunks(self, collection, file_path: str) -> List[Dict[str, Any]]:
        """Load all chunks for a file, ordered by chunk_index."""
        try:
            result = collection.get(
                where={"file_path": file_path},
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning(f"Failed to list file chunks for {file_path}: {e}")
            return []

        docs = result.get("documents") or []
        metas = result.get("metadatas") or []
        items = []
        for doc, meta in zip(docs, metas):
            meta = meta or {}
            items.append({
                "content": doc or "",
                "chunk_index": int(meta.get("chunk_index") or 0),
                "symbol_name": meta.get("symbol_name") or "",
                "symbol_type": meta.get("symbol_type") or "",
                "parent_symbol": meta.get("parent_symbol") or "",
                "start_line": int(meta.get("start_line") or 0),
                "end_line": int(meta.get("end_line") or 0),
            })
        items.sort(key=lambda x: (x["chunk_index"], x["start_line"]))
        return items

    def _expand_with_context(
        self,
        collection,
        hit: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach neighboring and parent-class context to a search hit."""
        file_path = hit.get("file_path") or ""
        chunk_index = int(hit.get("chunk_index") or 0)
        parent_symbol = hit.get("parent_symbol") or ""

        context_before = ""
        context_after = ""
        parent_context = ""

        file_chunks = self._list_file_chunks(collection, file_path) if file_path else []
        by_index = {c["chunk_index"]: c for c in file_chunks}

        prev_chunk = by_index.get(chunk_index - 1)
        next_chunk = by_index.get(chunk_index + 1)
        if prev_chunk:
            context_before = truncate_to_tokens(prev_chunk["content"], CONTEXT_TOKEN_CAP)
        if next_chunk:
            context_after = truncate_to_tokens(next_chunk["content"], CONTEXT_TOKEN_CAP)

        if parent_symbol:
            for c in file_chunks:
                if (
                    c.get("symbol_name") == parent_symbol
                    and c.get("symbol_type") == "class"
                    and c.get("chunk_index") != chunk_index
                ):
                    # Prefer class header (first sub-chunk / class itself)
                    parent_context = truncate_to_tokens(c["content"], CONTEXT_TOKEN_CAP)
                    break

        return {
            **hit,
            "context_before": context_before,
            "context_after": context_after,
            "parent_context": parent_context,
        }

    async def semantic_search(
        self,
        repo_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        try:
            collection = self.get_or_create_collection(repo_id)
            collection_count = collection.count()

            if collection_count == 0:
                return []

            n_results = min(top_k, collection_count)
            query_embedding = await self.embed_text(query)

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
            )

            formatted_results = []
            if results["documents"] and len(results["documents"]) > 0:
                for doc, metadata, distance in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    metadata = metadata or {}
                    hit = {
                        "file_path": metadata.get("file_path"),
                        "chunk_index": int(metadata.get("chunk_index") or 0),
                        "content": doc,
                        "similarity": 1 - distance,
                        "symbol_name": metadata.get("symbol_name") or "",
                        "symbol_type": metadata.get("symbol_type") or "",
                        "parent_symbol": metadata.get("parent_symbol") or "",
                        "language": metadata.get("language") or "",
                        "start_line": int(metadata.get("start_line") or 0),
                        "end_line": int(metadata.get("end_line") or 0),
                        "sub_chunk_index": int(metadata.get("sub_chunk_index") or 0),
                        "sub_chunk_count": int(metadata.get("sub_chunk_count") or 1),
                    }
                    formatted_results.append(
                        self._expand_with_context(collection, hit)
                    )

            # #region agent log
            try:
                from debug_log import debug_log
                debug_log("A", "embedding_service.py:semantic_search", "search completed", {
                    "repo_id": repo_id,
                    "query": query,
                    "collection_count": collection_count,
                    "result_count": len(formatted_results),
                    "top_file_paths": [r.get("file_path") for r in formatted_results[:3]],
                    "top_symbols": [r.get("symbol_name") for r in formatted_results[:3]],
                })
            except Exception:
                pass
            # #endregion

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
        results = {}
        for query in queries:
            results[query] = await self.semantic_search(repo_id, query, top_k)
        return results

    def delete_collection(self, repo_id: str) -> None:
        try:
            if repo_id in self.collections:
                self.client.delete_collection(f"repo_{repo_id}")
                del self.collections[repo_id]
                logger.info(f"Deleted collection for {repo_id}")
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")

    async def close(self) -> None:
        try:
            pass
        except Exception as e:
            logger.error(f"Failed to close EmbeddingService: {e}")
