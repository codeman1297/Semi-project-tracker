"""Each test here corresponds to a way a wrong number could otherwise ship."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from ism_tracker.loader import load_dataset
from ism_tracker.models import (
    Dataset,
    FxRate,
    Location,
    Project,
    Provenance,
    Sourced,
    Status,
    StatusEvent,
)
from ism_tracker.validate import validate_dataset

from conftest import MINIMAL_PROJECT, TODAY, write_dataset


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


@pytest.fixture
def project(sourced) -> Project:
    return Project.model_validate(
        dict(
            id="example-fab",
            name="Example Fab",
            company="Example Corp",
            scheme=sourced("ISM_1.0"),
            facility_type=sourced("atmp_osat"),
            location=Location(city="Sanand", state="Gujarat"),
            status=sourced("under_construction"),
            last_verified_at=date(2026, 9, 1),
            verification_owner="operator",
        )
    )


def with_fields(project: Project, **fields) -> Project:
    """Rebuild a project with several fields at once.

    Assignment revalidates one field at a time, which the cross-field rules
    (INR+USD requires fx) correctly reject -- so set them together.
    """
    return Project.model_validate({**project.model_dump(), **fields})


def report_for(project: Project):
    return validate_dataset(Dataset(projects=[project]), TODAY)


def test_a_clean_project_passes(project):
    report = report_for(project)
    assert report.ok
    assert not [f for f in report.warnings if f.project_id == project.id]


def test_inferred_facts_cannot_be_confirmed(project, prov):
    bad = prov.model_copy(update={"source_type": "inferred"})
    project.investment_inr_cr = Sourced(value=22516.0, provenance=bad)
    assert "provenance.contradiction" in codes(report_for(project))


def test_media_only_confirmation_is_flagged(project, prov):
    media = prov.model_copy(update={"source_type": "media", "source_name": "Reuters"})
    project.investment_inr_cr = Sourced(value=22516.0, provenance=media)
    assert "provenance.media_confirmed" in codes(report_for(project))


def test_going_backwards_down_the_ladder_is_an_error(project, prov):
    project.status_history = [
        StatusEvent(date=date(2025, 1, 1), to_status=Status.UNDER_CONSTRUCTION, provenance=prov),
        StatusEvent(
            date=date(2026, 1, 1),
            from_status=Status.UNDER_CONSTRUCTION,
            to_status=Status.LAND_ALLOTTED,
            provenance=prov,
        ),
    ]
    project.status = Sourced(value=Status.LAND_ALLOTTED, provenance=prov)
    assert "status.non_monotonic" in codes(report_for(project))


def test_a_declared_regression_is_allowed(project, prov):
    project.status_history = [
        StatusEvent(date=date(2025, 1, 1), to_status=Status.UNDER_CONSTRUCTION, provenance=prov),
        StatusEvent(
            date=date(2026, 1, 1),
            from_status=Status.UNDER_CONSTRUCTION,
            to_status=Status.STALLED,
            provenance=prov,
        ),
    ]
    project.status = Sourced(value=Status.STALLED, provenance=prov)
    assert "status.non_monotonic" not in codes(report_for(project))


def test_current_status_must_match_the_history(project, prov):
    project.status_history = [
        StatusEvent(date=date(2025, 1, 1), to_status=Status.LAND_ALLOTTED, provenance=prov)
    ]
    assert "status.history_mismatch" in codes(report_for(project))


def test_a_broken_transition_chain_is_caught(project, prov):
    project.status_history = [
        StatusEvent(date=date(2025, 1, 1), to_status=Status.LAND_ALLOTTED, provenance=prov),
        StatusEvent(
            date=date(2026, 1, 1),
            from_status=Status.GROUNDBROKEN,  # never happened
            to_status=Status.UNDER_CONSTRUCTION,
            provenance=prov,
        ),
    ]
    assert "status.history_broken_chain" in codes(report_for(project))


def test_future_dated_events_are_rejected(project, prov):
    project.status_history = [
        StatusEvent(date=date(2027, 1, 1), to_status=Status.UNDER_CONSTRUCTION, provenance=prov)
    ]
    assert "status.future_dated" in codes(report_for(project))


def test_key_dates_must_run_forwards(project, sourced):
    project.key_dates = project.key_dates.model_copy(
        update={
            "approval": sourced(date(2024, 3, 1)),
            "groundbreaking": sourced(date(2023, 9, 1)),
        }
    )
    assert "dates.out_of_order" in codes(report_for(project))


def test_stale_records_are_warned_about(project):
    project.last_verified_at = date(2026, 1, 1)
    assert "stale" in codes(report_for(project))


def test_a_passed_target_produces_a_slip_warning(project, sourced):
    project.key_dates = project.key_dates.model_copy(
        update={"target_first_output": sourced(date(2026, 3, 1))}
    )
    findings = [f for f in report_for(project).findings if f.code == "schedule.slipping"]
    assert findings and "6 month(s)" in findings[0].message


def test_currency_drift_is_flagged(project, sourced):
    project = with_fields(
        project,
        investment_inr_cr=sourced(22516.0),
        investment_usd_mn=sourced(500.0),  # nowhere near the INR figure
        fx=FxRate(usd_inr=83.0, rate_date=date(2024, 2, 29), rate_source="RBI"),
    )
    assert "currency.drift" in codes(report_for(project))


def test_consistent_currency_conversion_passes(project, sourced):
    project = with_fields(
        project,
        investment_inr_cr=sourced(22516.0),
        investment_usd_mn=sourced(2750.0),
        fx=FxRate(usd_inr=81.9, rate_date=date(2023, 6, 28), rate_source="RBI"),
    )
    assert "currency.drift" not in codes(report_for(project))


def test_events_may_not_reference_unknown_projects(project, prov):
    from ism_tracker.models import Event

    event = Event(
        ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
        project_id="ghost-fab",
        field="status",
        kind="status_change",
        provenance=prov,
        applied_by="operator",
    )
    report = validate_dataset(Dataset(projects=[project], events=[event]), TODAY)
    assert "events.unknown_project" in codes(report)
    assert not report.ok


def test_unreconciled_totals_are_surfaced_not_hidden(project):
    assert "reconcile.unset" in codes(report_for(project))


def test_the_seed_file_as_committed_validates(tmp_path):
    """The repo's own data files must always pass -- this is the CI gate in miniature."""
    dataset = load_dataset(write_dataset(tmp_path, MINIMAL_PROJECT))
    assert validate_dataset(dataset, TODAY).ok
