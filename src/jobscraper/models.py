from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    """Normalized job posting, regardless of source."""

    id: str  # globally unique: "<source>:<token>:<job_id>"
    source: str  # greenhouse | lever | ashby | ...
    company: str
    title: str
    location: str
    url: str  # employer posting link
    remote: bool | None = None
    country: str | None = None  # country hint from the source (ISO code or name), if given
    posted_at: datetime | None = None  # when the employer first published it, if known
    updated_at: datetime | None = None
    compensation: str | None = None
    department: str | None = None
    description: str = ""  # plain text, full (filters scan it); truncated on output
    tier: str | None = None  # company tier from companies.yaml
    flags: list[str] = field(default_factory=list)
    match_tier: int | None = None  # 1 or 2, set by title filter

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("posted_at", "updated_at"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d
