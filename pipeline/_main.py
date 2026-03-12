"""
Swimplex — main entry point.

Usage:
    python main.py [--scrape] [--parse] [--season YYYY-YY]
                   [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                   [--pdf-dir PATH] [--out PATH]

Modes:
    --scrape   Visit each SCIAC schedule page and download Hy-Tek result PDFs.
    --parse    Parse all PDFs in data/pdfs/ (or --pdf-dir) and write CSV/JSON.

By default both steps run if neither flag is provided.

Season selection:
    --season 2025-26   (recommended)
        Automatically derives start/end dates, rewrites schedule URLs, and
        names the output folder data/2025-26/.
    --start / --end
        Override the date window manually (legacy; still works).
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from config import SEASON_END, SEASON_START, is_sciac_school
from parser import SwimResult, parse_all_pdfs, result_to_dict
from scraper import scrape_all_teams

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")

_PROJECT_ROOT = Path(__file__).parent.parent
_BASE_DATA_DIR = _PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Season helpers
# ---------------------------------------------------------------------------

def _season_dates(season: str) -> tuple[date, date]:
    """
    Convert a season string like '2025-26' or '2024-25' into (start, end) dates.
    Season runs September 1 of the first year through April 30 of the second year.
    """
    m = _SEASON_RE.match(season)
    if not m:
        raise argparse.ArgumentTypeError(
            f"Invalid season '{season}'. Expected format: YYYY-YY (e.g. 2025-26)"
        )
    start_year = int(m.group(1))
    end_suffix = int(m.group(2))
    end_year = (start_year // 100) * 100 + end_suffix
    return date(start_year, 9, 1), date(end_year, 4, 30)


def _season_str(start: date, end: date) -> str:
    return f"{start.year}-{str(end.year)[2:]}"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------

_QUAL_SYM_RE = re.compile(r"[@#$%!]+$")


def _norm_finals(s: str) -> str:
    """Strip Hy-Tek qualifier symbols so '1:21.57#' == '1:21.57' for dedup."""
    return _QUAL_SYM_RE.sub("", s.strip())


def _deduplicate(results: list[SwimResult]) -> list[SwimResult]:
    """
    Remove exact duplicates that arise when the same meet PDF is posted on
    multiple teams' schedule pages (e.g. SCIAC Championships appears 9 times).

    Dedup key: (gender, event_name, name, school, norm_finals, relay_leg)
    Finals are normalised (qualifier symbols stripped) before comparison so
    that '1:21.57#' and '1:21.57' are treated as the same result.
    The first occurrence of each key is kept.
    """
    seen: set[tuple] = set()
    out: list[SwimResult] = []
    for r in results:
        key = (r.gender, r.event_name, r.name, r.school,
               _norm_finals(r.finals), r.relay_leg)
        if key not in seen:
            seen.add(key)
            out.append(r)
    removed = len(results) - len(out)
    if removed:
        logger.info("Deduplication removed %d duplicate rows (%d → %d)",
                    removed, len(results), len(out))
    return out


def _filter_sciac(results: list[SwimResult]) -> list[SwimResult]:
    """Keep only results where the school is a SCIAC member institution."""
    out = [r for r in results if is_sciac_school(r.school)]
    removed = len(results) - len(out)
    if removed:
        logger.info("SCIAC filter removed %d non-SCIAC rows (%d → %d)",
                    removed, len(results), len(out))
    return out


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _write_csv(records: list[dict], path: Path) -> None:
    if not records:
        logger.warning("No records to write to %s", path)
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    logger.info("CSV written: %s (%d rows)", path, len(records))


def _write_json(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    logger.info("JSON written: %s (%d records)", path, len(records))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Swimplex — SCIAC swim/dive data pipeline")
    ap.add_argument("--scrape", action="store_true", help="Download PDFs from team sites")
    ap.add_argument("--parse",  action="store_true", help="Parse downloaded PDFs into CSV/JSON")
    ap.add_argument("--season", type=str, default=None, metavar="YYYY-YY",
                    help="Season to scrape/parse, e.g. 2025-26 (derives --start/--end "
                         "and names the output folder data/<season>/)")
    ap.add_argument("--start",  type=_parse_date, default=None, metavar="YYYY-MM-DD",
                    help=f"Season start date override (default: {SEASON_START})")
    ap.add_argument("--end",    type=_parse_date, default=None, metavar="YYYY-MM-DD",
                    help=f"Season end date override (default: {SEASON_END})")
    ap.add_argument("--pdf-dir", type=Path, default=None,
                    help="Directory containing PDFs to parse (default: data/<season>/pdfs/)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output directory for CSV/JSON (default: data/<season>/)")
    ap.add_argument("--no-sciac-filter", action="store_true",
                    help="Include non-SCIAC schools in output (disabled by default)")
    args = ap.parse_args()

    # ── Resolve date range and season string ──────────────────────────────────
    if args.season:
        try:
            start, end = _season_dates(args.season)
        except argparse.ArgumentTypeError as e:
            ap.error(str(e))
        season = args.season
    else:
        start  = args.start or SEASON_START
        end    = args.end   or SEASON_END
        season = _season_str(start, end)

    # ── Output and PDF directories ────────────────────────────────────────────
    out_dir = args.out or (_BASE_DATA_DIR / season)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = args.pdf_dir or (out_dir / "pdfs")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # ── Default: run both steps ───────────────────────────────────────────────
    run_scrape = args.scrape or not (args.scrape or args.parse)
    run_parse  = args.parse  or not (args.scrape or args.parse)

    if run_scrape:
        logger.info("--- SCRAPE: downloading PDFs for %s to %s ---", start, end)
        pdfs = scrape_all_teams(start=start, end=end, season=season, pdf_dir=pdf_dir)
        logger.info("Downloaded %d PDF(s).", len(pdfs))

    if run_parse:
        logger.info("--- PARSE: extracting results from PDFs ---")
        results = parse_all_pdfs(pdf_dir=pdf_dir)
        if not results:
            logger.warning("No results found. Check that PDFs exist and were parsed correctly.")
            sys.exit(0)

        # Filter to SCIAC schools only (unless bypassed)
        if not args.no_sciac_filter:
            results = _filter_sciac(results)

        # Remove cross-PDF duplicates
        results = _deduplicate(results)

        if not results:
            logger.warning("No results remain after filtering/deduplication.")
            sys.exit(0)

        records = [result_to_dict(r) for r in results]
        _write_csv(records,  out_dir / "results.csv")
        _write_json(records, out_dir / "results.json")


if __name__ == "__main__":
    main()
