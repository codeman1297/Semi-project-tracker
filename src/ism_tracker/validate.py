"""`ism-tracker validate` -- the gate that runs in CI and blocks merge.

Every check here exists because a specific kind of wrong number could otherwise
reach the site. Errors block; warnings are printed and block only under
``--strict``. Link checking is opt-in so that the CI gate stays offline,
deterministic and fast; link rot is a separate weekly job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal

from . import config
from .models import (
    FACTUAL_FIELDS,
    REGRESSIONS,
    Dataset,
    Project,
    Sourced,
    Status,
    ladder_rank,
)

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    level: Level
    code: str
    message: str
    project_id: str | None = None

    def __str__(self) -> str:
        where = f"[{self.project_id}] " if self.project_id else ""
        return f"{self.level.upper():7} {self.code:24} {where}{self.message}"


@dataclass
class Report:
    findings: list[Finding]
    checked_projects: int = 0

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #


def _err(code: str, message: str, project_id: str | None = None) -> Finding:
    return Finding("error", code, message, project_id)


def _warn(code: str, message: str, project_id: str | None = None) -> Finding:
    return Finding("warning", code, message, project_id)


def check_provenance(project: Project) -> Iterable[Finding]:
    """Design rule #1: a factual field with a value must carry a source.

    ``Sourced[T]`` makes this true by construction; this check catches schema
    drift (someone widening a field to a bare type) and self-contradictory
    provenance.
    """
    for name in FACTUAL_FIELDS:
        value = getattr(project, name, None)
        if value is None:
            continue
        if not isinstance(value, Sourced):
            yield _err(
                "provenance.missing",
                f"`{name}` holds a bare value with no provenance",
                project.id,
            )
            continue
        prov = value.provenance
        if prov.source_type == "inferred" and prov.confidence == "confirmed":
            yield _err(
                "provenance.contradiction",
                f"`{name}` is marked confidence=confirmed but source_type=inferred; "
                "an inference cannot be confirmed",
                project.id,
            )
        if prov.source_type == "media" and prov.confidence == "confirmed":
            yield _warn(
                "provenance.media_confirmed",
                f"`{name}` is confirmed on a media source alone; prefer a primary "
                "source or downgrade to `reported`",
                project.id,
            )


def check_status(project: Project, today: date) -> Iterable[Finding]:
    """Status history must be monotonic up the ladder, apart from declared regressions."""
    history = project.status_history

    if history and history[-1].to_status is not project.status.value:
        yield _err(
            "status.history_mismatch",
            f"current status `{project.status.value.value}` does not match the last "
            f"history entry `{history[-1].to_status.value}`",
            project.id,
        )

    previous: Status | None = None
    for event in history:
        if event.from_status is not None and previous is not None and event.from_status is not previous:
            yield _err(
                "status.history_broken_chain",
                f"transition on {event.date} starts from `{event.from_status.value}` "
                f"but the previous entry left it at `{previous.value}`",
                project.id,
            )
        old_rank = ladder_rank(previous) if previous is not None else None
        new_rank = ladder_rank(event.to_status)
        if (
            previous is not None
            and old_rank is not None
            and new_rank is not None
            and new_rank < old_rank
            and event.to_status not in REGRESSIONS
        ):
            yield _err(
                "status.non_monotonic",
                f"moves backwards from `{previous.value}` to `{event.to_status.value}` "
                f"on {event.date} without being marked delayed/stalled/cancelled",
                project.id,
            )
        if event.date > today:
            yield _err(
                "status.future_dated",
                f"status event dated {event.date} is in the future",
                project.id,
            )
        previous = event.to_status


def check_dates(project: Project, today: date) -> Iterable[Finding]:
    kd = project.key_dates
    ordered = [
        ("approval", kd.approval),
        ("groundbreaking", kd.groundbreaking),
        ("target_first_output", kd.target_first_output),
        ("target_full_production", kd.target_full_production),
    ]
    present = [(name, f.value) for name, f in ordered if f is not None]
    for (a_name, a_date), (b_name, b_date) in zip(present, present[1:]):
        if b_date < a_date:
            yield _err(
                "dates.out_of_order",
                f"{b_name} ({b_date}) precedes {a_name} ({a_date})",
                project.id,
            )

    if project.last_verified_at > today:
        yield _err(
            "dates.verified_in_future",
            f"last_verified_at {project.last_verified_at} is in the future",
            project.id,
        )
    elif project.is_stale(today, config.STALE_AFTER_DAYS):
        age = (today - project.last_verified_at).days
        yield _warn(
            "stale",
            f"not verified for {age} days (limit {config.STALE_AFTER_DAYS})",
            project.id,
        )

    slip = project.slip_months(today)
    if slip is not None and project.status.value not in REGRESSIONS:
        yield _warn(
            "schedule.slipping",
            f"target {project.target_date} passed {slip} month(s) ago while status is "
            f"`{project.status.value.value}`; consider recording a `delayed` transition",
            project.id,
        )


def check_currency(project: Project) -> Iterable[Finding]:
    """A converted figure must record the rate and date used (§9)."""
    if not (project.investment_inr_cr and project.investment_usd_mn):
        return
    fx = project.fx
    if fx is None:  # already an error at model level; belt and braces
        yield _err("currency.no_rate", "two currency figures but no fx record", project.id)
        return
    # 1 crore = 10 million. inr_cr * 1e7 / rate / 1e6 = usd_mn
    implied = project.investment_inr_cr.value * 10.0 / fx.usd_inr
    stated = project.investment_usd_mn.value
    if stated and abs(implied - stated) / stated > 0.10:
        yield _warn(
            "currency.drift",
            f"USD figure {stated:,.0f} mn differs from INR {project.investment_inr_cr.value:,.0f} cr "
            f"at {fx.usd_inr}/USD (implies {implied:,.0f} mn) by more than 10%",
            project.id,
        )


def check_dataset(dataset: Dataset, today: date) -> Iterable[Finding]:
    known_companies = {c.name for c in dataset.companies} | {c.id for c in dataset.companies}
    known_projects = {p.id for p in dataset.projects}

    for project in dataset.projects:
        if dataset.companies and project.company not in known_companies:
            yield _warn(
                "company.unknown",
                f"company `{project.company}` is not in companies.yaml",
                project.id,
            )

    for index, event in enumerate(dataset.events, start=1):
        if event.project_id not in known_projects and event.kind != "new_project":
            yield _err(
                "events.unknown_project",
                f"events.jsonl line {index} references unknown project `{event.project_id}`",
            )

    # Reconciliation against the officially stated cumulative figure.
    recon = config.RECONCILIATION
    total = sum(
        p.investment_inr_cr.value for p in dataset.headline_projects if p.investment_inr_cr
    )
    if recon.stated_total_inr_cr and recon.verified:
        drift_pct = abs(total - recon.stated_total_inr_cr) / recon.stated_total_inr_cr * 100
        if drift_pct > recon.tolerance_pct:
            yield _warn(
                "reconcile.investment_drift",
                f"sum of project investments is Rs {total:,.0f} cr but the stated cumulative "
                f"figure is Rs {recon.stated_total_inr_cr:,.0f} cr ({drift_pct:.1f}% drift, "
                f"tolerance {recon.tolerance_pct}%) -- a project or a figure is probably missing",
            )
    elif dataset.projects:
        yield _warn(
            "reconcile.unset",
            "no verified cumulative investment figure configured, so per-project totals "
            f"(Rs {total:,.0f} cr) are unreconciled -- see config.RECONCILIATION",
        )

    if recon.stated_project_count and recon.verified:
        actual = len(dataset.headline_projects)
        if actual != recon.stated_project_count:
            yield _warn(
                "reconcile.project_count",
                f"tracking {actual} non-adjacent projects but the stated count is "
                f"{recon.stated_project_count}",
            )


def validate_dataset(dataset: Dataset, today: date | None = None) -> Report:
    today = today or date.today()
    findings: list[Finding] = []
    for project in dataset.projects:
        findings.extend(check_provenance(project))
        findings.extend(check_status(project, today))
        findings.extend(check_dates(project, today))
        findings.extend(check_currency(project))
    findings.extend(check_dataset(dataset, today))
    return Report(findings=findings, checked_projects=len(dataset.projects))


# --------------------------------------------------------------------------- #
# Link rot (opt-in; needs the network)
# --------------------------------------------------------------------------- #


def check_links(dataset: Dataset) -> list[Finding]:
    """Weekly link-rot pass. Dead links are warnings, not errors: the fact was
    true when we recorded it, and archive_url exists for exactly this case."""
    import httpx  # imported lazily so `validate` has no network dependency by default

    urls: dict[str, tuple[str | None, str | None]] = {}
    for project in dataset.projects:
        for name in FACTUAL_FIELDS:
            value = getattr(project, name, None)
            if isinstance(value, Sourced):
                prov = value.provenance
                urls.setdefault(str(prov.source_url), (project.id, str(prov.archive_url or "") or None))

    findings: list[Finding] = []
    headers = {"User-Agent": config.USER_AGENT}
    with httpx.Client(headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        for url, (project_id, archive) in sorted(urls.items()):
            try:
                response = client.head(url)
                if response.status_code >= 400:  # some govt sites reject HEAD
                    response = client.get(url)
                status = response.status_code
            except httpx.HTTPError as exc:
                findings.append(_warn("link.unreachable", f"{url}: {exc.__class__.__name__}", project_id))
                continue
            if status >= 400:
                hint = "" if archive else " (no archive_url recorded)"
                findings.append(_warn("link.dead", f"{url} returned {status}{hint}", project_id))
    return findings
