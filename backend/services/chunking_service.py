"""AST-based semantic chunking for code embeddings."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .ast_service import ASTService

logger = logging.getLogger(__name__)

# ~400 tokens before splitting (chars // 4)
MAX_CHUNK_TOKENS = 400
# Overlap when splitting oversized symbols
OVERLAP_LINES = 10
OVERLAP_TOKEN_BUDGET = 50
# Target window size when splitting (~350 tokens)
SPLIT_TOKEN_BUDGET = 350
# Fixed-size fallback (~1000 chars, same as before)
FALLBACK_CHAR_SIZE = 1000
# Cap neighbor context on retrieve (~200 tokens)
CONTEXT_TOKEN_CAP = 200


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def truncate_to_tokens(text: str, max_tokens: int = CONTEXT_TOKEN_CAP) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n..."


class ChunkingService:
    """
    Build embedding chunks from AST symbols (functions, methods, classes, decls).
    Falls back to fixed-size line chunks when AST is unavailable.
    """

    def __init__(self, ast_service: Optional[ASTService] = None):
        self.ast_service = ast_service or ASTService()

    def chunk_file(
        self,
        content: str,
        file_path: str,
        language: str,
        ast_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        lines = content.split("\n")
        symbols = self.ast_service.iter_symbols(ast_data) if ast_data else []

        if not symbols:
            return self._fallback_chunks(content, file_path, language)

        raw_chunks: List[Dict[str, Any]] = []
        for symbol in symbols:
            start = max(1, int(symbol.get("line") or 1))
            end = max(start, int(symbol.get("end_line") or start))
            # Clamp to file bounds
            end = min(end, len(lines))
            start = min(start, len(lines)) if lines else 1

            text = "\n".join(lines[start - 1 : end])
            if not text.strip():
                continue

            sym_type = symbol.get("type") or "function"
            parent = symbol.get("parent_class") or ""
            if parent and sym_type in ("function", "async_function"):
                sym_type = "method"

            name = symbol.get("name") or "anonymous"
            base = {
                "file_path": file_path,
                "symbol_name": name,
                "symbol_type": sym_type,
                "parent_symbol": parent,
                "language": language,
            }

            if estimate_tokens(text) <= MAX_CHUNK_TOKENS:
                raw_chunks.append({
                    **base,
                    "content": text,
                    "start_line": start,
                    "end_line": end,
                    "sub_chunk_index": 0,
                    "sub_chunk_count": 1,
                })
            else:
                raw_chunks.extend(
                    self._split_oversized(text, start, end, base)
                )

        if not raw_chunks:
            return self._fallback_chunks(content, file_path, language)

        # Assign stable chunk_index by file order
        raw_chunks.sort(key=lambda c: (c["start_line"], c["sub_chunk_index"], c["symbol_name"]))
        for i, chunk in enumerate(raw_chunks):
            chunk["chunk_index"] = i

        return raw_chunks

    def _split_oversized(
        self,
        text: str,
        start_line: int,
        end_line: int,
        base: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Split a large symbol into overlapping line windows."""
        lines = text.split("\n")
        if not lines:
            return []

        window_lines = max(20, SPLIT_TOKEN_BUDGET)  # approx lines if ~1 token/line; refine below
        # Prefer ~80 lines or whatever fits SPLIT_TOKEN_BUDGET
        target_chars = SPLIT_TOKEN_BUDGET * 4
        overlap = OVERLAP_LINES

        windows: List[tuple] = []  # (rel_start, rel_end, content) 0-based in lines
        i = 0
        while i < len(lines):
            j = i
            length = 0
            while j < len(lines) and (length + len(lines[j]) + 1) <= target_chars:
                length += len(lines[j]) + 1
                j += 1
            if j == i:
                j = min(i + 1, len(lines))
            piece = "\n".join(lines[i:j])
            windows.append((i, j - 1, piece))
            if j >= len(lines):
                break
            next_i = max(i + 1, j - overlap)
            if next_i <= i:
                next_i = i + 1
            i = next_i

        count = len(windows)
        result = []
        for idx, (rel_start, rel_end, piece) in enumerate(windows):
            abs_start = start_line + rel_start
            abs_end = start_line + rel_end
            result.append({
                **base,
                "symbol_type": base.get("symbol_type", "function"),
                "content": piece,
                "start_line": abs_start,
                "end_line": min(abs_end, end_line),
                "sub_chunk_index": idx,
                "sub_chunk_count": count,
            })
        return result

    def _fallback_chunks(
        self,
        content: str,
        file_path: str,
        language: str,
        chunk_size: int = FALLBACK_CHAR_SIZE,
    ) -> List[Dict[str, Any]]:
        """Fixed-size line chunks when AST is unavailable."""
        lines = content.split("\n")
        chunks: List[Dict[str, Any]] = []
        current: List[str] = []
        current_length = 0
        start_line = 1

        for line_no, line in enumerate(lines, start=1):
            if not current:
                start_line = line_no
            current.append(line)
            current_length += len(line)

            if current_length > chunk_size:
                text = "\n".join(current)
                chunks.append({
                    "content": text,
                    "file_path": file_path,
                    "symbol_name": f"chunk_{len(chunks)}",
                    "symbol_type": "file_chunk",
                    "parent_symbol": "",
                    "language": language,
                    "start_line": start_line,
                    "end_line": line_no,
                    "sub_chunk_index": 0,
                    "sub_chunk_count": 1,
                    "chunk_index": len(chunks),
                })
                current = []
                current_length = 0

        if current:
            text = "\n".join(current)
            chunks.append({
                "content": text,
                "file_path": file_path,
                "symbol_name": f"chunk_{len(chunks)}",
                "symbol_type": "file_chunk",
                "parent_symbol": "",
                "language": language,
                "start_line": start_line,
                "end_line": len(lines) or 1,
                "sub_chunk_index": 0,
                "sub_chunk_count": 1,
                "chunk_index": len(chunks),
            })

        return chunks
