"""In-memory edit history for apply / undo of agent proposals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    file_path: str
    before: str
    after: str


@dataclass
class EditRequestSnapshot:
    repo_id: str
    request_id: str
    files: List[FileSnapshot] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


class EditHistory:
    """Store before/after snapshots keyed by (repo_id, request_id)."""

    def __init__(self):
        self._history: Dict[str, EditRequestSnapshot] = {}

    def _key(self, repo_id: str, request_id: str) -> str:
        return f"{repo_id}::{request_id}"

    def save_snapshot(
        self,
        repo_id: str,
        request_id: str,
        files: List[Dict[str, str]],
    ) -> EditRequestSnapshot:
        snapshots = [
            FileSnapshot(
                file_path=f["file_path"],
                before=f.get("before", ""),
                after=f.get("after", ""),
            )
            for f in files
        ]
        entry = EditRequestSnapshot(
            repo_id=repo_id,
            request_id=request_id,
            files=snapshots,
        )
        self._history[self._key(repo_id, request_id)] = entry
        logger.info(
            "Saved edit snapshot %s (%d files)",
            request_id,
            len(snapshots),
        )
        return entry

    def get(self, repo_id: str, request_id: str) -> Optional[EditRequestSnapshot]:
        return self._history.get(self._key(repo_id, request_id))

    def pop(self, repo_id: str, request_id: str) -> Optional[EditRequestSnapshot]:
        return self._history.pop(self._key(repo_id, request_id), None)

    def to_dict(self, entry: EditRequestSnapshot) -> Dict[str, Any]:
        return {
            "repo_id": entry.repo_id,
            "request_id": entry.request_id,
            "files": [
                {
                    "file_path": f.file_path,
                    "before": f.before,
                    "after": f.after,
                }
                for f in entry.files
            ],
            "created_at": entry.created_at.isoformat() + "Z",
        }
