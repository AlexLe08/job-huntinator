"""Title / location / red-flag filters. Pure functions; config comes from config/filters.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Job

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "filters.yaml"


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.I)


@dataclass
class FilterConfig:
    freshness_hours: float
    senior_mode: str
    tier1: list[re.Pattern[str]]
    tier2: list[re.Pattern[str]]
    exclude: list[re.Pattern[str]]
    mobile_only: re.Pattern[str]
    generic_swe: re.Pattern[str]
    generic_swe_exclude: re.Pattern[str]
    senior: re.Pattern[str]
    location_keep: set[str]
    location_flag: dict[str, str]
    red_flag_mode: str
    red_flags: dict[str, re.Pattern[str]]
    citizen_with_clearance: re.Pattern[str]
    title_similarity: float

    @classmethod
    def load(cls, path: str | Path | None = None) -> FilterConfig:
        return cls.from_dict(yaml.safe_load(Path(path or DEFAULT_PATH).read_text()))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FilterConfig:
        t, loc, rf = d["title"], d["location"], d["red_flags"]
        senior_mode = d.get("senior_mode", "flag")
        if senior_mode not in ("flag", "drop"):
            raise ValueError("senior_mode must be 'flag' or 'drop'")
        return cls(
            freshness_hours=float(d.get("freshness_hours", 48)),
            senior_mode=senior_mode,
            tier1=[_rx(p) for p in t["tier1"]],
            tier2=[_rx(p) for p in t["tier2"]],
            exclude=[_rx(p) for p in t["exclude"]],
            mobile_only=_rx(t["mobile_only"]),
            generic_swe=_rx(t["generic_swe"]),
            generic_swe_exclude=_rx(t["generic_swe_exclude"]),
            senior=_rx(t["senior"]),
            location_keep=set(loc["keep"]),
            location_flag=dict(loc.get("flag") or {}),
            red_flag_mode=rf.get("mode", "drop"),
            red_flags={k: _rx(v) for k, v in rf["patterns"].items()},
            citizen_with_clearance=_rx(rf["citizen_with_clearance"]),
            title_similarity=float((d.get("dedupe") or {}).get("title_similarity", 0.85)),
        )


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    match_tier: int | None = None
    location_class: str | None = None
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- title


def normalize_title(title: str) -> str:
    t = title.lower().replace("&", " and ")
    t = re.sub(r"[-‐–—/,|()\[\]:._+]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classify_title(title: str, cfg: FilterConfig) -> Verdict:
    t = normalize_title(title)
    flags: list[str] = []
    for rx in cfg.exclude:
        if rx.search(t):
            return Verdict(False, f"title-exclude:{rx.pattern}")
    t1 = any(rx.search(t) for rx in cfg.tier1)  # explicitly web/frontend/fullstack
    t2 = any(rx.search(t) for rx in cfg.tier2)
    generic = bool(cfg.generic_swe.search(t)) and not cfg.generic_swe_exclude.search(t)
    if cfg.mobile_only.search(t) and not t1:
        return Verdict(False, "title-mobile-only")
    if not (t1 or t2 or generic):
        if cfg.generic_swe.search(t):
            return Verdict(False, "title-swe-specialty")
        return Verdict(False, "title-no-match")
    tier = 1 if (t1 or generic) else 2
    if cfg.senior.search(t):
        if cfg.senior_mode == "drop":
            return Verdict(False, "title-senior")
        flags.append("senior")
    return Verdict(True, match_tier=tier, flags=flags)


# ---------------------------------------------------------------- location

US_STATES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new hampshire",
    "NJ": "new jersey",
    "NM": "new mexico",
    "NY": "new york",
    "NC": "north carolina",
    "ND": "north dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode island",
    "SC": "south carolina",
    "SD": "south dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
    "DC": "district of columbia",
}
_MA = re.compile(
    r"\b(boston|cambridge,? ma|cambridge, massachusetts|somerville|worcester|waltham|burlington,? ma|lexington,? ma|newton,? ma|framingham|quincy|woburn|bedford,? ma|marlborough|massachusetts)\b|,\s*ma\b",
    re.I,
)
_NC = re.compile(
    r"\b(raleigh|durham|research triangle|rtp|chapel hill|cary|morrisville|north carolina)\b|,\s*nc\b", re.I
)
_US_CITIES = re.compile(
    r"\b(san francisco|sf bay|bay area|new york|nyc|seattle|austin|chicago|los angeles|denver|boulder|atlanta|"
    r"portland|san diego|san jose|palo alto|mountain view|menlo park|sunnyvale|oakland|redwood city|"
    r"washington,? d\.?c|philadelphia|pittsburgh|miami|dallas|houston|phoenix|salt lake|minneapolis|"
    r"detroit|nashville|charlotte|columbus|st\.? louis|kansas city|baltimore|brooklyn|jersey city|"
    r"irvine|santa monica|lehi|provo|madison|ann arbor|indianapolis|richmond|tampa|orlando)\b",
    re.I,
)
_US_GENERIC = re.compile(r"\b(united states|usa|u\.s\.a?\.?|us|north america|americas|nationwide)\b", re.I)
_US_STATE_ABBR = re.compile(r",\s*(" + "|".join(US_STATES) + r")\b")
_US_STATE_NAME = re.compile(r"\b(" + "|".join(v for v in US_STATES.values() if v != "washington") + r")\b", re.I)
_NON_US = re.compile(
    r"\b(canada|toronto|vancouver|montreal|ottawa|mexico|brazil|são paulo|sao paulo|argentina|colombia|chile|"
    r"uk|united kingdom|england|london|manchester|edinburgh|ireland|dublin|germany|berlin|munich|france|paris|"
    r"spain|madrid|barcelona|portugal|lisbon|netherlands|amsterdam|poland|warsaw|sweden|stockholm|denmark|"
    r"copenhagen|norway|oslo|finland|helsinki|switzerland|zurich|austria|vienna|italy|milan|europe|eu|"
    r"european union|emea|apac|latam|india|bangalore|bengaluru|hyderabad|pune|singapore|japan|tokyo|"
    r"australia|sydney|melbourne|new zealand|israel|tel aviv|uae|dubai|korea|seoul|china|hong kong|taiwan|"
    r"philippines|indonesia|vietnam|nigeria|kenya|south africa|estonia|romania|ukraine|czech|prague|"
    r"hungary|budapest|serbia|greece|turkey|istanbul|belgium|brussels|asia|africa|oceania|middle east|"
    r"latin america|south america|central america|caribbean|anguilla|pakistan|bangladesh|egypt|malaysia|thailand)\b",
    re.I,
)
_REMOTE = re.compile(r"\b(remote|anywhere|distributed|work from home|wfh)\b", re.I)
_SPLIT = re.compile(r";|\||\s/\s|\bor\b|\n|·")
US_COUNTRY_HINTS = {"us", "usa", "united states", "united states of america"}

LOC_PRIORITY = ["MA", "NC", "us_remote", "us_onsite", "remote_unspecified", "unknown", "non_us"]


def _classify_segment(seg: str) -> str:
    s = seg.strip()
    if not s:
        return "unknown"
    remote = bool(_REMOTE.search(s))
    if _MA.search(s) and not re.search(r"cambridge,? (uk|england)", s, re.I):
        return "MA"
    if _NC.search(s):
        return "NC"
    us = bool(_US_CITIES.search(s) or _US_GENERIC.search(s) or _US_STATE_ABBR.search(s) or _US_STATE_NAME.search(s))
    non_us = bool(_NON_US.search(s))
    if us:
        return "us_remote" if remote else "us_onsite"
    if non_us:
        return "non_us"
    if remote:
        return "remote_unspecified"
    return "unknown"


def classify_location(location: str, remote: bool | None = None, country: str | None = None) -> str:
    segments = [p for p in _SPLIT.split(location or "") if p and p.strip()] or [""]
    classes = {_classify_segment(s) for s in segments}
    best = min(classes, key=LOC_PRIORITY.index)
    c = (country or "").strip().lower()
    if best in ("unknown", "remote_unspecified") and c:
        if c in US_COUNTRY_HINTS:
            return "us_remote" if (remote or best == "remote_unspecified") else "us_onsite"
        return "non_us"
    # "United States" (no city/state) + remote flag -> US remote
    if (
        best == "us_onsite"
        and remote
        and not (_US_CITIES.search(location) or _US_STATE_ABBR.search(location) or _US_STATE_NAME.search(location))
    ):
        return "us_remote"
    return best


# ---------------------------------------------------------------- red flags


def red_flags(text: str, cfg: FilterConfig) -> list[str]:
    hits = [name for name, rx in cfg.red_flags.items() if rx.search(text or "")]
    if "clearance" in hits and cfg.citizen_with_clearance.search(text or ""):
        hits.append("citizen+clearance")
    return hits


# ---------------------------------------------------------------- combined


def evaluate(job: Job, cfg: FilterConfig) -> Verdict:
    v = classify_title(job.title, cfg)
    if not v.keep:
        return v
    loc = classify_location(job.location, job.remote, job.country)
    v.location_class = loc
    if loc not in cfg.location_keep:
        return Verdict(False, f"location:{loc}", v.match_tier, loc)
    if loc in cfg.location_flag:
        v.flags.append(cfg.location_flag[loc])
    rf = red_flags(job.description, cfg)
    if rf:
        if cfg.red_flag_mode == "drop":
            return Verdict(False, "red-flag:" + ",".join(rf), v.match_tier, loc, v.flags + rf)
        v.flags.extend(rf)
    if job.match_tier is None:
        job.match_tier = v.match_tier
    return v
