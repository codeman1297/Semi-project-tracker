"""Paths and settings. No secrets here -- those come from .env via python-dotenv."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op when .env is absent, which is the case in CI

# Repo root = two levels up from this file (src/ism_tracker/config.py).
ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
PROJECTS_YAML = DATA_DIR / "projects.yaml"
COMPANIES_YAML = DATA_DIR / "companies.yaml"
SOURCES_YAML = DATA_DIR / "sources.yaml"
EVENTS_JSONL = DATA_DIR / "events.jsonl"

CACHE_DIR = ROOT / ".cache"
DB_PATH = ROOT / "ism.db"
SITE_DIR = ROOT / "site"
OUT_DIR = ROOT / "out"
REVIEW_DIR = ROOT / "review"
PENDING_MD = REVIEW_DIR / "pending.md"

#: Sent on every outbound request so site owners can identify and contact us.
USER_AGENT = os.getenv(
    "ISM_TRACKER_USER_AGENT",
    "ism-tracker/0.1 (+https://github.com/codeman1297/semi-project-tracker; public dataset bot)",
)
#: Politeness floor, per domain. Never lower this.
REQUEST_DELAY_SECONDS = float(os.getenv("ISM_TRACKER_REQUEST_DELAY", "2.0"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("ISM_TRACKER_REQUEST_TIMEOUT", "30"))

#: Optional. Absent means the core pipeline runs exactly as it always does.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LLM_MODEL = os.getenv("ISM_TRACKER_LLM_MODEL", "claude-sonnet-5")

SITE_BASE_URL = os.getenv("ISM_TRACKER_SITE_URL", "https://example.invalid/ism-tracker")
CONTACT_EMAIL = os.getenv("ISM_TRACKER_CONTACT", "corrections@example.invalid")

#: A project unverified for longer than this is flagged stale by `validate`.
STALE_AFTER_DAYS = int(os.getenv("ISM_TRACKER_STALE_DAYS", "60"))


@dataclass(frozen=True)
class Reconciliation:
    """The published cumulative investment figure we check our own sum against.

    If our per-project sum drifts from the officially stated cumulative number by
    more than the tolerance, either a project is missing or a figure is wrong.
    Both are worth being told about. Populated for real in step 2, against a
    primary source.
    """

    stated_total_inr_cr: float | None = None
    stated_project_count: int | None = None
    source_url: str | None = None
    as_of: str | None = None
    tolerance_pct: float = 5.0
    #: Set False until the figure above is verified against a primary source.
    verified: bool = False


RECONCILIATION = Reconciliation(
    # TODO(step 2): fill in from the PIB / ism.gov.in release that states the
    # cumulative approved investment, and set verified=True.
    tolerance_pct=float(os.getenv("ISM_TRACKER_RECONCILE_TOLERANCE", "5.0")),
)

#: Dataset licence, advertised on every download.
DATA_LICENCE = "CC BY 4.0"


@dataclass
class Paths:
    """Overridable paths, so tests can point at fixture directories."""

    projects: Path = PROJECTS_YAML
    companies: Path = COMPANIES_YAML
    sources: Path = SOURCES_YAML
    events: Path = EVENTS_JSONL
    extra: dict[str, Path] = field(default_factory=dict)


DEFAULT_PATHS = Paths()
