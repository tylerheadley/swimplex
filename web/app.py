"""
app.py — Swimplex Flask backend.

Serves the single-page coach UI and provides JSON/SSE API endpoints that
wrap the existing pipeline scripts without modifying them.

Usage:
    python3 app.py
    open http://localhost:5000
"""

import io
import json
import os
import logging
import queue
import re
import sys
import threading
from collections import defaultdict
from datetime import date
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

_PROJECT_ROOT = Path(__file__).parent.parent
_PIPELINE_DIR = _PROJECT_ROOT / "pipeline"
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

app = Flask(__name__)

BASE_DIR = _PROJECT_ROOT
DATA_DIR = BASE_DIR / "data"

# Lock so sys.argv patching in process_results / best_performances is safe
_PIPELINE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Logging + stdout capture for SSE streaming
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, q: "queue.Queue[str]") -> None:
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(self.format(record))


class _QueueWriter:
    """Redirect sys.stdout into the shared SSE queue."""
    def __init__(self, q: "queue.Queue[str]") -> None:
        self.q = q

    def write(self, s: str) -> None:
        for line in s.splitlines():
            stripped = line.strip()
            if stripped:
                self.q.put(stripped)

    def flush(self) -> None:
        pass


_LOG_FMT = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S"
)
_SENTINEL = object()


def _stream_fn(fn, *args, **kwargs):
    """
    Run fn(*args, **kwargs) in a background thread.
    Yield captured log lines and stdout writes as they arrive.
    """
    q: "queue.Queue" = queue.Queue()

    handler = _QueueHandler(q)
    handler.setFormatter(_LOG_FMT)
    root = logging.getLogger()
    root.addHandler(handler)

    old_stdout = sys.stdout

    def _target() -> None:
        sys.stdout = _QueueWriter(q)
        try:
            fn(*args, **kwargs)
        except SystemExit:
            pass
        except Exception as exc:
            q.put(f"ERROR: {exc}")
        finally:
            sys.stdout = old_stdout
            q.put(_SENTINEL)

    t = threading.Thread(target=_target, daemon=True)
    t.start()

    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        yield item

    root.removeHandler(handler)
    t.join(timeout=30)


def _sse(gen):
    """Wrap a text generator as SSE events, with a terminal __DONE__ event."""
    for line in gen:
        yield f"data: {line}\n\n"
    yield "data: __DONE__\n\n"


# ---------------------------------------------------------------------------
# Pipeline wrappers — called as modules, never via subprocess
# ---------------------------------------------------------------------------

def _do_scrape(season: str, start: date, end: date) -> None:
    from scraper import scrape_all_teams
    pdf_dir = DATA_DIR / season / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdfs = scrape_all_teams(start=start, end=end, season=season, pdf_dir=pdf_dir)
    logging.getLogger(__name__).info("Downloaded %d PDF(s).", len(pdfs))


def _do_parse(season: str) -> None:
    from parser import parse_all_pdfs, result_to_dict
    from _main import _filter_sciac, _deduplicate, _write_csv, _write_json
    log = logging.getLogger(__name__)
    out_dir = DATA_DIR / season
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = out_dir / "pdfs"
    log.info("Parsing PDFs in %s ...", pdf_dir)
    results = parse_all_pdfs(pdf_dir=pdf_dir)
    if not results:
        log.warning("No results found in PDF directory.")
        return
    results = _filter_sciac(results)
    results = _deduplicate(results)
    records = [result_to_dict(r) for r in results]
    _write_csv(records, out_dir / "results.csv")
    _write_json(records, out_dir / "results.json")


def _do_process(season: str, gender: str) -> None:
    old_argv = sys.argv
    sys.argv = ["process_results.py", "--season", season, "--gender", gender]
    try:
        import process_results
        process_results.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv


def _do_best_perfs(season: str, gender: str) -> None:
    old_argv = sys.argv
    sys.argv = ["best_performances.py", "--season", season, "--gender", gender]
    try:
        import best_performances
        best_performances.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv


def _run_parse_pipeline(season: str, gender: str) -> None:
    log = logging.getLogger(__name__)
    with _PIPELINE_LOCK:
        _do_parse(season)
        genders = ["Men", "Women"] if gender == "Mixed" else [gender]
        for g in genders:
            log.info("Processing results for %s ...", g)
            _do_process(season, g)
            log.info("Extracting best performances for %s ...", g)
            _do_best_perfs(season, g)
        log.info("Pipeline complete.")


# ---------------------------------------------------------------------------
# Data quality helpers (calling internals directly, not main())
# ---------------------------------------------------------------------------

def _build_quality_report(season: str) -> dict:
    from data_quality import (
        _normalize_name, _build_name_aliases, _to_seconds,
        _is_diving, _pace_bounds, _find_near_duplicates,
        _MANUAL_NAME_ALIASES, _TRAILING_CODE_RE,
        _TRAILING_SYMS_RE, _DIST_UNIT_RE,
    )
    from process_results import _canonicalize_school

    results_path = DATA_DIR / season / "results.json"
    rows: list[dict] = json.loads(results_path.read_text())

    for r in rows:
        r["_norm_name"] = _normalize_name(r["name"])
    aliases = _build_name_aliases([r["_norm_name"] for r in rows])
    for r in rows:
        n = aliases.get(r["_norm_name"], r["_norm_name"])
        r["_norm_name"] = _MANUAL_NAME_ALIASES.get(n, n)

    issues: dict[str, list] = defaultdict(list)
    indiv_rows = [r for r in rows if not r["is_relay"] or r["relay_leg"] > 0]

    # 1. Suspect times
    for r in indiv_rows:
        if _is_diving(r["event_name"]) or r["relay_leg"] >= 2:
            continue
        val = _to_seconds(r["finals"])
        if val is None:
            continue
        raw_clean = _TRAILING_SYMS_RE.sub("", r["finals"].strip()).strip()
        if re.fullmatch(r"\d+", raw_clean):
            issues["suspect_times"].append({
                "name": r["_norm_name"], "event": r["event_name"],
                "finals": r["finals"], "reason": "bare integer (no colon/decimal)",
                "pdf": r["pdf_file"], "meet": r["meet_name"],
            })
            continue
        bounds = _pace_bounds(r["event_name"])
        if bounds:
            lo, hi = bounds
            if not (lo <= val <= hi):
                m_dist = _DIST_UNIT_RE.search(r["event_name"])
                dist = float(m_dist.group(1)) if m_dist else 0
                per50 = round(val / (dist / 50), 2) if dist else None
                issues["suspect_times"].append({
                    "name": r["_norm_name"], "event": r["event_name"],
                    "finals": r["finals"], "seconds": round(val, 2), "per_50": per50,
                    "reason": f"pace {per50}s/50 outside [15, 50]",
                    "pdf": r["pdf_file"], "meet": r["meet_name"],
                })

    # 2. Near-duplicate names
    all_norm = list({r["_norm_name"] for r in indiv_rows if r["_norm_name"]})
    name_school: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in indiv_rows:
        name_school[r["_norm_name"]][_canonicalize_school(r["school"])] += 1

    def _cs(name: str) -> str:
        votes = name_school.get(name, {})
        return max(votes, key=votes.__getitem__) if votes else ""

    for a, b, sim in _find_near_duplicates(all_norm, threshold=0.80):
        sa, sb = _cs(a), _cs(b)
        if sa and sb and sa != sb:
            continue
        issues["near_duplicate_names"].append({"name_a": a, "name_b": b, "similarity": sim})

    # 3. Case variants
    lower_map: dict[str, list] = defaultdict(list)
    for n in all_norm:
        lower_map[n.lower()].append(n)
    for variants in lower_map.values():
        u = sorted(set(variants))
        if len(u) > 1:
            issues["case_variant_names"].append(u)

    # 4. Missing first names
    seen_miss: set = set()
    for r in rows:
        norm = r["_norm_name"]
        if "," in norm and not norm.split(",", 1)[1].strip():
            key = (r["name"], r["pdf_file"])
            if key not in seen_miss:
                seen_miss.add(key)
                issues["missing_first_name"].append({
                    "raw": r["name"], "normalised": norm, "pdf": r["pdf_file"],
                })

    # 5. Residual name suffixes
    seen_sfx: set = set()
    for r in rows:
        if _TRAILING_CODE_RE.search(r["_norm_name"]):
            key = (r["name"], r["pdf_file"])
            if key not in seen_sfx:
                seen_sfx.add(key)
                issues["residual_name_suffixes"].append({
                    "raw": r["name"], "normalised": r["_norm_name"], "pdf": r["pdf_file"],
                })

    return dict(issues)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    body   = request.get_json(force=True)
    season = body.get("season", "2025-26")
    start_year = int(season.split("-")[0])
    end_year   = start_year + 1
    start = date.fromisoformat(body.get("start", f"{start_year}-09-01"))
    end   = date.fromisoformat(body.get("end",   f"{end_year}-04-30"))
    return Response(
        stream_with_context(_sse(_stream_fn(_do_scrape, season, start, end))),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/api/parse", methods=["POST"])
def api_parse():
    body   = request.get_json(force=True)
    season = body.get("season", "2025-26")
    gender = body.get("gender", "Men")
    return Response(
        stream_with_context(_sse(_stream_fn(_run_parse_pipeline, season, gender))),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/api/quality")
def api_quality():
    season = request.args.get("season", "2025-26")
    results_path = DATA_DIR / season / "results.json"
    if not results_path.exists():
        return jsonify({"error": "results.json not found — run parse first"}), 404
    try:
        report = _build_quality_report(season)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(report)


@app.route("/api/athletes")
def api_athletes():
    season = request.args.get("season", "2025-26")
    gender = request.args.get("gender", "Men")
    bp_path = DATA_DIR / season / f"best_performances_{gender.lower()}.json"
    if not bp_path.exists():
        return jsonify({"error": "best_performances not found — run parse first"}), 404

    data   = json.loads(bp_path.read_text())
    edits  = _load_edits(season, gender)

    rows = []
    for name, info in data["swimmers"].items():
        for event, perf in info["events"].items():
            best = edits.get(name, {}).get(event, perf.get("best", perf.get("time", "")))
            rows.append({
                "name":   name,
                "school": info.get("school", ""),
                "age":    info.get("age", ""),
                "event":  event,
                "best":   best,
                "meet":   perf.get("meet", ""),
                "date":   perf.get("date", ""),
                "edited": name in edits and event in edits.get(name, {}),
            })
    return jsonify(rows)


@app.route("/api/athletes/edit", methods=["POST"])
def api_edit_athlete():
    body     = request.get_json(force=True)
    season   = body.get("season", "2025-26")
    gender   = body.get("gender", "Men")
    name     = body.get("name", "")
    event    = body.get("event", "")
    new_time = body.get("time", "").strip()

    edits = _load_edits(season, gender)
    edits.setdefault(name, {})[event] = new_time
    _save_edits(season, gender, edits)
    return jsonify({"ok": True, "name": name, "event": event, "time": new_time})


@app.route("/api/model/run", methods=["POST"])
def api_model_run():
    return jsonify({"status": "not_implemented", "message": "Model not yet configured"})


@app.route("/api/lineup")
def api_lineup():
    return jsonify({"lineup": [], "status": "not_implemented"})


@app.route("/api/export/csv")
def api_export_csv():
    season = request.args.get("season", "2025-26")
    gender = request.args.get("gender", "Men")
    bp_path = DATA_DIR / season / f"best_performances_{gender.lower()}.json"
    if not bp_path.exists():
        return "best_performances not found", 404

    import csv
    data  = json.loads(bp_path.read_text())
    edits = _load_edits(season, gender)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "school", "age", "event", "best", "meet", "date"])
    for name, info in data["swimmers"].items():
        for event, perf in info["events"].items():
            best = edits.get(name, {}).get(event, perf.get("best", perf.get("time", "")))
            writer.writerow([
                name, info.get("school", ""), info.get("age", ""),
                event, best, perf.get("meet", ""), perf.get("date", ""),
            ])
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=best_performances_{gender.lower()}_{season}.csv"},
    )


@app.route("/api/export/json")
def api_export_json():
    season = request.args.get("season", "2025-26")
    gender = request.args.get("gender", "Men")
    bp_path = DATA_DIR / season / f"best_performances_{gender.lower()}.json"
    if not bp_path.exists():
        return "best_performances not found", 404

    data  = json.loads(bp_path.read_text())
    edits = _load_edits(season, gender)

    for name, athlete_edits in edits.items():
        if name in data["swimmers"]:
            for event, new_time in athlete_edits.items():
                if event in data["swimmers"][name]["events"]:
                    data["swimmers"][name]["events"][event]["best"] = new_time

    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition":
                 f"attachment; filename=best_performances_{gender.lower()}_{season}.json"},
    )


# ---------------------------------------------------------------------------
# Edit persistence helpers
# ---------------------------------------------------------------------------

def _edits_path(season: str, gender: str) -> Path:
    return DATA_DIR / season / f"edits_{gender.lower()}.json"


def _load_edits(season: str, gender: str) -> dict:
    p = _edits_path(season, gender)
    return json.loads(p.read_text()) if p.exists() else {}


def _save_edits(season: str, gender: str, edits: dict) -> None:
    p = _edits_path(season, gender)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(edits, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, threaded=True, host="0.0.0.0", port=port)
