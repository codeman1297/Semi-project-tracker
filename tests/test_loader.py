"""Loading is where hand-edited YAML meets the schema; errors must name the record."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ism_tracker.loader import DataError, append_event, load_dataset, load_events
from ism_tracker.models import Event, Scheme, Status

from conftest import MINIMAL_PROJECT, write_dataset


def test_src_shorthand_expands_to_full_provenance(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path, MINIMAL_PROJECT))
    project = dataset.project("example-fab")
    assert project.scheme.value is Scheme.ISM_1_0
    assert project.scheme.provenance.source_name == "PIB"
    assert project.status.value is Status.UNDER_CONSTRUCTION


def test_project_local_refs_shadow_global_ones(tmp_path):
    yaml_text = MINIMAL_PROJECT.replace(
        "  - id: example-fab\n",
        "  - id: example-fab\n"
        "    refs:\n"
        "      pib:\n"
        "        source_url: https://www.micron.com/press\n"
        "        source_name: Micron IR\n"
        "        source_type: primary_company\n"
        "        retrieved_at: 2026-09-01T00:00:00Z\n"
        "        confidence: reported\n",
    )
    project = load_dataset(write_dataset(tmp_path, yaml_text)).project("example-fab")
    assert project.scheme.provenance.source_name == "Micron IR"


def test_unknown_ref_is_a_named_error(tmp_path):
    yaml_text = MINIMAL_PROJECT.replace("src: pib}", "src: nope}", 1)
    with pytest.raises(DataError, match="unknown source ref `nope`"):
        load_dataset(write_dataset(tmp_path, yaml_text))


def test_src_and_inline_provenance_together_is_an_error(tmp_path):
    yaml_text = MINIMAL_PROJECT.replace(
        "    status: {value: under_construction, src: pib}\n",
        "    status:\n"
        "      value: under_construction\n"
        "      src: pib\n"
        "      provenance:\n"
        "        source_url: https://example.com/x\n"
        "        source_name: Other\n"
        "        source_type: media\n"
        "        retrieved_at: 2026-09-01T00:00:00Z\n"
        "        confidence: reported\n",
    )
    with pytest.raises(DataError, match="inline `provenance`"):
        load_dataset(write_dataset(tmp_path, yaml_text))


def test_duplicate_ids_are_rejected(tmp_path):
    doubled = MINIMAL_PROJECT + MINIMAL_PROJECT.split("projects:")[1]
    with pytest.raises(DataError, match="duplicate project id"):
        load_dataset(write_dataset(tmp_path, doubled))


def test_validation_errors_name_the_project_and_field(tmp_path):
    yaml_text = MINIMAL_PROJECT.replace("value: atmp_osat", "value: osat_atmp")
    with pytest.raises(DataError, match="example-fab.*facility_type"):
        load_dataset(write_dataset(tmp_path, yaml_text))


def test_empty_files_load_as_an_empty_dataset(tmp_path):
    dataset = load_dataset(write_dataset(tmp_path, "projects: []"))
    assert dataset.projects == [] and dataset.events == []


def test_events_round_trip_and_append(tmp_path, prov):
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")
    event = Event(
        ts=datetime(2026, 9, 1, tzinfo=timezone.utc),
        project_id="example-fab",
        field="status",
        old_value="land_allotted",
        new_value="under_construction",
        kind="status_change",
        provenance=prov,
        applied_by="operator",
    )
    append_event(event, path)
    append_event(event, path)
    assert len(load_events(path)) == 2
    assert json.loads(path.read_text().splitlines()[0])["field"] == "status"


def test_a_corrupt_event_line_names_its_line_number(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(DataError, match="events.jsonl:1"):
        load_events(path)


def test_headline_totals_exclude_adjacent_entries(tmp_path):
    yaml_text = MINIMAL_PROJECT + """
  - id: legacy-fab
    name: Legacy Fab
    company: Example Corp
    adjacent: true
    scheme: {value: Non-scheme, src: pib}
    facility_type: {value: logic_fab, src: pib}
    location: {state: Punjab}
    status: {value: commercial_production, src: pib}
    last_verified_at: 2026-09-01
    verification_owner: operator
"""
    dataset = load_dataset(write_dataset(tmp_path, yaml_text))
    assert len(dataset.projects) == 2
    assert [p.id for p in dataset.headline_projects] == ["example-fab"]


def test_every_field_shape_round_trips(tmp_path):
    """One record exercising every field type, including `src` refs nested inside
    capacity and superseded values. Guards the seeding work in build step 2."""
    from pathlib import Path

    from ism_tracker.config import Paths
    from ism_tracker.models import FacilityType

    fixture = Path(__file__).parent / "fixtures" / "full_shape_project.yaml"
    (tmp_path / "companies.yaml").write_text("companies: []", encoding="utf-8")
    (tmp_path / "sources.yaml").write_text("sources: []", encoding="utf-8")
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    dataset = load_dataset(
        Paths(
            projects=fixture,
            companies=tmp_path / "companies.yaml",
            sources=tmp_path / "sources.yaml",
            events=tmp_path / "events.jsonl",
        )
    )
    project = dataset.project("shape-test-fab")
    assert project.facility_type.value is FacilityType.LOGIC_FAB
    assert project.capacity.value.unit == "wafer starts per month"
    assert project.capacity.provenance.source_name == "PIB"
    assert project.investment_inr_cr.superseded[0].value == 90000.0
    assert project.investment_inr_cr.superseded[0].provenance.source_name == "Business Standard"
    assert project.jv_partners.value == ["PSMC", "Someone Else"]
    assert [e.to_status.value for e in project.status_history] == [
        "cabinet_approved",
        "groundbroken",
        "under_construction",
    ]
    assert project.last_ladder_status is Status.UNDER_CONSTRUCTION
