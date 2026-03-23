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
# Data quality — delegate to data_quality.build_report()
# ---------------------------------------------------------------------------

def _build_quality_report(season: str) -> dict:
    import data_quality
    return data_quality.build_report(season)


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


@app.route("/api/data-status")
def api_data_status():
    season = request.args.get("season", "2025-26")
    season_dir = DATA_DIR / season

    # PDFs
    pdf_dir = season_dir / "pdfs"
    pdf_files = list(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    pdf_mtime = max((p.stat().st_mtime for p in pdf_files), default=None)

    # results.json
    results_path = season_dir / "results.json"
    results_mtime = results_path.stat().st_mtime if results_path.exists() else None

    # best_performances
    bp_men   = season_dir / "best_performances_men.json"
    bp_women = season_dir / "best_performances_women.json"

    import time

    def _fmt(ts):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else None

    return jsonify({
        "pdfs":   {"count": len(pdf_files), "last_updated": _fmt(pdf_mtime)},
        "parsed": {"exists": results_path.exists(), "last_updated": _fmt(results_mtime)},
        "best_performances": {
            "men":   {"exists": bp_men.exists(),   "last_updated": _fmt(bp_men.stat().st_mtime   if bp_men.exists()   else None)},
            "women": {"exists": bp_women.exists(), "last_updated": _fmt(bp_women.stat().st_mtime if bp_women.exists() else None)},
        },
    })


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

    resolutions = _load_resolutions(season)
    resolved = {(r["name"], r["event"], r.get("value", ""), r["pdf"]) for r in resolutions}
    for cat in list(report.keys()):
        report[cat] = [
            item for item in report[cat]
            if (item.get("name"), item.get("event"),
                item.get("raw", item.get("finals", "")),
                item.get("pdf", "")) not in resolved
        ]
        if not report[cat]:
            del report[cat]

    return jsonify(report)


@app.route("/api/athletes")
def api_athletes():
    season = request.args.get("season", "2025-26")
    gender = request.args.get("gender", "Men")
    rows = _build_athlete_rows(season, gender)
    if rows is None:
        return jsonify({"error": "best_performances not found — run parse first"}), 404
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
    edits.setdefault(name, {})[event] = {"action": "edit", "time": new_time}
    _save_edits(season, gender, edits)
    return jsonify({"ok": True, "name": name, "event": event, "time": new_time})


@app.route("/api/athletes/discard", methods=["POST"])
def api_discard_athlete():
    body   = request.get_json(force=True)
    season = body.get("season", "2025-26")
    gender = body.get("gender", "Men")
    name   = body.get("name", "")
    event  = body.get("event", "")
    edits  = _load_edits(season, gender)
    edits.setdefault(name, {})[event] = {"action": "discard"}
    _save_edits(season, gender, edits)
    return jsonify({"ok": True})


@app.route("/api/athletes/restore", methods=["POST"])
def api_restore_athlete():
    body   = request.get_json(force=True)
    season = body.get("season", "2025-26")
    gender = body.get("gender", "Men")
    name   = body.get("name", "")
    event  = body.get("event", "")
    edits  = _load_edits(season, gender)
    if name in edits and event in edits[name]:
        del edits[name][event]
        if not edits[name]:
            del edits[name]
    _save_edits(season, gender, edits)
    return jsonify({"ok": True})


@app.route("/api/athletes/add", methods=["POST"])
def api_add_athlete():
    body   = request.get_json(force=True)
    season = body.get("season", "2025-26")
    gender = body.get("gender", "Men")
    name   = body.get("name", "").strip()
    school = body.get("school", "").strip()
    age    = body.get("age", "").strip()
    event  = body.get("event", "").strip()
    best   = body.get("best", "").strip()
    meet   = body.get("meet", "Manually added").strip()
    date   = body.get("date", "").strip()
    if not name or not event or not best:
        return jsonify({"error": "name, event, and best are required"}), 400
    manual = _load_manual(season, gender)
    if name not in manual:
        manual[name] = {"school": school, "age": age, "events": {}}
    manual[name]["events"][event] = {"best": best, "meet": meet, "date": date}
    _save_manual(season, gender, manual)
    return jsonify({"ok": True, "name": name, "event": event, "best": best})


@app.route("/api/quality/resolve", methods=["POST"])
def api_quality_resolve():
    body           = request.get_json(force=True)
    season         = body.get("season", "2025-26")
    gender         = body.get("gender", "")
    name           = body.get("name", "")
    event          = body.get("event", "")   # may have gender prefix
    value          = body.get("value", "")   # raw / finals identifying value
    pdf            = body.get("pdf", "")
    action         = body.get("action", "discard")   # "discard" | "edit" | "accept_fix"
    corrected_time = body.get("corrected_time", "").strip()

    resolutions = _load_resolutions(season)
    resolutions = [r for r in resolutions
                   if not (r["name"] == name and r["event"] == event
                           and r.get("value") == value and r["pdf"] == pdf)]
    resolutions.append({
        "name": name, "event": event, "value": value, "pdf": pdf,
        "action": action, "corrected_time": corrected_time or None,
    })
    _save_resolutions(season, resolutions)

    # Propagate edit/accept_fix to best-times edits
    if action in ("edit", "accept_fix") and corrected_time and gender:
        bare_event = re.sub(r"^(Men|Women|Mixed)\s+", "", event, flags=re.IGNORECASE).strip()
        edits = _load_edits(season, gender)
        edits.setdefault(name, {})[bare_event] = {"action": "edit", "time": corrected_time}
        _save_edits(season, gender, edits)

    return jsonify({"ok": True})


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
    rows = _build_athlete_rows(season, gender)
    if rows is None:
        return "best_performances not found", 404
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "school", "age", "event", "best", "meet", "date"])
    for r in rows:
        writer.writerow([r["name"], r["school"], r["age"], r["event"],
                         r["best"], r["meet"], r["date"]])
    buf.seek(0)
    return Response(buf.read(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=best_performances_{gender.lower()}_{season}.csv"})


@app.route("/api/export/json")
def api_export_json():
    season = request.args.get("season", "2025-26")
    gender = request.args.get("gender", "Men")
    rows = _build_athlete_rows(season, gender)
    if rows is None:
        return "best_performances not found", 404
    return Response(
        json.dumps(rows, indent=2),
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
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    out = {}
    for name, events in raw.items():
        out[name] = {}
        for event, val in events.items():
            out[name][event] = val if isinstance(val, dict) else {"action": "edit", "time": val}
    return out


def _save_edits(season: str, gender: str, edits: dict) -> None:
    p = _edits_path(season, gender)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(edits, indent=2))


def _manual_path(season: str, gender: str) -> Path:
    return DATA_DIR / season / f"manual_additions_{gender.lower()}.json"

def _load_manual(season: str, gender: str) -> dict:
    p = _manual_path(season, gender)
    return json.loads(p.read_text()) if p.exists() else {}

def _save_manual(season: str, gender: str, manual: dict) -> None:
    p = _manual_path(season, gender)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manual, indent=2))

def _resolutions_path(season: str) -> Path:
    return DATA_DIR / season / "quality_resolutions.json"

def _load_resolutions(season: str) -> list:
    p = _resolutions_path(season)
    return json.loads(p.read_text()) if p.exists() else []

def _save_resolutions(season: str, resolutions: list) -> None:
    p = _resolutions_path(season)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(resolutions, indent=2))


def _build_athlete_rows(season: str, gender: str):
    """Build athlete rows from scraped data + edits + manual additions. Returns None if bp missing."""
    bp_path = DATA_DIR / season / f"best_performances_{gender.lower()}.json"
    if not bp_path.exists():
        return None
    data   = json.loads(bp_path.read_text())
    edits  = _load_edits(season, gender)
    manual = _load_manual(season, gender)

    rows = []
    seen = set()  # (name, event) already covered by scraped data

    for name, info in data["swimmers"].items():
        for event, perf in info["events"].items():
            edit = edits.get(name, {}).get(event)
            if edit and edit.get("action") == "discard":
                continue
            best = edit["time"] if edit and edit.get("action") == "edit" else perf.get("best", perf.get("time", ""))
            rows.append({
                "name":   name,
                "school": info.get("school", ""),
                "age":    info.get("age", ""),
                "event":  event,
                "best":   best,
                "meet":   perf.get("meet", ""),
                "date":   perf.get("date", ""),
                "edited": bool(edit and edit.get("action") == "edit"),
                "manual": False,
            })
            seen.add((name, event))

    for name, info in manual.items():
        for event, perf in info["events"].items():
            if (name, event) in seen:
                continue
            edit = edits.get(name, {}).get(event)
            if edit and edit.get("action") == "discard":
                continue
            best = edit["time"] if edit and edit.get("action") == "edit" else perf.get("best", "")
            rows.append({
                "name":   name,
                "school": info.get("school", ""),
                "age":    info.get("age", ""),
                "event":  event,
                "best":   best,
                "meet":   perf.get("meet", "Manually added"),
                "date":   perf.get("date", ""),
                "edited": bool(edit and edit.get("action") == "edit"),
                "manual": True,
            })

    return rows


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
