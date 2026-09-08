"""`ism-tracker` command line.

Commands land here in build order. Anything not yet built exits non-zero with the
step that will bring it, rather than pretending to succeed.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import typer

from . import config
from .loader import DataError, load_dataset
from .models import FACTUAL_FIELDS, Sourced
from .validate import Report, check_links, validate_dataset

app = typer.Typer(
    name="ism-tracker",
    help="Tracker of semiconductor manufacturing projects approved under India's "
    "Semiconductor Mission (ISM) and adjacent schemes.",
    no_args_is_help=True,
    add_completion=False,
)


def _echo(message: str = "") -> None:
    typer.echo(message)


def _load():
    try:
        return load_dataset()
    except DataError as exc:
        _echo(f"error: {exc}")
        raise typer.Exit(code=2)


def _not_yet(step: str) -> None:
    _echo(f"not implemented yet -- arrives in build step {step}.")
    raise typer.Exit(code=1)


def parse_since(value: str) -> datetime:
    """Accept `7d`, `24h`, or an ISO date."""
    value = value.strip()
    now = datetime.now(timezone.utc)
    if value.endswith("d") and value[:-1].isdigit():
        return now - timedelta(days=int(value[:-1]))
    if value.endswith("h") and value[:-1].isdigit():
        return now - timedelta(hours=int(value[:-1]))
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise typer.BadParameter(f"could not read `{value}`; use 7d, 24h or YYYY-MM-DD") from exc


# --------------------------------------------------------------------------- #


@app.command()
def validate(
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
    links: bool = typer.Option(
        False, "--check-links", help="Also check that every source URL still resolves (needs network)."
    ),
    today: str | None = typer.Option(
        None, "--today", help="Override today's date (YYYY-MM-DD), for reproducible tests."
    ),
) -> None:
    """Schema, provenance and internal-consistency checks. Blocks merge in CI."""
    dataset = _load()
    as_of = date.fromisoformat(today) if today else date.today()
    report: Report = validate_dataset(dataset, as_of)
    if links:
        report.findings.extend(check_links(dataset))

    for finding in report.findings:
        _echo(str(finding))

    _echo()
    _echo(
        f"{report.checked_projects} project(s) checked: "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    if report.errors or (strict and report.warnings):
        raise typer.Exit(code=1)
    _echo("validate: OK")


@app.command()
def stats() -> None:
    """Coverage report: how much of the dataset is actually sourced, and how stale."""
    dataset = _load()
    projects = dataset.projects
    if not projects:
        _echo("no projects yet -- seed data/projects.yaml (build step 2).")
        raise typer.Exit(code=0)

    today = date.today()
    total_slots = len(projects) * len(FACTUAL_FIELDS)
    filled = sum(
        1
        for p in projects
        for f in FACTUAL_FIELDS
        if isinstance(getattr(p, f, None), Sourced)
    )
    by_confidence: dict[str, int] = {}
    for p in projects:
        for f in FACTUAL_FIELDS:
            value = getattr(p, f, None)
            if isinstance(value, Sourced):
                by_confidence[value.confidence] = by_confidence.get(value.confidence, 0) + 1

    _echo(f"projects            {len(projects)} ({len(dataset.headline_projects)} headline, "
          f"{len(projects) - len(dataset.headline_projects)} adjacent)")
    _echo(f"field coverage      {filled}/{total_slots} ({filled / total_slots:.0%}) of factual fields sourced")
    for level in ("confirmed", "reported", "unconfirmed"):
        count = by_confidence.get(level, 0)
        _echo(f"  {level:<16}{count}")
    _echo(f"events logged       {len(dataset.events)}")
    _echo(f"sources registered  {len(dataset.sources)}")

    stale = sorted(
        (p for p in projects if p.is_stale(today, config.STALE_AFTER_DAYS)),
        key=lambda p: p.last_verified_at,
    )
    _echo(f"stale (> {config.STALE_AFTER_DAYS}d)      {len(stale)}")
    for p in stale[:10]:
        _echo(f"  {p.id:<32} last verified {p.last_verified_at} "
              f"({(today - p.last_verified_at).days}d ago, owner {p.verification_owner})")

    slipping = [(p, p.slip_months(today)) for p in projects]
    slipping = [(p, m) for p, m in slipping if m]
    if slipping:
        _echo(f"slipping timelines  {len(slipping)}")
        for p, months in sorted(slipping, key=lambda pair: -pair[1]):
            _echo(f"  {p.id:<32} {months} month(s) past {p.target_date}")


@app.command()
def ingest(
    source: str | None = typer.Option(None, "--source", help="Only poll this source id."),
    llm: bool = typer.Option(False, "--llm", help="Enable optional LLM extraction for the messy remainder."),
    since: str | None = typer.Option(None, "--since", help="Only consider documents published since (7d, YYYY-MM-DD)."),
) -> None:
    """Fetch sources, filter for relevance, and queue candidate changes for review."""
    _not_yet("4")


@app.command()
def apply(
    from_file: Path = typer.Option(config.PENDING_MD, "--from", help="Reviewed checklist to apply."),
) -> None:
    """Apply the changes you ticked in review/pending.md. Never runs automatically."""
    _not_yet("4")


@app.command("build-site")
def build_site() -> None:
    """Render the static site into ./site."""
    _not_yet("3")


@app.command()
def digest(
    since: str = typer.Option("7d", "--since", help="Window to diff (7d, 24h, YYYY-MM-DD)."),
) -> None:
    """Generate the weekly newsletter and LinkedIn post from events.jsonl."""
    _not_yet("5")


@app.command()
def serve(
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Preview the built site locally."""
    _not_yet("3")


def main() -> None:  # pragma: no cover - console-script shim
    try:
        app()
    except DataError as exc:
        _echo(f"error: {exc}")
        sys.exit(2)


if __name__ == "__main__":  # pragma: no cover
    main()
