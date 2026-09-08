"""Smoke tests: the commands exist, and unbuilt ones say so instead of lying."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ism_tracker.cli import app, parse_since

runner = CliRunner()


def test_help_lists_every_planned_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("ingest", "apply", "validate", "build-site", "digest", "stats", "serve"):
        assert command in result.stdout


def test_validate_runs_against_the_committed_data_files():
    result = runner.invoke(app, ["validate", "--today", "2026-09-08"])
    assert result.exit_code == 0, result.stdout
    assert "validate: OK" in result.stdout


def test_stats_reports_an_empty_dataset_plainly():
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "build step 2" in result.stdout


@pytest.mark.parametrize("command", ["ingest", "build-site", "digest", "serve"])
def test_unbuilt_commands_fail_loudly(command):
    result = runner.invoke(app, [command])
    assert result.exit_code == 1
    assert "not implemented yet" in result.stdout


@pytest.mark.parametrize("value,delta_hours", [("7d", 168), ("24h", 24)])
def test_parse_since_accepts_shorthand(value, delta_hours):
    from datetime import datetime, timezone

    parsed = parse_since(value)
    hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600
    assert abs(hours - delta_hours) < 1


def test_parse_since_rejects_nonsense():
    import typer

    with pytest.raises(typer.BadParameter):
        parse_since("last tuesday")
