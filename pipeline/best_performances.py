#!/usr/bin/env python3
"""
best_performances.py — Extract each SCIAC athlete's season-best in every event.

Reads from the already-processed athlete_profiles_<gender>.json produced by
process_results.py (rank "1" entry per athlete-event is the season best).

Usage:
    python3 best_performances.py --season 2025-26 --gender Men
    python3 best_performances.py --season 2025-26 --gender Women

Output:
    data/<season>/best_performances_<gender>.json

Run process_results.py first to generate athlete_profiles_<gender>.json.
"""

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from config import is_relevant_event


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract per-athlete season bests from athlete_profiles output"
    )
    ap.add_argument("--season", required=True, metavar="YYYY-YY",
                    help="Season to process, e.g. 2025-26")
    ap.add_argument("--gender", required=True, choices=["Men", "Women", "Mixed"],
                    help="Gender division to process")
    args = ap.parse_args()

    profiles_path = DATA_DIR / args.season / f"athlete_profiles_{args.gender.lower()}.json"
    if not profiles_path.exists():
        ap.error(
            f"Athlete profiles not found: {profiles_path}\n"
            f"Run:  python3 process_results.py --season {args.season} --gender {args.gender}"
        )

    data = json.loads(profiles_path.read_text())

    swimmers_out: dict[str, dict] = {}
    for name, info in data["athletes"].items():
        events_out: dict[str, dict] = {}
        for event, perfs in info["events"].items():
            if not is_relevant_event(event):
                continue
            best_entry = perfs.get("1")
            if best_entry is None:
                continue
            # "time" for swim events, "score" (float) for diving
            raw_val = best_entry.get("time")
            if raw_val is None:
                raw_val = str(best_entry["score"])
            entry: dict = {
                "best":  raw_val,
                "meet":  best_entry["meet"],
                "date":  best_entry["date"],
                "place": best_entry["place"],
            }
            if "relay_leg" in best_entry:
                entry["relay_leg"] = best_entry["relay_leg"]
            if "dive_format" in best_entry:
                entry["dive_format"]      = best_entry["dive_format"]
                entry["dive_format_conf"] = best_entry["dive_format_conf"]
            events_out[event] = entry

        swimmers_out[name] = {
            "school": info["school"],
            "age":    info["age"],
            "type":   info.get("type", "swimmer"),
            "events": events_out,
        }

    output = {
        "season":   args.season,
        "gender":   args.gender,
        "swimmers": swimmers_out,
    }

    out_path = DATA_DIR / args.season / f"best_performances_{args.gender.lower()}.json"
    out_path.write_text(json.dumps(output, indent=2))

    n_swimmers = len(swimmers_out)
    n_bests    = sum(len(v["events"]) for v in swimmers_out.values())
    print(f"Written: {out_path}")
    print(f"  {n_swimmers} athletes,  {n_bests} season-best entries")


if __name__ == "__main__":
    main()
