from __future__ import annotations

import sys
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ism_tracker.config import Paths  # noqa: E402
from ism_tracker.models import Provenance, Sourced  # noqa: E402

TODAY = date(2026, 9, 8)


@pytest.fixture
def prov() -> Provenance:
    return Provenance(
        source_url="https://pib.gov.in/PressReleasePage.aspx?PRID=1234567",
        source_name="PIB",
        source_type="primary_govt",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        confidence="confirmed",
    )


@pytest.fixture
def sourced(prov):
    def _make(value):
        return Sourced(value=value, provenance=prov)

    return _make


def write_dataset(tmp_path: Path, projects_yaml: str, *, companies: str = "companies: []",
                  sources: str = "sources: []", events: str = "") -> Paths:
    """Materialise a throwaway data directory and return Paths pointing at it."""
    (tmp_path / "projects.yaml").write_text(textwrap.dedent(projects_yaml), encoding="utf-8")
    (tmp_path / "companies.yaml").write_text(textwrap.dedent(companies), encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(textwrap.dedent(sources), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text(events, encoding="utf-8")
    return Paths(
        projects=tmp_path / "projects.yaml",
        companies=tmp_path / "companies.yaml",
        sources=tmp_path / "sources.yaml",
        events=tmp_path / "events.jsonl",
    )


MINIMAL_PROJECT = """
refs:
  pib:
    source_url: https://pib.gov.in/PressReleasePage.aspx?PRID=1234567
    source_name: PIB
    source_type: primary_govt
    retrieved_at: 2026-09-01T00:00:00Z
    confidence: confirmed

projects:
  - id: example-fab
    name: Example Fab
    company: Example Corp
    scheme: {value: ISM_1.0, src: pib}
    facility_type: {value: atmp_osat, src: pib}
    location: {city: Sanand, state: Gujarat}
    status: {value: under_construction, src: pib}
    last_verified_at: 2026-09-01
    verification_owner: operator
"""
