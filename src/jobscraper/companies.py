"""Load the company list (config/companies.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Company:
    company: str
    ats: str
    token: str
    tier: str | None = None
    notes: str | None = None
    disabled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)  # source-specific (e.g. workday host/site)


KNOWN_KEYS = {"company", "ats", "token", "tier", "notes", "disabled"}


def load_companies(path: str | Path, include_disabled: bool = False) -> list[Company]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    rows = data.get("companies", data) if isinstance(data, dict) else data
    out: list[Company] = []
    for row in rows or []:
        c = Company(
            company=str(row["company"]),
            ats=str(row["ats"]).lower(),
            token=str(row["token"]),
            tier=row.get("tier"),
            notes=row.get("notes"),
            disabled=bool(row.get("disabled", False)),
            extra={k: v for k, v in row.items() if k not in KNOWN_KEYS},
        )
        if include_disabled or not c.disabled:
            out.append(c)
    return out
