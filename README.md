# India Semiconductor Project Tracker

A public, regularly-updated record of every semiconductor manufacturing project
approved under **India's Semiconductor Mission (ISM)** and adjacent schemes
(SPECS, state policies) — what was approved, where, for how much, and how far it
has actually got.

Three surfaces, one dataset:

| Surface | What it is |
| --- | --- |
| **Dataset** | `data/*.yaml` — canonical, hand-editable, version-controlled. The source of truth. |
| **Dashboard** | A static site built from that data. No backend, no JS framework, free to host. |
| **Weekly digest** | A newsletter + LinkedIn post generated from the change log, reporting only what actually changed. |

The dataset is published under **CC BY 4.0**. Take it, cite it.

## The one rule

**No number without a source.** Every factual field is wrapped in a `Sourced[T]`
that cannot be constructed without provenance — a URL, the kind of source, when
we retrieved it, and how confident we are. A field we cannot source has no value
at all; it renders as an em dash. In this domain a wrong number destroys
credibility faster than a missing number gains it.

The second rule follows from the first: **nothing is applied automatically.**
The ingest pipeline proposes; a human accepts. See *Weekly routine* below.

## Quick start

```bash
uv sync                    # or: pip install -e '.[dev]'
uv run ism-tracker validate
uv run ism-tracker stats
```

`validate` is the gate. It runs in CI and blocks merge on any error.

## Commands

| Command | What it does | Built in step |
| --- | --- | --- |
| `ism-tracker validate [--strict] [--check-links]` | Schema, provenance and consistency checks | 1 ✅ |
| `ism-tracker stats` | Field coverage, staleness, slipping timelines | 1 ✅ |
| `ism-tracker build-site` | Render the static site into `site/` | 3 |
| `ism-tracker serve` | Preview the built site on `:8000` | 3 |
| `ism-tracker ingest [--source NAME] [--llm] [--since DATE]` | Poll sources, propose changes into `review/pending.md` | 4 |
| `ism-tracker apply --from review/pending.md` | Apply the changes you ticked | 4 |
| `ism-tracker digest --since 7d` | Weekly newsletter + LinkedIn post | 5 |

Unbuilt commands exit non-zero and name the step that brings them, rather than
silently doing nothing.

## Build status

- [x] **1.** Skeleton, schema (`models.py`), `validate`, `stats`, tests
- [ ] **2.** `projects.yaml` seeded and verified against primary sources
- [ ] **3.** SQLite materialisation + static site (deployable MVP)
- [ ] **4.** Ingestion + rules extractor + review queue
- [ ] **5.** Weekly digest
- [ ] **6.** GitHub Actions (daily ingest PR, publish on merge)
- [ ] **7.** Optional LLM enrichment behind `--llm`
- [ ] **8.** Map, changes feed, methodology page, data downloads

## Weekly routine (target: under 30 minutes)

Once step 4 lands, the daily CI job opens a PR titled
`Ingest YYYY-MM-DD: N candidate changes`. The whole week's work is:

1. **Open the ingest PR** (phone is fine). It contains only `review/pending.md`.
2. **For each proposed change**, click the evidence link and read the sentence it
   points at. Tick the box if the source genuinely says it. Leave it unticked if
   it doesn't, or if the source is a news report repeating a rumour — you can
   downgrade `confidence` to `reported` instead of rejecting outright.
3. **Merge the PR.** CI runs `apply`, which writes the accepted changes into
   `projects.yaml`, appends to `events.jsonl`, and rebuilds the site.
4. **Run `ism-tracker stats`.** Anything listed as stale (unverified > 60 days)
   gets five minutes of checking — usually one search — and its
   `last_verified_at` bumped.
5. **Run `ism-tracker digest --since 7d`.** Write the one `TODO: what this means`
   paragraph it leaves for you. Paste `out/digest-*.md` into your newsletter
   provider and `out/linkedin-*.txt` into LinkedIn.

If nothing changed, the digest says so plainly. Publish it anyway — a tracker
that reports "no movement this week" is more trustworthy than one that pads.

## How to add a source

1. Add an entry to `data/sources.yaml`:

   ```yaml
   sources:
     - id: gujarat-dst
       name: Gujarat Dept. of Science & Technology
       url: https://dst.gujarat.gov.in/press-releases
       type: state_govt          # pib | ism_site | rss | company | state_govt | html
       source_type: primary_govt # how much weight its claims carry
       poll_frequency: weekly
   ```
2. If it needs a fetcher that doesn't exist yet, add one in
   `src/ism_tracker/ingest/` implementing `Fetcher.fetch() -> list[RawDoc]`.
   Most sites are covered by the generic `rss` or `html` fetchers.
3. Run `ism-tracker ingest --source gujarat-dst` and read `review/pending.md`.

Fetchers respect `robots.txt`, send a descriptive User-Agent with a contact URL,
and rate-limit to one request per two seconds per domain. Do not lower that.

## How to correct an error

Corrections are a feature, not an embarrassment — the correction log is what
makes the rest of the numbers believable.

1. Open an issue, or email the address on the `/methodology` page, with the
   field, what it should say, and a link to the source.
2. To fix it yourself: edit `data/projects.yaml`, but **do not overwrite the old
   value** — move it into the field's `superseded` list with a reason:

   ```yaml
   investment_inr_cr:
     value: 22516
     src: pib-2024-02-29
     superseded:
       - value: 22540
         provenance: {...}
         superseded_on: 2026-09-08
         reason: "PIB corrected the figure in its 2024-03-02 clarification"
   ```
3. Run `ism-tracker validate` and open a PR. The change appears on `/changes/`
   with its evidence, tagged as a correction.

## Repository layout

```
data/            canonical YAML + append-only events.jsonl   <- edit this
src/ism_tracker/ models, loader, validation, ingest, site, digest
review/          pending.md — the human review queue
docs/            DATA_DICTIONARY.md — every field, in plain English
tests/           pytest, with real source text in tests/fixtures/
site/            build output (gitignored)
```

## Licence

Code: MIT. Data: CC BY 4.0.
