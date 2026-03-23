# Swimplex Web App

A single-page Flask coach UI that wraps the data pipeline and lets you browse, edit, and export SCIAC swimming best times without touching the command line.

## Running

```bash
python3 web/app.py
# open http://localhost:5001
```

Set `PORT` to change the port. The app runs in Flask debug mode locally, so it auto-reloads on code changes.

## Architecture overview

The backend is a single file (`app.py`) that imports and calls pipeline modules directly — no subprocesses. The frontend is a single HTML page (`templates/index.html`) that communicates with the backend through JSON and SSE endpoints. There's no build step, no bundler, no JS framework.

### Step 1 — Scrape & Parse

Hitting the Scrape or Parse buttons fires a POST request that starts the respective pipeline function in a background thread. The page receives live log output via **Server-Sent Events**: `app.py` redirects both `sys.stdout` and the Python logging root handler into a `queue.Queue`, and the SSE response drains that queue line-by-line until a sentinel signals completion. This is why you see live progress in the browser even though scraping and parsing can take a while.

A status hint under each button tells you how many PDFs are already downloaded and when results were last parsed, so you don't re-scrape unnecessarily. This comes from the `/api/data-status` endpoint, which just checks file mtimes.

### Step 2 — Best Times

The best times tab shows one row per athlete-event combination, sourced from `best_performances_<gender>.json`. Three layers of per-session overrides sit on top of the raw data:

- **Edit** — changes a time for a specific athlete-event. Stored in `edits_<gender>.json` as `{"action": "edit", "time": "..."}`.
- **Discard** — hides a row entirely (e.g. a mis-parsed entry you don't want in the model). Stored as `{"action": "discard"}` in the same file.
- **Restore** — removes the override and reverts to the scraped value.
- **Manual additions** — times your coach knows about that aren't in any scraped PDF. Stored separately in `manual_additions_<gender>.json` so they survive re-parses without getting clobbered. These rows display a `[M]` badge and have a yellow background.

The `_build_athlete_rows()` helper in `app.py` merges all three sources every time the page loads. Edits and discards apply equally to scraped and manually added rows.

The event filter dropdown uses a fixed canonical ordering (freestyle by distance → butterfly → backstroke → breaststroke → IM → diving → relay splits) rather than alphabetical, because alphabetical order mixes strokes together in a confusing way for coaching use.

### Step 2 — Data Quality

The data quality tab calls `data_quality.build_report()` from the pipeline and displays the results grouped by issue category. Issues can be resolved in-browser with three actions:

- **Accept Fix** — accepts the auto-corrected value that `_clean_raw` would have applied.
- **Edit** — lets you type the correct value manually.
- **Discard** — marks the entry as reviewed and removes it from future reports.

Resolutions are written to `quality_resolutions.json`. Edit and Accept Fix resolutions also propagate into `edits_<gender>.json` so the corrected time shows up immediately on the Best Times tab. On subsequent loads, resolved issues are filtered out of the quality report.

### Export

The export buttons produce CSV or JSON from the same `_build_athlete_rows()` function the best-times tab uses, so edits and manual additions are always included.

## Persistence files

All files live under `data/<season>/`:

| File | Purpose |
|------|---------|
| `edits_<gender>.json` | Coach time edits and discards |
| `manual_additions_<gender>.json` | Manually added athlete entries |
| `quality_resolutions.json` | Resolved data quality flags |

These files are intentionally separate from the pipeline outputs so that re-running the scrape/parse pipeline never overwrites coach edits.

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves the UI |
| POST | `/api/scrape` | Scrape PDFs; body `{season, start, end}`; SSE stream |
| POST | `/api/parse` | Parse + process pipeline; body `{season, gender}`; SSE stream |
| GET | `/api/data-status` | PDF count + parse timestamps for a season |
| GET | `/api/athletes` | Best times rows; params `season`, `gender` |
| POST | `/api/athletes/edit` | Override a best time |
| POST | `/api/athletes/discard` | Hide an entry |
| POST | `/api/athletes/restore` | Remove an override |
| POST | `/api/athletes/add` | Add a manual entry |
| GET | `/api/quality` | Data quality report (resolved items filtered out) |
| POST | `/api/quality/resolve` | Resolve a quality flag |
| GET | `/api/export/csv` | Download best times as CSV |
| GET | `/api/export/json` | Download best times as JSON |
