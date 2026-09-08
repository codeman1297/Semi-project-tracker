# Data dictionary

Every field in the dataset, in plain English. This doubles as the public
methodology page: if you cite a number from this tracker, this document tells you
exactly what it means and how much weight it carries.

Defined in code at `src/ism_tracker/models.py`. If the two ever disagree, the
code is right and this file is a bug.

---

## 1. Provenance — attached to every fact

A fact without a source is not published. Every factual field carries:

| Field | Meaning |
| --- | --- |
| `source_url` | The exact page the claim came from. |
| `source_name` | Who published it — "PIB", "MeitY", "Micron IR", "Reuters". |
| `source_type` | How direct the source is. See below. |
| `retrieved_at` | When we read it. Pages change; this is what we read, when. |
| `published_at` | The date on the source document, if it has one. |
| `confidence` | How much weight the claim carries. See below. |
| `quote_hash` | SHA-256 of the supporting sentence, whitespace-normalised. Proves we read a specific line without republishing the text. |
| `archive_url` | An archive.org fallback, for when the original link rots. |
| `note` | Anything a reader needs to interpret the citation. |

### `source_type`

| Value | Meaning |
| --- | --- |
| `primary_govt` | The government body that made or approved the decision — PIB, MeitY, ISM, a state industry department. Strongest. |
| `primary_company` | The company itself — a press release, investor presentation, annual report. |
| `media` | A news outlet reporting on it. Useful, but second-hand. |
| `inferred` | We worked it out from other sourced facts. Always the weakest, and can never be `confirmed`. |

### `confidence`

| Value | Meaning |
| --- | --- |
| `confirmed` | Stated directly by a primary source. A number tagged `confirmed` is one you can quote. |
| `reported` | Reported by credible media, or stated by a primary source with hedging ("expected to", "up to"). |
| `unconfirmed` | We have seen the claim but cannot stand behind it. Shown, but visibly marked. |

`inferred` + `confirmed` is a contradiction and fails validation. `media` +
`confirmed` produces a warning — prefer finding the primary source.

### `superseded`

Values are never overwritten. When a fact changes, the old value moves into the
field's `superseded` list along with the date and the reason. The full history is
public at `/changes/`. This is deliberate: a tracker whose numbers quietly change
is indistinguishable from one that makes them up.

---

## 2. Project fields

### Identity

| Field | Meaning |
| --- | --- |
| `id` | Permanent slug, e.g. `micron-sanand-atmp`. Never changes, never reused — external links depend on it. |
| `name` | The project's name as commonly used. |
| `company` | The entity building and operating it. |
| `parent_company` | Its corporate parent, where relevant (e.g. Tata Sons behind Tata Electronics). |
| `jv_partners` | Technology or equity partners named in the approval (e.g. PSMC for Tata Dholera). |
| `adjacent` | `true` for entries tracked for context but **not** ISM manufacturing approvals — SPECS units, legacy government fabs. Excluded from headline totals so our numbers reconcile with the government's. |

### Scheme and type

`scheme` — which policy approved it:

| Value | Meaning |
| --- | --- |
| `ISM_1.0` | Approved under the first ₹76,000 crore India Semiconductor Mission tranche. |
| `ISM_2.0` | Approved under the second tranche. |
| `SPECS` | Scheme for Promotion of Manufacturing of Electronic Components and Semiconductors — components, not ISM fabs/ATMPs. |
| `State` | Approved under a state semiconductor policy without a central ISM approval. |
| `Non-scheme` | Neither — included for completeness (e.g. a legacy government fab). |

`facility_type` — what is actually being built:

| Value | Meaning |
| --- | --- |
| `logic_fab` | Silicon wafer fabrication for logic chips. |
| `compound_fab` | Compound semiconductors (GaN, GaAs) other than SiC. |
| `sic_fab` | Silicon carbide fabrication. |
| `display_fab` | Display or display-driver fabrication, including micro-LED. |
| `atmp_osat` | Assembly, Testing, Marking and Packaging / outsourced assembly and test. Packages chips; does not make wafers. |
| `substrate` | Substrates, interposers, glass carriers — inputs to packaging. |
| `other` | Anything that fits none of the above; see `notes_md`. |

**ATMP vs OSAT:** the same activity. ATMP is the term used in Indian scheme
documents; OSAT is the global industry term. We treat them as one category and
say which the source used in the notes.

### Location

`city`, `district`, `state`, `cluster` (e.g. "Dholera SIR", "Sanand GIDC"),
`lat`, `lon`. Only `state` is mandatory — it drives the map. Coordinates are
given as a pair or not at all.

### Money

| Field | Meaning |
| --- | --- |
| `investment_inr_cr` | Total announced investment, in ₹ crore (1 crore = 10 million). The figure as stated by the source — usually total project cost, not the government's subsidy share. |
| `investment_usd_mn` | The same figure in US$ million, **only** when a source states it. |
| `fx` | The rate, date and rate source used, mandatory whenever both currency figures are present. |

We do not convert currencies silently. If both figures appear and imply rates
more than 10% apart, validation warns — usually because they were announced years
apart at different exchange rates.

### Capacity

`value`, `unit`, `basis` — **stored exactly as stated, never normalised.**

Official releases use wafer starts per month, chips per day, million units per
year and modules per year, sometimes for neighbouring projects. Converting
between them requires assumptions about die size and yield that nobody publishes.
Normalising would manufacture a false comparison, so we render the unit next to
every number and let you do the arithmetic knowingly. `basis` records the caveat:
"phase 1", "at full capacity", "design capacity".

### Technology and output

`technology_node` (e.g. "28nm and above"), `products` (what it makes),
`end_markets` (automotive, telecom, consumer, defence).

### Status ladder

`status` is where the project is now. The first nine values are **ordered rungs**;
progress up them is monotonic, and validation rejects any backwards move that
isn't a declared regression.

| Rung | Meaning |
| --- | --- |
| `announced` | Publicly announced or applied for. No approval yet. |
| `cabinet_approved` | Approved by the Union Cabinet / ISM. The moment it becomes real policy. |
| `fsa_signed` | Fiscal Support Agreement signed with the government — subsidy terms locked. |
| `land_allotted` | Site formally allotted by the state. |
| `groundbroken` | Ceremonial or actual start of construction (*bhoomi pujan*). |
| `under_construction` | Physical construction under way. |
| `equipment_install` | Building substantially complete; tools being installed. |
| `pilot_production` | Producing engineering or qualification lots, not selling at volume. |
| `commercial_production` | Selling output commercially. The finish line. |

Three further values are **conditions, not rungs** — a project in one of them is
still physically somewhere on the ladder, and `last_ladder_status` records where:

| Condition | Meaning |
| --- | --- |
| `delayed` | Officially acknowledged as behind schedule. |
| `stalled` | No visible progress for an extended period, or reported paused. |
| `cancelled` | Abandoned or approval withdrawn. |

**Groundbreaking is not construction.** A *bhoomi pujan* with a photo op is
`groundbroken`; steel going up is `under_construction`. We keep them separate
because the gap between them is often the most informative number in the table.

`status_history` records every transition with its date and source — the
timeline on each project page is generated from it.

### Dates

`key_dates` holds `approval`, `groundbreaking`, `target_first_output` and
`target_full_production`. Each is sourced independently, because targets are
usually announced by different people at different times.

**"Delayed" is computed, not typed in.** A project is shown as slipping when its
nearest published target date has passed and it has not reached
`pilot_production`. The slip is displayed in months. Nobody issues a press
release announcing they are late, so waiting for one would mean never reporting
a delay.

### Employment

`employment_direct`, `employment_indirect` — as announced. Indirect job figures
are estimates by whoever announced them and should be read as such; they are
almost always sourced at `reported`, not `confirmed`.

### Housekeeping

| Field | Meaning |
| --- | --- |
| `last_verified_at` | When a human last checked this record end to end. |
| `verification_owner` | Who did. |
| `notes_md` | Free-text context, Markdown. Caveats live here. |

A record unverified for more than **60 days** is flagged stale by
`ism-tracker validate` and `ism-tracker stats`. Stale does not mean wrong; it
means nobody has recently confirmed it is still right.

---

## 3. The change log (`events.jsonl`)

Append-only. One JSON object per applied change, written by `ism-tracker apply`
and never edited by hand.

| Field | Meaning |
| --- | --- |
| `ts` | When the change was applied. |
| `project_id`, `field` | What changed. |
| `old_value`, `new_value` | The change itself. |
| `kind` | `status_change`, `field_update`, `new_project` or `correction`. |
| `provenance` | The evidence that justified it. |
| `applied_by` | Who accepted it. |
| `note` | Optional context. |

This file drives both `/changes/` and the weekly digest. If a number on this site
ever changed, that change is in here with its evidence.

---

## 4. Candidate changes (`review/pending.md`)

What the ingest pipeline proposes, before any human has looked at it. **Nothing
here is published.** Each candidate carries the target field, the current and
proposed values, an evidence URL and snippet, a confidence level, and which
extractor produced it (`rules` or `llm:<model>`). Applying requires a ticked box
and an explicit `ism-tracker apply`.

---

## 5. Sources (`data/sources.yaml`)

The registry of feeds we poll — distinct from provenance, which cites one
document. Each has an `id`, `name`, `url`, fetcher `type`, a `source_type`
recording how much weight its claims carry, and a `poll_frequency`.

Polling is done politely: `robots.txt` is respected, a descriptive User-Agent
with a contact URL is sent, and requests to one domain are spaced at least two
seconds apart.
