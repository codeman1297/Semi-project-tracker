"""Load the canonical YAML/JSONL files into validated models.

Kept separate from :mod:`ism_tracker.db` on purpose: this module is the only way
into the data model and is used by every command, while ``db.py`` is one
consumer of it (YAML -> SQLite materialisation).

**The `src:` shorthand.** Writing a full provenance block next to every field
would make ``projects.yaml`` unreadable and unmaintainable by hand, which would
in practice mean provenance gets skipped. So a file may define a ``refs`` block
of named citations, and any sourced field may cite one by name::

    refs:
      pib-2024-02-29:
        source_url: https://pib.gov.in/PressReleasePage.aspx?PRID=2010650
        source_name: PIB
        source_type: primary_govt
        retrieved_at: 2026-09-08T00:00:00Z
        confidence: confirmed

    projects:
      - id: micron-sanand-atmp
        investment_inr_cr: {value: 22516, src: pib-2024-02-29}

Refs resolve project-local first, then file-global. Expansion happens here,
before Pydantic sees the data, so the models stay simple and the YAML stays
diffable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .config import DEFAULT_PATHS, Paths
from .models import Company, Dataset, Event, Project, Source


class DataError(Exception):
    """Raised for malformed input files -- always with the file and record named."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message passthrough
        raise DataError(f"{path.name}: invalid YAML: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise DataError(f"{path.name}: expected a mapping at the top level")
    return loaded


def expand_refs(node: Any, refs: dict[str, Any], *, where: str) -> Any:
    """Recursively replace ``src: <name>`` with the named provenance block."""
    if isinstance(node, list):
        return [expand_refs(item, refs, where=where) for item in node]
    if not isinstance(node, dict):
        return node

    out = {k: expand_refs(v, refs, where=where) for k, v in node.items() if k != "src"}
    if "src" in node:
        name = node["src"]
        if "provenance" in node:
            raise DataError(f"{where}: has both `src: {name}` and an inline `provenance`")
        if not isinstance(name, str) or name not in refs:
            known = ", ".join(sorted(refs)) or "(none defined)"
            raise DataError(f"{where}: unknown source ref `{name}`. Known refs: {known}")
        out["provenance"] = refs[name]
    return out


def _load_projects(path: Path) -> list[Project]:
    raw = _read_yaml(path)
    global_refs: dict[str, Any] = raw.get("refs") or {}
    records = raw.get("projects") or []
    if not isinstance(records, list):
        raise DataError(f"{path.name}: `projects` must be a list")

    projects: list[Project] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DataError(f"{path.name}[{index}]: each project must be a mapping")
        pid = record.get("id", f"index {index}")
        local_refs = record.get("refs") or {}
        refs = {**global_refs, **local_refs}
        payload = {k: v for k, v in record.items() if k != "refs"}
        expanded = expand_refs(payload, refs, where=f"{path.name}:{pid}")
        try:
            project = Project.model_validate(expanded)
        except ValidationError as exc:
            raise DataError(f"{path.name}:{pid}: {_fmt(exc)}") from exc
        if project.id in seen:
            raise DataError(f"{path.name}: duplicate project id `{project.id}`")
        seen.add(project.id)
        projects.append(project)
    return projects


def _load_simple(path: Path, key: str, model: type) -> list[Any]:
    raw = _read_yaml(path)
    records = raw.get(key) or []
    if not isinstance(records, list):
        raise DataError(f"{path.name}: `{key}` must be a list")
    out = []
    for index, record in enumerate(records):
        try:
            out.append(model.model_validate(record))
        except ValidationError as exc:
            ident = record.get("id", index) if isinstance(record, dict) else index
            raise DataError(f"{path.name}:{ident}: {_fmt(exc)}") from exc
    return out


def load_events(path: Path) -> list[Event]:
    if not path.exists():
        return []
    events: list[Event] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            events.append(Event.model_validate(json.loads(line)))
        except json.JSONDecodeError as exc:
            raise DataError(f"{path.name}:{lineno}: invalid JSON: {exc.msg}") from exc
        except ValidationError as exc:
            raise DataError(f"{path.name}:{lineno}: {_fmt(exc)}") from exc
    return events


def append_event(event: Event, path: Path | None = None) -> None:
    """Append-only by construction: we open in 'a' and never rewrite the file."""
    path = path or DEFAULT_PATHS.events
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json() + "\n")


def load_dataset(paths: Paths | None = None) -> Dataset:
    paths = paths or DEFAULT_PATHS
    return Dataset(
        projects=_load_projects(paths.projects),
        companies=_load_simple(paths.companies, "companies", Company),
        sources=_load_simple(paths.sources, "sources", Source),
        events=load_events(paths.events),
    )


def _fmt(exc: ValidationError) -> str:
    """Pydantic errors, rendered for a human editing YAML on a phone."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"{loc}: {err['msg']}")
    return "; ".join(lines)
