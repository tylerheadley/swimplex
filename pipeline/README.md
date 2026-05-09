# Swimplex — Data Pipeline

SCIAC does not publish a centralised results database. Hy-Tek Meet Manager PDFs are the only structured source of meet results; they live on each school's Sidearm Sports schedule page and can disappear or become stale over time. This pipeline scrapes them, parses them into a uniform schema, and feeds the structured data into the optimisation model.

---

## Data flow

```
python3 main.py --scrape   →  data/<season>/pdfs/*.pdf

python3 main.py --parse    →  data/<season>/results.json
                               data/<season>/results.csv

python3 pipeline/process_results.py --season X --gender Men|Women \
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
                           →  data/<season>/event_rankings_<gender>.json
                               data/<season>/athlete_profiles_<gender>.json

python3 pipeline/best_performances.py --season X --gender Men|Women
                           →  data/<season>/best_performances_<gender>.json

python3 pipeline/ampl_export.py --season X --gender Men|Women \
        [--home-team 'Team Name']
                           →  data/<season>/best_performances_<gender>.dat

python3 pipeline/data_quality.py --season X  [--json]
                           →  console report  (+ optional JSON)
```

Every script accepts `--season YYYY-YY`. Gender-specific scripts also accept `--gender Men` or `--gender Women`.

---

## Scripts

### `scraper.py`

All nine SCIAC schools use the Sidearm Sports platform. Schedule pages are server-rendered HTML, so plain `requests` + `BeautifulSoup` is sufficient — no JavaScript execution required.

**Indirect PDF links.** PDFs are not directly linked from schedule pages. Sidearm wraps each file in an HTML viewer page; the actual file sits on a CloudFront CDN. The scraper detects this via the `Content-Type` header or the absence of `%PDF` magic bytes, then extracts the real CDN URL from the `s3_bucket_path` attribute or the `og:url` `<meta>` tag.

**Date filtering.** The scraper walks up the DOM from each `<a>` tag pointing to a PDF, looking for a recognisable date string. Only links whose date falls within the season window (September 1 – April 30) are downloaded.

**Safe filenames.** Each file is prefixed with the team abbreviation (e.g. `CALT_results.pdf`) to avoid collisions when the same meet PDF appears on multiple schools' pages. Spaces and special characters are replaced with underscores.

**Season URL rewriting.** Team schedule URLs contain a trailing `YYYY-YY` segment. The scraper replaces it at runtime so historical seasons can be scraped without editing `config.py`.

**Rate limiting.** A `REQUEST_DELAY` of 1.5 seconds is enforced between requests.

```
python3 main.py --scrape --season 2025-26
```

---

### `parser.py`

Uses `pdfplumber` word-level coordinate extraction (not text blocks or lines). Each word carries `x0`, `x1`, `top`, and `bottom`. Words are assigned to columns by their `x0` coordinate against empirically calibrated boundaries.

**Column layout:**

| Column  | x0 range         |
|---------|------------------|
| place   | `x0 < 46`        |
| name    | `46 ≤ x0 < 187`  |
| age     | `187 ≤ x0 < 210` |
| school  | `210 ≤ x0 < 360` |
| seed    | `360 ≤ x0 < 440` |
| finals  | `440 ≤ x0 < 525` |
| points  | `x0 ≥ 525`       |

**Non-obvious parsing issues:**

- **CID ligatures.** Some fonts encode `f` as `(cid:976)`. Without correction, "Butterfly" appears as "Butter(cid:976)ly". A CID-to-Unicode map is applied after extraction.
- **Floating-point boundary.** A word visually in the school column may have `x0 = 209.9999`, failing the `>= 210` check. All coordinates are rounded to one decimal place before comparison.
- **Athlete ID prefix.** Some PDFs prepend an integer athlete ID to the name field (e.g. `12345 Smith, John`). Leading digit sequences are stripped by regex.
- **Gender/year prefix in school field.** School fields sometimes read `W 18 CMS-CA` rather than `CMS-CA`. The leading gender letter and year code are stripped before canonicalisation.
- **"First Last" name order.** Most PDFs use "Last, First" order. At least one PDF (`CLU_full_results_pp_v_clu_v_westmont.pdf`) uses "First Last" with no comma. Name normalisation detects the missing comma and inverts the tokens.
- **Seed column shift.** In some PDFs the seed column shifts left so that a time value lands in the school column. The parser detects a time-shaped string in the school column and promotes it to seed.

**Relay parsing — two-pass approach:**

1. **Team row** (place / relay-name / school / time) is stored as a `pending_relay_result` with `relay_leg=0` and `is_relay=True`.
2. **Swimmer-name row** (`1) Last, First Age  2) Last, First Age …`) is split on leg-number prefixes and stored as swimmer names.
3. **Split rows** carry cumulative 50-yard marks and parenthesised per-leg deltas, accumulated until a non-split row arrives.
4. **Finalization.** `_finalize_relay` calls `_extract_leg_splits` to derive per-leg times, then appends one `SwimResult` per swimmer (`relay_leg = 1…4`).

**`relay_leg` semantics:**

| `relay_leg` | Meaning | Downstream treatment |
|-------------|---------|----------------------|
| 0 | Relay team row | Relay section of event rankings |
| 1 | Flat-start leadoff | Treated as an individual swim (no relay label) |
| ≥ 2 | Exchange-start split | Individual section, event suffixed with `(Relay Split)` |

---

### `main.py` (root shim → `pipeline/_main.py`)

The root `main.py` is a thin shim; the real implementation lives in `pipeline/_main.py`. It orchestrates scrape and parse, then applies post-parse cleanup.

**Season date range.** `YYYY-YY` → September 1 of the first year through April 30 of the second year. Passed to the scraper for date filtering.

**SCIAC filter.** After parsing, results whose school does not canonicalise to one of the nine SCIAC members are discarded. Non-SCIAC opponents appear in many dual-meet PDFs.

**Deduplication.** The same meet PDF is frequently downloaded from multiple schools' pages — SCIAC Championships appears nine times, once per school. We deduplicate on `(gender, event, name, school, finals, relay_leg)` before writing `results.json`.

```
python3 main.py --scrape --season 2025-26   # scrape only
python3 main.py --parse  --season 2025-26   # parse only
python3 main.py          --season 2025-26   # both steps
```

---

### `process_results.py`

Reads `results.json` and produces per-event rankings and per-athlete profiles.

**Name normalisation (`_normalize_name`) — six steps in order:**

1. Invert "First Last" → "Last, First" when no comma is present.
2. Strip leading gender prefix: `M.Kiss, Jake` → `Kiss, Jake`.
3. Strip trailing school/year codes: `WSO`, `WFR`, `W18`, `MSO`, `MFR`, `M21`, etc.
4. Strip trailing single-letter middle initial (upper or lower case).
5. Strip orphaned trailing comma: `Vanluvanee, ` → `Vanluvanee`.
6. Title-case all-caps first names that contain a vowel: `Zheng, BO` → `Zheng, Bo`; `Morris, DJ` is left alone.

**Name alias resolution:**

- *Case-variant resolution.* When the same last name appears with different capitalisation (e.g. `DeBoom` vs. `Deboom`), the most-frequent form wins.
- *Last-name-only merging.* A bare surname (e.g. `Vanluvanee`) is merged into the full form `Vanluvanee, Adam` when exactly one full form exists.
- *Manual aliases.* A small table of known nickname/typo pairs verified by hand.

**School canonicalisation.** 22 raw variants → 9 canonical SCIAC names. CMS has the most variants because Hy-Tek PDFs frequently prefix it with a gender letter and graduation year (e.g. `V 19 CMS-CA`).

**Swimmer vs. diver classification.** No explicit sport flag exists in the data. Classification uses each athlete's event portfolio: if they have only dive events → `diver`; only swim events → `swimmer`; both → `hybrid` if the minority type is at least one-third of the majority count, otherwise whichever type has the larger count.

**6-dive vs. 11-dive classification** (per meet × board pair):

1. Max score ≥ 450 → 11-dive.
2. Max score < 200 → 6-dive.
3. Ambiguous 200–450 → fit a 2-component GMM on all (meet, board) max scores (optionally augmented via `--aux-seasons`). Requires `scikit-learn`; falls back to a midpoint rule if not installed.

**Date range filtering.** `--date-from` and `--date-to` (both optional, `YYYY-MM-DD`) filter results to meets whose start date falls within the range. Multi-day meets use their start date. Useful for simulating what data would have been available before a given point — for example, `--date-to 2026-02-17` to exclude SCIAC championships.

**Outputs:** `event_rankings_<gender>.json` and `athlete_profiles_<gender>.json`.

```
python3 pipeline/process_results.py --season 2025-26 --gender Men
python3 pipeline/process_results.py --season 2025-26 --gender Women --aux-seasons 2024-25
python3 pipeline/process_results.py --season 2025-26 --gender Men --date-to 2026-02-17
```

---

### `best_performances.py`

Reads `athlete_profiles_<gender>.json` (output of `process_results.py`) and extracts the rank-1 entry for each (athlete, event) pair — the athlete's season best.

**Bare integer filtering.** Times that are bare integers (no colon or decimal) are rejected. These are place numbers the parser mistakenly picked up from mis-formatted rows — most commonly the 1650 Yard Freestyle section of the SCIAC conference PDF. Diving scores are not filtered because they can legitimately be round numbers.

```
python3 pipeline/best_performances.py --season 2025-26 --gender Men
```

---

### `ampl_export.py`

Converts `best_performances_<gender>.json` into AMPL `.dat` format for `model/Swimplex_time.mod`.

**Event sets (AMPL short ids → JSON event name):**

- **`SoloEvents`** (13): `free50`, `free100`, `free200`, `free500`, `free1650`, `back100`, `back200`, `breast100`, `breast200`, `fly100`, `fly200`, `im200`, `im400`
- **`RelayEvents`** (3 freestyle): `FR200` (4×50), `FR400` (4×100), `FR800` (4×200) — use leg split times
- **`MedleyEvents`** (2): `MED200` (4×50 medley) and `MED400` (4×100 medley) — use per-stroke split times. `MED200` uses 50-yard stroke splits; `MED400` uses 100-yard splits (`100 Yard Backstroke` individual time is used as the back-leg proxy for `MED400` since no relay split is tracked separately for that leg).
- **`DivingEvents`** (2): `dive1m`, `dive3m`

**Athletes.** All athletes in `best_performances_<gender>.json` belonging to a SCIAC team are included — swimmers, divers, and hybrids alike. The `--home-team` flag sets which team the model optimises for (default: `Claremont-Mudd-Scripps`).

**Parameters:**

- `solo_time {Athletes, SoloEvents}` — seconds; sentinel `9999` for missing times (higher is worse, so missing athletes never score).
- `leg_time {Athletes, RelayEvents}` — individual leg split in seconds; same sentinel.
- `leg_time_med {Athletes, MedleyEvents, Stroke}` — medley leg split per stroke; same sentinel.
- `diving_score {Athletes, DivingEvents}` — raw score (higher = better); sentinel `0.0` for no score.
- `solo_points {Place}` — SCIAC individual scoring: 20/17/16/…/1 for places 1–16; `1/rank` heuristic for places 17+.
- `relay_points {Place_Relay, Level}` — 2× the corresponding individual points. A heat (overall places 1–9); B heat (overall places 10–18).
- `relay_enroll_ct = 4`, `home_team` (symbolic).

```
python3 pipeline/ampl_export.py --season 2025-26 --gender Men
python3 pipeline/ampl_export.py --season 2025-26 --gender Women --home-team 'Pomona-Pitzer'
```

---

### `data_quality.py`

Runs ten validation checks on parsed data and prints a human-readable report.

1. **Suspect times** — bare integers and times whose pace falls outside 15–50 s per 50 yards.
2. **Suspect dive scores** — scores outside [50, 800].
3. **Unrecognised schools** — strings that do not map to a canonical SCIAC name.
4. **Residual name suffixes** — W/M+year codes still present after normalisation.
5. **Missing first name** — names that reduce to `Last, ` after normalisation.
6. **Near-duplicate names** — pairs sharing the same last name with first-name similarity > 0.80 (same school only).
7. **First-Last format names** — raw names with no comma.
8. **Case-variant duplicates** — same name with different capitalisation.
9. **Event name anomalies** — unusual relay distances or mixed Yard/Meter keywords.
10. **Relay split sanity** — split times exceeding the upper bound implied by the pace rule.

```
python3 pipeline/data_quality.py --season 2025-26
python3 pipeline/data_quality.py --season 2025-26 --json
```

---

## `config.py`

School names, team schedule URLs, season defaults, and the `is_sciac_school()` predicate. Edit here to add teams or change the default season window.
