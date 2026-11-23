"""Source registry.

A *company source* (ATS) exposes:
    API_NAME: str
    def board_url(token: str) -> str
    def fetch(client, company) -> list[Job]          # raises FetchError on failure
    def normalize(raw: dict, company) -> Job
    def enrich(client, job, company) -> None      # optional: fill description etc. for filtered candidates only
"""
from __future__ import annotations

from types import ModuleType

from . import ashby, greenhouse, lever, recruitee, smartrecruiters, workable, workday

COMPANY_SOURCES: dict[str, ModuleType] = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
    "recruitee": recruitee,
    "workday": workday,
}

# ATSes the validator may auto-detect by slug guessing. SmartRecruiters answers 200 with zero jobs for any
# name and Workday needs host/site, so those two must be configured explicitly.
AUTODETECT = ["greenhouse", "lever", "ashby", "workable", "recruitee"]


def get_company_source(ats: str) -> ModuleType:
    try:
        return COMPANY_SOURCES[ats]
    except KeyError:
        raise ValueError(f"unknown ats '{ats}' (known: {', '.join(COMPANY_SOURCES)})") from None
