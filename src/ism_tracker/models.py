"""The schema contract.

Two rules drive every design decision in this file:

1. **Every factual field carries provenance.** A number without a source link is
   a rumour, and publishing rumours as facts is the one failure mode that kills
   this project. So factual fields are wrapped in ``Sourced[T]``, which cannot be
   constructed without a ``Provenance``. A field with no provenance has no value
   at all -- it is ``None``, and renders as an em dash.

2. **Values are never overwritten.** When a fact changes, the old value moves
   into ``Sourced.superseded`` with the reason and date. The audit trail is the
   product.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2)]

SourceType = Literal["primary_govt", "primary_company", "media", "inferred"]
Confidence = Literal["confirmed", "reported", "unconfirmed"]


class Base(BaseModel):
    """Strict by default: a typo in hand-edited YAML must fail loudly, not silently."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


class Provenance(Base):
    """Where a single fact came from.

    ``quote_hash`` stores a hash of the supporting snippet rather than the snippet
    itself -- it proves we read a specific sentence without republishing
    copyrighted text. Use :func:`hash_quote` to produce it.
    """

    source_url: HttpUrl
    source_name: str = Field(min_length=1)  # "PIB", "MeitY", "Micron IR", "Reuters"
    source_type: SourceType
    retrieved_at: datetime
    confidence: Confidence
    quote_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # Link rot is a certainty over a multi-year project, so keep an archive fallback
    # (validate --check-links records dead links against this field).
    archive_url: HttpUrl | None = None
    published_at: date | None = None  # date of the source document itself, if known
    note: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v

    @property
    def is_primary(self) -> bool:
        return self.source_type in ("primary_govt", "primary_company")


def hash_quote(snippet: str) -> str:
    """Stable hash of a supporting snippet, whitespace-normalised."""
    return hashlib.sha256(" ".join(snippet.split()).encode("utf-8")).hexdigest()


T = TypeVar("T")


class Superseded(Base, Generic[T]):
    """A value we used to publish, kept forever."""

    value: T
    provenance: Provenance
    superseded_on: date
    reason: str = Field(min_length=1)


class Sourced(Base, Generic[T]):
    """A value that cannot exist without a source.

    In YAML this is written either fully::

        investment_inr_cr:
          value: 22516
          provenance: {source_url: "https://...", source_name: PIB, ...}

    or, far more commonly, using a reference into the project's own ``refs`` block::

        investment_inr_cr: {value: 22516, src: pib-2023-06-28}

    The ``src`` shorthand is expanded by :mod:`ism_tracker.loader` before validation.
    """

    value: T
    provenance: Provenance
    superseded: list[Superseded[T]] = Field(default_factory=list)

    @property
    def confidence(self) -> Confidence:
        return self.provenance.confidence

    def __str__(self) -> str:  # convenience for templates
        return str(self.value)


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #


class Scheme(str, Enum):
    ISM_1_0 = "ISM_1.0"
    ISM_2_0 = "ISM_2.0"
    SPECS = "SPECS"
    STATE = "State"
    NON_SCHEME = "Non-scheme"


class FacilityType(str, Enum):
    LOGIC_FAB = "logic_fab"
    COMPOUND_FAB = "compound_fab"
    SIC_FAB = "sic_fab"
    DISPLAY_FAB = "display_fab"
    ATMP_OSAT = "atmp_osat"
    SUBSTRATE = "substrate"
    OTHER = "other"


class Status(str, Enum):
    """The status ladder.

    The first nine values are ordered rungs. The last three are *conditions*, not
    rungs: a project that slips is still physically somewhere on the ladder, so
    ``status_history`` records the move to ``delayed``/``stalled``/``cancelled``
    while ``last_ladder_status`` remembers how far it had got.
    """

    ANNOUNCED = "announced"
    CABINET_APPROVED = "cabinet_approved"
    FSA_SIGNED = "fsa_signed"
    LAND_ALLOTTED = "land_allotted"
    GROUNDBROKEN = "groundbroken"
    UNDER_CONSTRUCTION = "under_construction"
    EQUIPMENT_INSTALL = "equipment_install"
    PILOT_PRODUCTION = "pilot_production"
    COMMERCIAL_PRODUCTION = "commercial_production"
    DELAYED = "delayed"
    STALLED = "stalled"
    CANCELLED = "cancelled"


LADDER: tuple[Status, ...] = (
    Status.ANNOUNCED,
    Status.CABINET_APPROVED,
    Status.FSA_SIGNED,
    Status.LAND_ALLOTTED,
    Status.GROUNDBROKEN,
    Status.UNDER_CONSTRUCTION,
    Status.EQUIPMENT_INSTALL,
    Status.PILOT_PRODUCTION,
    Status.COMMERCIAL_PRODUCTION,
)

#: Conditions that legitimately interrupt monotonic progress up the ladder.
REGRESSIONS: frozenset[Status] = frozenset(
    {Status.DELAYED, Status.STALLED, Status.CANCELLED}
)

#: Below this rung, a project that has blown its target date counts as slipping.
PRODUCING = (Status.PILOT_PRODUCTION, Status.COMMERCIAL_PRODUCTION)


def ladder_rank(status: Status) -> int | None:
    """Position on the ladder, or ``None`` for the three condition statuses."""
    try:
        return LADDER.index(status)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Sub-records
# --------------------------------------------------------------------------- #


class Location(Base):
    city: str | None = None
    district: str | None = None
    state: str  # the one geography field we always require -- it drives the map
    cluster: str | None = None  # e.g. "Dholera SIR", "Sanand GIDC"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _coords_come_in_pairs(self) -> Location:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be given together")
        return self


class Capacity(Base):
    """Capacity as *stated by the source*.

    Units in this industry are not comparable: wafer starts per month, chips per
    day, million units per year, and modules per year all appear in official
    releases for projects sitting next to each other. Normalising them silently
    would manufacture a false comparison, so we store the number, the unit and the
    basis exactly as stated and render the unit alongside the value everywhere.
    """

    value: float = Field(gt=0)
    unit: str = Field(min_length=1)  # "wafer starts per month", "chips per day"
    basis: str | None = None  # "at full capacity", "phase 1", "design capacity"


class StatusEvent(Base):
    date: date
    from_status: Status | None = None  # None for the first recorded status
    to_status: Status
    provenance: Provenance
    note: str | None = None


class KeyDates(Base):
    approval: Sourced[date] | None = None
    groundbreaking: Sourced[date] | None = None
    target_first_output: Sourced[date] | None = None
    target_full_production: Sourced[date] | None = None


class FxRate(Base):
    """Recorded whenever we present a converted currency figure (validate §9)."""

    usd_inr: float = Field(gt=0)
    rate_date: date
    rate_source: str


# --------------------------------------------------------------------------- #
# Project
# --------------------------------------------------------------------------- #

#: Fields whose value is a claim about the world and therefore must be Sourced[T].
#: `validate` walks this list; it is the machine-readable form of design rule #1.
FACTUAL_FIELDS: tuple[str, ...] = (
    "parent_company",
    "jv_partners",
    "scheme",
    "facility_type",
    "investment_inr_cr",
    "investment_usd_mn",
    "capacity",
    "technology_node",
    "products",
    "end_markets",
    "status",
    "employment_direct",
    "employment_indirect",
)


class Project(Base):
    id: Slug  # stable forever, e.g. "micron-sanand-atmp"
    name: str = Field(min_length=1)
    company: str = Field(min_length=1)
    parent_company: Sourced[str] | None = None
    jv_partners: Sourced[list[str]] | None = None

    scheme: Sourced[Scheme]
    facility_type: Sourced[FacilityType]
    location: Location

    investment_inr_cr: Sourced[float] | None = None
    investment_usd_mn: Sourced[float] | None = None
    fx: FxRate | None = None  # required if both currency figures are present

    capacity: Sourced[Capacity] | None = None
    technology_node: Sourced[str] | None = None
    products: Sourced[list[str]] | None = None
    end_markets: Sourced[list[str]] | None = None

    status: Sourced[Status]
    status_history: list[StatusEvent] = Field(default_factory=list)
    key_dates: KeyDates = Field(default_factory=KeyDates)

    employment_direct: Sourced[int] | None = None
    employment_indirect: Sourced[int] | None = None

    last_verified_at: date
    verification_owner: str = Field(min_length=1)
    notes_md: str | None = None

    #: Set for entries that are tracked for context but are not ISM manufacturing
    #: approvals (SPECS units, legacy government fabs). Kept out of headline totals.
    adjacent: bool = False

    @model_validator(mode="after")
    def _history_is_ordered(self) -> Project:
        dates = [e.date for e in self.status_history]
        if dates != sorted(dates):
            raise ValueError(f"{self.id}: status_history must be in date order")
        return self

    @model_validator(mode="after")
    def _conversion_records_its_rate(self) -> Project:
        if self.investment_inr_cr and self.investment_usd_mn and self.fx is None:
            raise ValueError(
                f"{self.id}: both INR and USD investment figures are present, so `fx` "
                "must record the rate and date used (or drop the derived one)"
            )
        return self

    # -- derived -------------------------------------------------------------

    @property
    def last_ladder_status(self) -> Status | None:
        """How far up the ladder the project actually got.

        For a project whose current status is a condition (delayed/stalled/
        cancelled), this is the last real rung it stood on.
        """
        if ladder_rank(self.status.value) is not None:
            return self.status.value
        for event in reversed(self.status_history):
            if ladder_rank(event.to_status) is not None:
                return event.to_status
        return None

    @property
    def target_date(self) -> date | None:
        """The nearest published target we can be held to."""
        for field in (self.key_dates.target_first_output, self.key_dates.target_full_production):
            if field is not None:
                return field.value
        return None

    def slip_months(self, today: date | None = None) -> int | None:
        """Months past a published target, or ``None`` if not slipping.

        Derived, never stored: a project is slipping when its target date has
        passed and it is not yet producing. This is why `delayed` is computed
        rather than hand-maintained -- nobody issues a press release to announce
        that they are late.
        """
        today = today or date.today()
        target = self.target_date
        if target is None or target >= today:
            return None
        if self.status.value in PRODUCING or self.status.value is Status.CANCELLED:
            return None
        return (today.year - target.year) * 12 + (today.month - target.month)

    def is_stale(self, today: date | None = None, max_age_days: int = 60) -> bool:
        today = today or date.today()
        return (today - self.last_verified_at).days > max_age_days


# --------------------------------------------------------------------------- #
# Companies, sources, events
# --------------------------------------------------------------------------- #


class Company(Base):
    id: Slug
    name: str
    parent: str | None = None
    country: str | None = None
    kind: Literal["idm", "foundry", "osat", "equipment", "conglomerate", "other"] = "other"
    jv_of: list[str] = Field(default_factory=list)
    website: HttpUrl | None = None
    ir_url: HttpUrl | None = None  # press / investor-relations page we poll
    notes_md: str | None = None


class Source(Base):
    """A feed we poll. Distinct from Provenance, which cites one document."""

    id: Slug
    name: str
    url: HttpUrl
    type: Literal["pib", "ism_site", "rss", "company", "state_govt", "html"]
    source_type: SourceType
    poll_frequency: Literal["daily", "weekly", "monthly"] = "daily"
    enabled: bool = True
    #: Restrict PIB-style feeds to a ministry / query fragment.
    params: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None


class Event(Base):
    """One line of ``events.jsonl`` -- the append-only change log.

    This is what the digest diffs and what ``/changes/`` renders. Written by
    ``apply``, never hand-edited.
    """

    ts: datetime
    project_id: Slug
    field: str
    old_value: Any = None
    new_value: Any = None
    kind: Literal["status_change", "field_update", "new_project", "correction"]
    provenance: Provenance
    applied_by: str
    note: str | None = None

    @field_validator("ts")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


class CandidateChange(Base):
    """A proposed change awaiting human review.

    Produced by the extractors, written to ``review/pending.md``, and never
    applied automatically. Also the JSON schema the optional LLM step must
    conform to.
    """

    project_id: Slug | None = None  # None => proposes a brand-new project
    field: str
    current_value: Any = None
    proposed_value: Any = None
    evidence_url: HttpUrl
    evidence_snippet: str
    confidence: Confidence
    extractor: str  # "rules" | "llm:<model>"
    score: float = Field(default=0.0, ge=0.0)

    @property
    def fingerprint(self) -> str:
        """Stable id so the same proposal is not re-queued every day."""
        raw = f"{self.project_id}|{self.field}|{self.proposed_value}|{self.evidence_url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class RawDoc(Base):
    """A fetched document, before any interpretation."""

    url: HttpUrl
    title: str | None = None
    published_at: datetime | None = None
    text: str
    source_name: str
    content_hash: str

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


class Dataset(Base):
    """Everything loaded, validated and cross-checked together."""

    projects: list[Project] = Field(default_factory=list)
    companies: list[Company] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

    def project(self, project_id: str) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)

    @property
    def headline_projects(self) -> list[Project]:
        """ISM manufacturing approvals only -- what the cumulative totals cover."""
        return [p for p in self.projects if not p.adjacent]
