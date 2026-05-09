# Swimplex — Web App

A single-page Flask coach UI that wraps the data pipeline and optimisation model. No build step, no JS framework, no bundler — one Python file (`app.py`) and one HTML file (`templates/index.html`).

---

## Running

```bash
python3 web/app.py
# open http://localhost:5001
```

Set the `PORT` environment variable to override the default. The app runs with Flask's built-in server in debug/threaded mode, so it auto-reloads on code changes during development.

---

## Architecture

The frontend is a single HTML page that communicates with the backend through JSON endpoints and Server-Sent Events (SSE). The backend imports pipeline modules in-process for fast operations (data loading, edits, exports), and spawns a subprocess for the optimisation model (see caveat below).

### Step 1 — Scrape & Parse

The Scrape and Parse buttons each fire a POST that runs the corresponding pipeline function in a **background thread**. Live output reaches the browser via SSE: `app.py` redirects `sys.stdout` and the Python logging root handler into a `queue.Queue` via `_QueueWriter` and `_QueueHandler`; the SSE response generator drains that queue line-by-line, yielding each line as a `data:` event until a sentinel signals completion.

The `_PIPELINE_LOCK` ensures that only one parse pipeline runs at a time (since `process_results.py` and `best_performances.py` patch `sys.argv` to simulate CLI invocation).

The `/api/data-status` endpoint checks file mtimes and PDF counts so the UI can show when data was last updated without re-running anything.

### Step 2 — Data Review

`/api/athletes` serves rows from `best_performances_<gender>.json` merged with two override layers via `_build_athlete_rows()`:

- **`edits_<gender>.json`** — keyed by athlete name → event. Values are `{"action": "edit", "time": "..."}` or `{"action": "discard"}`. Discarded rows are dropped; edits replace the scraped best time.
- **`manual_additions_<gender>.json`** — athlete entries added by the coach that have no scraped counterpart. Same structure as the best_performances swimmers dict. Manual rows that are also in the scraped data are skipped (scraped takes precedence).

Edits and discards apply to both scraped and manually added rows. The merge happens on every request — no caching.

The data quality tab calls `data_quality.build_report()` directly and filters out already-resolved issues using `quality_resolutions.json`. Edit and Accept Fix resolutions also propagate into `edits_<gender>.json` so the corrected time appears immediately on the Best Times tab.

### Step 3 — Model

`/api/model/run` launches `model/run_iterative.py` as a **subprocess** via `subprocess.Popen`, streaming its combined stdout/stderr line-by-line as SSE events. The endpoint first checks that the `.dat` file exists for the requested season and gender; if it doesn't, it returns an error event immediately without spawning a process.

**Why subprocess and not in-process threading?** Gurobi's C library calls `abort()` when initialised from a non-main thread, which kills the Flask process with SIGABRT. Running `run_iterative.py` as a child process sidesteps this entirely — Gurobi sees a clean main thread.

Parameters passed to the subprocess:

| CLI flag | Source |
|----------|--------|
| `--season`, `--gender` | POST body |
| `--solver` | POST body (default `gurobi`) |
| `--mip-gap` | POST body (default `0.0`) |
| `--time-limit` | POST body (omitted if not set) |
| `--br-teams` | POST body (space-separated list) |
| `--skip-pipeline` | always set (pipeline already ran in Step 1) |

### Step 4 — Lineup

`/api/lineup` reads `model_results_<gender>.json` written by `run_iterative.py` and reshapes it for the UI:

- **Scoreboard** — built from `greedy_scores` and `optimized_scores` dicts in the results file. Teams are sorted by optimized score descending.
- **Per-team rosters** — pulled from `optimized_rosters`. Each athlete's assigned events are enriched with their seed time or diving score looked up from `best_performances_<gender>.json`.
- **Relay rows** — built by `_build_relay_rows()` from `optimized_relays`. Leg times are looked up from `best_performances_<gender>.json` using the same event-key mapping as `ampl_export.py`. Projected total relay times are computed by summing the four leg times.

---

## Persistence files

All files live under `data/<season>/` and survive pipeline re-runs:

| File | Written by | Purpose |
|------|-----------|---------|
| `edits_<gender>.json` | web app | Coach time overrides and discards |
| `manual_additions_<gender>.json` | web app | Manually added athlete entries |
| `quality_resolutions.json` | web app | Resolved data quality flags |
| `model_results_<gender>.json` | `run_iterative.py` | Optimisation output (scores + rosters + relays) |

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves the UI |
| POST | `/api/scrape` | Scrape PDFs; body `{season, start, end}`; SSE stream |
| POST | `/api/parse` | Parse + process pipeline; body `{season, gender, date_from, date_to}`; SSE stream |
| GET | `/api/data-status` | PDF count + parse/model result timestamps; param `season` |
| GET | `/api/athletes` | Best times rows merged with edits + manual additions; params `season`, `gender` |
| POST | `/api/athletes/edit` | Override a best time; body `{season, gender, name, event, time}` |
| POST | `/api/athletes/discard` | Hide an entry; body `{season, gender, name, event}` |
| POST | `/api/athletes/restore` | Remove an override; body `{season, gender, name, event}` |
| POST | `/api/athletes/add` | Add a manual entry; body `{season, gender, name, school, age, event, best, meet, date}` |
| GET | `/api/quality` | Data quality report with resolved items filtered out; param `season` |
| POST | `/api/quality/resolve` | Resolve a quality flag; body `{season, gender, name, event, value, pdf, action, corrected_time}` |
| GET | `/api/export/csv` | Best times as CSV (edits + manual additions included); params `season`, `gender` |
| GET | `/api/export/json` | Best times as JSON; params `season`, `gender` |
| POST | `/api/model/run` | Run optimisation model as subprocess; body `{season, gender, solver, mip_gap, time_limit, br_teams}`; SSE stream |
| GET | `/api/lineup` | Optimised lineup + scoreboard; params `season`, `gender` |
| GET | `/api/lineup/export/csv` | Scoreboard + all-team rosters as CSV; params `season`, `gender` |

---

## Technical caveats

**Gurobi and threading.** The model must run as a subprocess, not in a thread. Gurobi's C library aborts the process if it is initialised from any thread other than the main thread. Attempting to call `run_iterative.py` via `runpy` or `importlib` inside a Flask request thread will crash the server with SIGABRT.

**`sys.argv` patching.** The pipeline wrappers for `process_results.py` and `best_performances.py` patch `sys.argv` before calling `main()`, then restore it in a `finally` block. This is why `_PIPELINE_LOCK` exists — concurrent parse requests would race on `sys.argv`.

**SSE and proxies.** If the app is deployed behind a reverse proxy (nginx, etc.), SSE streaming requires `X-Accel-Buffering: no` and `Cache-Control: no-cache` response headers, which are already set. Without them, the proxy buffers the response and the live log won't appear until the request completes.

**Debug mode.** Flask runs with `debug=True`, which means the Werkzeug reloader forks the process. If AMPL or Gurobi licenses are tied to a process ID, the reloader fork may cause license errors. Disable with `FLASK_DEBUG=0` if this is an issue.
