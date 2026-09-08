"""The schema is the contract; these tests pin the parts of it that matter."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from ism_tracker.models import (
    LADDER,
    REGRESSIONS,
    Capacity,
    FxRate,
    Location,
    Project,
    Provenance,
    Sourced,
    Status,
    StatusEvent,
    hash_quote,
    ladder_rank,
)

from conftest import TODAY


def _project(sourced, **overrides) -> Project:
    payload = dict(
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
    payload.update(overrides)
    return Project.model_validate(payload)


class TestProvenance:
    def test_a_value_cannot_exist_without_a_source(self, prov):
        with pytest.raises(ValidationError):
            Sourced(value=22516)  # type: ignore[call-arg]
        assert Sourced(value=22516, provenance=prov).confidence == "confirmed"

    def test_naive_timestamps_are_treated_as_utc(self):
        prov = Provenance(
            source_url="https://pib.gov.in/x",
            source_name="PIB",
            source_type="primary_govt",
            retrieved_at=datetime(2026, 9, 1),
            confidence="reported",
        )
        assert prov.retrieved_at.tzinfo is timezone.utc

    def test_quote_hash_is_whitespace_stable(self):
        assert hash_quote("Rs 22,516  crore\n investment") == hash_quote("Rs 22,516 crore investment")

    def test_quote_hash_must_look_like_a_sha256(self, prov):
        with pytest.raises(ValidationError):
            prov.model_copy(update={}).model_validate(
                {**prov.model_dump(mode="json"), "quote_hash": "not-a-hash"}
            )

    def test_typos_in_yaml_are_rejected_rather_than_ignored(self, prov):
        with pytest.raises(ValidationError):
            Provenance.model_validate({**prov.model_dump(mode="json"), "sourse_name": "PIB"})


class TestLadder:
    def test_ladder_is_ordered_and_excludes_conditions(self):
        assert ladder_rank(Status.ANNOUNCED) == 0
        assert ladder_rank(Status.COMMERCIAL_PRODUCTION) == len(LADDER) - 1
        for condition in REGRESSIONS:
            assert ladder_rank(condition) is None

    def test_last_ladder_status_remembers_the_rung_below_a_condition(self, sourced, prov):
        project = _project(
            sourced,
            status=sourced("stalled"),
            status_history=[
                StatusEvent(date=date(2024, 3, 1), to_status=Status.CABINET_APPROVED, provenance=prov),
                StatusEvent(
                    date=date(2025, 1, 1),
                    from_status=Status.CABINET_APPROVED,
                    to_status=Status.UNDER_CONSTRUCTION,
                    provenance=prov,
                ),
                StatusEvent(
                    date=date(2026, 5, 1),
                    from_status=Status.UNDER_CONSTRUCTION,
                    to_status=Status.STALLED,
                    provenance=prov,
                ),
            ],
        )
        assert project.last_ladder_status is Status.UNDER_CONSTRUCTION

    def test_status_history_must_be_in_date_order(self, sourced, prov):
        with pytest.raises(ValidationError, match="date order"):
            _project(
                sourced,
                status_history=[
                    StatusEvent(date=date(2026, 1, 1), to_status=Status.LAND_ALLOTTED, provenance=prov),
                    StatusEvent(date=date(2025, 1, 1), to_status=Status.GROUNDBROKEN, provenance=prov),
                ],
            )


class TestDerivedDelay:
    def test_slip_is_computed_not_stored(self, sourced):
        project = _project(
            sourced,
            key_dates={"target_first_output": sourced(date(2026, 3, 1))},
        )
        assert project.slip_months(TODAY) == 6

    def test_a_producing_project_is_never_slipping(self, sourced):
        project = _project(
            sourced,
            status=sourced("commercial_production"),
            key_dates={"target_first_output": sourced(date(2026, 3, 1))},
        )
        assert project.slip_months(TODAY) is None

    def test_no_target_date_means_no_claim_about_lateness(self, sourced):
        assert _project(sourced).slip_months(TODAY) is None

    def test_a_future_target_is_not_a_slip(self, sourced):
        project = _project(sourced, key_dates={"target_first_output": sourced(date(2027, 1, 1))})
        assert project.slip_months(TODAY) is None


class TestUnitsAndCurrency:
    def test_capacity_units_are_stored_as_stated(self, sourced):
        project = _project(
            sourced,
            capacity=sourced(Capacity(value=48000, unit="wafer starts per month", basis="phase 1")),
        )
        assert project.capacity.value.unit == "wafer starts per month"

    def test_two_currencies_require_a_recorded_rate(self, sourced):
        with pytest.raises(ValidationError, match="fx"):
            _project(sourced, investment_inr_cr=sourced(22516.0), investment_usd_mn=sourced(2750.0))

    def test_recording_the_rate_satisfies_the_rule(self, sourced):
        project = _project(
            sourced,
            investment_inr_cr=sourced(22516.0),
            investment_usd_mn=sourced(2750.0),
            fx=FxRate(usd_inr=81.9, rate_date=date(2023, 6, 28), rate_source="RBI reference rate"),
        )
        assert project.fx.usd_inr == 81.9


class TestIdentityAndGeography:
    def test_ids_are_slugs(self, sourced):
        with pytest.raises(ValidationError):
            _project(sourced, id="Micron Sanand ATMP")

    def test_coordinates_come_in_pairs(self):
        with pytest.raises(ValidationError, match="together"):
            Location(state="Gujarat", lat=22.9)

    def test_staleness_uses_the_configured_window(self, sourced):
        project = _project(sourced, last_verified_at=date(2026, 6, 1))
        assert project.is_stale(TODAY, max_age_days=60) is True
        assert project.is_stale(TODAY, max_age_days=365) is False
