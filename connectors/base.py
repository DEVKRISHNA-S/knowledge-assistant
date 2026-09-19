"""
Base connector interface.

Every data source (GitHub, Slack, Confluence, ...) implements this interface.
Nothing outside `connectors/` should ever import a source-specific SDK
(no `import slack_sdk` in ingestion/ or retrieval/) — that's the whole point
of this abstraction. If you add a 3rd source later, this file should not change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator, Optional


@dataclass
class RawItem:
    """
    A single normalized unit of content from any source, BEFORE chunking.
    e.g. one Slack thread, one GitHub PR (with its comments), one Confluence page.
    """
    source: str                      # "github" | "slack" | ...
    source_id: str                   # unique id within that source, e.g. "psf/requests#6721"
    title: str                       # human-readable title/summary line
    content: str                     # the actual text to embed (already cleaned)
    permission_scope: str            # e.g. repo full_name, or slack channel_id
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)  # source-specific extras


class BaseConnector(ABC):
    """
    Implement this for each new source.
    """

    source_name: str  # set by subclass, e.g. "github"

    @abstractmethod
    def fetch_since(self, cursor: Optional[str]) -> Iterator[RawItem]:
        """
        Yield RawItems updated/created since `cursor`.
        `cursor` is whatever this connector last returned via `get_next_cursor`
        (e.g. an ISO timestamp, or a GitHub API pagination token).
        Pass cursor=None to do a full initial sync.
        """
        raise NotImplementedError

    @abstractmethod
    def get_next_cursor(self) -> str:
        """
        Return the cursor value to persist in `sync_state` after this run,
        so the *next* call to fetch_since() picks up where this one left off.
        """
        raise NotImplementedError