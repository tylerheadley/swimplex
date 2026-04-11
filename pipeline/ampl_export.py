#!/usr/bin/env python3
"""
ampl_export.py — Convert best_performances_<gender>.json to AMPL .dat format.

Matches model/Swimplex_time_upV6.mod. Defines all sets and parameters
required by the model:
  Sets:    Events, Athletes, Team, AthletesTeam, SoloEvents, RelayEvents, MedleyEvents
  Params:  solo_time, leg_time, leg_time_med, solo_points, relay_points,
           relay_enroll_ct, home_team

Usage:
    python3 ampl_export.py --season 2025-26 --gender Men
    python3 ampl_export.py --season 2025-26 --gender Women [--home-team 'Cal Lutheran']
"""

import argparse
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = _PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# SCIAC configuration
# ---------------------------------------------------------------------------

SCIAC_TEAMS = [
    "Claremont-Mudd-Scripps",
    "Cal Lutheran",
    "Caltech",
    "Chapman",
    "Occidental",
    "Pomona-Pitzer",
    "La Verne",
    "Redlands",
    "Whittier",
]

_DEFAULT_HOME_TEAM = "Claremont-Mudd-Scripps"

DIVE_SENTINEL = 0.0   # missing diving score sentinel (higher score = better)

# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

# Individual events (SoloEvents in .mod): AMPL id → JSON event key
SOLO_EVENTS: dict[str, str] = {
    "free50":    "50 Yard Freestyle",
    "free100":   "100 Yard Freestyle",
    "free200":   "200 Yard Freestyle",
    "free500":   "500 Yard Freestyle",
    "free1000":  "1000 Yard Freestyle",
    "free1650":  "1650 Yard Freestyle",
    "back100":   "100 Yard Backstroke",
    "back200":   "200 Yard Backstroke",
    "breast100": "100 Yard Breaststroke",
    "breast200": "200 Yard Breaststroke",
    "fly100":    "100 Yard Butterfly",
    "fly200":    "200 Yard Butterfly",
    "im200":     "200 Yard IM",
    "im400":     "400 Yard IM",
}

# Freestyle relay events (RelayEvents in .mod): AMPL id → JSON key for the leg split
# Each relay uses the individual leg split as leg_time.
RELAY_EVENTS: dict[str, str] = {
    "FR200": "50 Yard Freestyle (Relay Split)",   # 4 × 50
    "FR400": "100 Yard Freestyle (Relay Split)",  # 4 × 100
    "FR800": "200 Yard Freestyle (Relay Split)",  # 4 × 200
}

# Medley relay events (MedleyEvents in .mod): AMPL id → {Stroke → JSON key}
# Stroke set in .mod: {"Free", "Back", "Breast", "Fly"}
# NOTE: "100 Yard Backstroke (Relay Split)" is not tracked separately in the
# pipeline — the individual "100 Yard Backstroke" is used as the best proxy for
# the 400 medley back leg.
MEDLEY_EVENTS: dict[str, dict[str, str]] = {
    "MED200": {  # 4 × 50 medley relay
        "Back":   "50 Yard Backstroke",                  # leadoff (relay_leg=1)
        "Breast": "50 Yard Breaststroke (Relay Split)",
        "Fly":    "50 Yard Butterfly (Relay Split)",
        "Free":   "50 Yard Freestyle (Relay Split)",
    },
    "MED400": {  # 4 × 100 medley relay
        "Back":   "100 Yard Backstroke",                 # individual time (best proxy)
        "Breast": "100 Yard Breaststroke (Relay Split)",
        "Fly":    "100 Yard Butterfly (Relay Split)",
        "Free":   "100 Yard Freestyle (Relay Split)",
    },
}

STROKES = ["Back", "Breast", "Fly", "Free"]   # must match .mod Stroke set

# Diving events (DivingEvents in .mod): AMPL id → JSON event key
DIVE_EVENTS: dict[str, str] = {
    "dive1m": "1 mtr Diving",
    "dive3m": "3 mtr Diving",
}

# ---------------------------------------------------------------------------
# SCIAC scoring
# NOTE: Verify these values against the official SCIAC championship scoring
# sheet before running the optimisation model.
# ---------------------------------------------------------------------------

# Individual events: A final (places 1–8), B final (places 9–16).
# Places 17+ use the 1/rank heuristic (fractional credit, keeps objective smooth).
# NOTE: Verify top-16 values against official SCIAC championship scoring sheet.
SOLO_POINTS: dict[int, int] = {
    1: 20, 2: 17, 3: 16, 4: 15, 5: 14, 6: 13, 7: 12, 8: 11,
    9:  9, 10: 7, 11:  6, 12:  5, 13:  4, 14:  3, 15:  2, 16:  1,
}

# Relay scoring: 2× individual points at each overall placement (1–16), then 0.
# A heat (9 teams) → overall places 1–9  → relay_points[p, 'A'] = 2×solo[p]
# B heat (9 teams) → overall places 10–18 → relay_points[p, 'B'] = 2×solo[p+9]
# B heat places 8–9 (overall 17–18) score 0.
_SOLO_PTS_LIST = [20, 17, 16, 15, 14, 13, 12, 11, 9, 7, 6, 5, 4, 3, 2, 1]  # places 1–16

def _relay_pts_a(p: int) -> int:
    """Points for finishing in place p of the A relay heat (p = 1..card(Team))."""
    return 2 * _SOLO_PTS_LIST[p - 1] if 1 <= p <= len(_SOLO_PTS_LIST) else 0

def _relay_pts_b(p: int) -> int:
    """Points for finishing in place p of the B relay heat (overall place = p+9)."""
    overall = p + 9
    return 2 * _SOLO_PTS_LIST[overall - 1] if 1 <= overall <= len(_SOLO_PTS_LIST) else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_time(s: str, sentinel: float = 9999.0) -> float:
    """Convert a time string ('1:54.66', '22.14') to seconds, or sentinel."""
    s = s.strip()
    if s.upper().startswith("NT"):
        s = s[2:].lstrip("xX ").strip()
    if not s or s.upper() in {"NT", "DQ", "NP", "NS", "SCR", "---", "DNF", "DFS"}:
        return sentinel
    if ":" in s:
        mins, rest = s.split(":", 1)
        try:
            return int(mins) * 60 + float(rest)
        except ValueError:
            return sentinel
    try:
        return float(s)
    except ValueError:
        return sentinel


def q(s: str) -> str:
    """Single-quote a string for AMPL; escapes internal apostrophes by doubling."""
    return "'" + s.replace("'", "''") + "'"


def fmt(val: float, sentinel: float) -> str:
    """Format a value; use sentinel representation when the value equals the sentinel."""
    if sentinel == DIVE_SENTINEL:
        # Diving: sentinel is 0 (missing = no score); real scores are positive
        return str(int(sentinel)) if val <= sentinel else f"{val:.2f}"
    return str(int(sentinel)) if val >= sentinel else f"{val:.2f}"


# ---------------------------------------------------------------------------
# .dat writer
# ---------------------------------------------------------------------------

def write_dat(
    out_path: Path,
    season: str,
    gender: str,
    athletes: list[str],
    team_athletes: dict[str, list[str]],
    solo_time: dict[str, dict[str, float]],
    leg_time: dict[str, dict[str, float]],
    leg_time_med: dict[str, dict[str, dict[str, float]]],
    diving_score: dict[str, dict[str, float]],
    home_team: str,
    sentinel: float,
) -> None:

    lines: list[str] = []
    W = 78

    def sec(title: str) -> None:
        lines.append("")
        lines.append(f"# {'─' * W}")
        lines.append(f"# {title}")
        lines.append(f"# {'─' * W}")
        lines.append("")

    lines.append(f"# AMPL data file — Swimplex SCIAC {season} {gender}")
    lines.append(f"# Generated by pipeline/ampl_export.py")
    lines.append(f"# Model: Swimplex_time_upV6.mod")
    lines.append(f"# Sentinel value for missing times: {int(sentinel)}")

    solo_ids   = list(SOLO_EVENTS.keys())
    relay_ids  = list(RELAY_EVENTS.keys())
    medley_ids = list(MEDLEY_EVENTS.keys())
    dive_ids   = list(DIVE_EVENTS.keys())

    # ── Sets ─────────────────────────────────────────────────────────────────
    sec("Event sets")

    lines.append("set SoloEvents :=")
    lines.append("  " + "  ".join(solo_ids) + " ;")
    lines.append("")
    lines.append("set RelayEvents :=")
    lines.append("  " + "  ".join(relay_ids) + " ;")
    lines.append("")
    lines.append("set MedleyEvents :=")
    lines.append("  " + "  ".join(medley_ids) + " ;")
    lines.append("")
    lines.append("set DivingEvents :=")
    lines.append("  " + "  ".join(dive_ids) + " ;")
    lines.append("")
    all_event_ids = solo_ids + relay_ids + medley_ids + dive_ids
    lines.append("set Events :=")
    lines.append("  " + "  ".join(all_event_ids) + " ;")

    sec("Team and athlete sets")

    lines.append("set Team :=")
    for t in SCIAC_TEAMS:
        lines.append(f"  {q(t)}")
    lines.append("  ;")
    lines.append("")

    for t in SCIAC_TEAMS:
        members = team_athletes.get(t, [])
        lines.append(f"set AthletesTeam[{q(t)}] :=")
        for ath in members:
            lines.append(f"  {q(ath)}")
        lines.append("  ;")
        lines.append("")

    lines.append("set Athletes :=")
    for ath in athletes:
        lines.append(f"  {q(ath)}")
    lines.append("  ;")

    # ── Scalar params ─────────────────────────────────────────────────────────
    sec("Scalar parameters")

    lines.append(f"param home_team := {q(home_team)} ;")

    # ── Scoring ───────────────────────────────────────────────────────────────
    sec("Scoring  (NOTE: verify against official SCIAC championship sheet)")

    n_athletes = len(athletes)
    n_teams    = len(SCIAC_TEAMS)

    lines.append("# Individual: top 16 per SCIAC rules; 1/rank heuristic for places 17+")
    lines.append("param solo_points default 0 :=")
    for p in range(1, n_athletes + 1):
        pts = SOLO_POINTS[p] if p in SOLO_POINTS else 1.0 / p
        lines.append(f"  [{p}]  {pts}")
    lines.append("  ;")
    lines.append("")

    lines.append("# Relay: 2× individual points; A heat → overall 1–9, B heat → overall 10–18")
    a_vals  = [_relay_pts_a(p) for p in range(1, n_teams + 1)]
    b_vals  = [_relay_pts_b(p) for p in range(1, n_teams + 1)]
    pts_w   = max(len(str(v)) for v in a_vals + b_vals)
    place_w = len(str(n_teams))
    lines.append(f"param relay_points default 0 :")
    lines.append(f"  {'':>{place_w}}  {'A':>{pts_w}}  {'B':>{pts_w}} :=")
    for p in range(1, n_teams + 1):
        lines.append(f"  {p:>{place_w}}  {_relay_pts_a(p):>{pts_w}}  {_relay_pts_b(p):>{pts_w}}")
    lines.append("  ;")

    # ── solo_time ────────────────────────────────────────────────────────────
    sec(f"Individual event times  —  param solo_time {{Athletes, SoloEvents}}")

    def _table_2d(param_name: str, row_names: list[str], col_ids: list[str],
                  data: dict[str, dict[str, float]]) -> None:
        col_w = {c: len(c) for c in col_ids}
        for r in row_names:
            for c in col_ids:
                col_w[c] = max(col_w[c], len(fmt(data[r][c], sentinel)))
        name_w = max(len(q(n)) for n in row_names) if row_names else 10

        lines.append(f"param {param_name} default {int(sentinel)} :")
        header = "  ".join(c.ljust(col_w[c]) for c in col_ids)
        lines.append(f"  {'':>{name_w}}  {header}  :=")
        for r in row_names:
            vals = "  ".join(fmt(data[r][c], sentinel).rjust(col_w[c]) for c in col_ids)
            lines.append(f"  {q(r).ljust(name_w)}  {vals}")
        lines.append("  ;")

    _table_2d("solo_time", athletes, solo_ids, solo_time)

    # ── leg_time ─────────────────────────────────────────────────────────────
    sec(f"Freestyle relay leg times  —  param leg_time {{Athletes, RelayEvents}}")
    _table_2d("leg_time", athletes, relay_ids, leg_time)

    # ── leg_time_med ─────────────────────────────────────────────────────────
    sec(f"Medley relay leg times  —  param leg_time_med {{Athletes, MedleyEvents, Stroke}}")

    stroke_col_w = {s: len(s) for s in STROKES}
    for ath in athletes:
        for med in medley_ids:
            for s in STROKES:
                stroke_col_w[s] = max(stroke_col_w[s],
                                      len(fmt(leg_time_med[ath][med][s], sentinel)))
    name_w = max(len(q(n)) for n in athletes) if athletes else 10

    lines.append(f"param leg_time_med default {int(sentinel)} :=")
    for med in medley_ids:
        header = "  ".join(s.ljust(stroke_col_w[s]) for s in STROKES)
        lines.append(f"  [*, {med}, *] :  {header}  :=")
        for ath in athletes:
            vals = "  ".join(
                fmt(leg_time_med[ath][med][s], sentinel).rjust(stroke_col_w[s])
                for s in STROKES
            )
            lines.append(f"  {q(ath).ljust(name_w)}  {vals}")
        lines.append("")
    lines.append("  ;")

    # ── diving_score ──────────────────────────────────────────────────────────
    sec(f"Diving scores  —  param diving_score {{Athletes, DivingEvents}}  (sentinel {int(DIVE_SENTINEL)} = no score)")

    col_w = {d: len(d) for d in dive_ids}
    for ath in athletes:
        for d in dive_ids:
            col_w[d] = max(col_w[d], len(fmt(diving_score[ath][d], DIVE_SENTINEL)))
    name_w = max(len(q(n)) for n in athletes) if athletes else 10

    lines.append(f"param diving_score default {int(DIVE_SENTINEL)} :")
    header = "  ".join(d.ljust(col_w[d]) for d in dive_ids)
    lines.append(f"  {'':>{name_w}}  {header}  :=")
    for ath in athletes:
        vals = "  ".join(fmt(diving_score[ath][d], DIVE_SENTINEL).rjust(col_w[d]) for d in dive_ids)
        lines.append(f"  {q(ath).ljust(name_w)}  {vals}")
    lines.append("  ;")

    out_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export best_performances JSON to AMPL .dat (Swimplex_time_upV6.mod)"
    )
    ap.add_argument("--season",    required=True, metavar="YYYY-YY")
    ap.add_argument("--gender",    required=True, choices=["Men", "Women", "Mixed"])
    ap.add_argument("--home-team", default=_DEFAULT_HOME_TEAM,
                    help=f"Home team (default: {_DEFAULT_HOME_TEAM!r})")
    ap.add_argument("--sentinel",  type=float, default=9999.0,
                    help="Placeholder for missing times (default: 9999)")
    args = ap.parse_args()

    in_path = DATA_DIR / args.season / f"best_performances_{args.gender.lower()}.json"
    if not in_path.exists():
        ap.error(
            f"Input not found: {in_path}\n"
            f"Run:  python3 best_performances.py --season {args.season} --gender {args.gender}"
        )

    data = json.loads(in_path.read_text())
    swimmers_raw = data["swimmers"]

    # Collect athletes per SCIAC team; include divers
    team_athletes: dict[str, list[str]] = {t: [] for t in SCIAC_TEAMS}
    for name, info in swimmers_raw.items():
        school = info.get("school", "")
        if school not in SCIAC_TEAMS:
            continue
        team_athletes[school].append(name)

    for t in SCIAC_TEAMS:
        team_athletes[t].sort()

    # Ordered athlete list: team by team, alphabetical within
    athletes: list[str] = []
    for t in SCIAC_TEAMS:
        athletes.extend(team_athletes[t])

    sentinel = args.sentinel

    # ── Build time matrices ───────────────────────────────────────────────────
    solo_time:    dict[str, dict[str, float]] = {}
    leg_time:     dict[str, dict[str, float]] = {}
    leg_time_med: dict[str, dict[str, dict[str, float]]] = {}
    diving_score: dict[str, dict[str, float]] = {}

    for ath in athletes:
        ev = swimmers_raw[ath]["events"]

        solo_time[ath] = {
            eid: parse_time(ev[jk]["best"], sentinel) if jk in ev else sentinel
            for eid, jk in SOLO_EVENTS.items()
        }
        leg_time[ath] = {
            eid: parse_time(ev[jk]["best"], sentinel) if jk in ev else sentinel
            for eid, jk in RELAY_EVENTS.items()
        }
        leg_time_med[ath] = {
            med: {
                stroke: parse_time(ev[jk]["best"], sentinel) if jk in ev else sentinel
                for stroke, jk in stroke_map.items()
            }
            for med, stroke_map in MEDLEY_EVENTS.items()
        }
        diving_score[ath] = {
            eid: parse_time(ev[jk]["best"], DIVE_SENTINEL) if jk in ev else DIVE_SENTINEL
            for eid, jk in DIVE_EVENTS.items()
        }

    out_path = DATA_DIR / args.season / f"best_performances_{args.gender.lower()}.dat"
    write_dat(out_path, args.season, args.gender, athletes, team_athletes,
              solo_time, leg_time, leg_time_med, diving_score, args.home_team, sentinel)

    # ── Summary ───────────────────────────────────────────────────────────────
    def missing(d2, s): return sum(1 for a in athletes for v in d2[a].values() if v == s)
    def missing3(d3): return sum(
        1 for a in athletes
        for med in MEDLEY_EVENTS
        for v in d3[a][med].values() if v >= sentinel
    )
    def missing_dive(d2): return sum(1 for a in athletes for v in d2[a].values() if v <= DIVE_SENTINEL)
    total_solo = len(athletes) * len(SOLO_EVENTS)
    total_leg  = len(athletes) * len(RELAY_EVENTS)
    total_med  = len(athletes) * len(MEDLEY_EVENTS) * len(STROKES)
    total_dive = len(athletes) * len(DIVE_EVENTS)

    n_divers = sum(1 for a in athletes if swimmers_raw[a].get("type") == "diver")
    print(f"Written: {out_path}")
    print(f"  {len(athletes)} athletes across {sum(1 for t in SCIAC_TEAMS if team_athletes[t])} teams"
          f"  ({n_divers} pure divers)")
    for t in SCIAC_TEAMS:
        n = len(team_athletes[t])
        if n:
            print(f"    {t}: {n}")
    print(f"  solo_time:    {missing(solo_time, sentinel)}/{total_solo} sentinel ({missing(solo_time, sentinel)/total_solo*100:.1f}% missing)")
    print(f"  leg_time:     {missing(leg_time, sentinel)}/{total_leg} sentinel ({missing(leg_time, sentinel)/total_leg*100:.1f}% missing)")
    print(f"  leg_time_med: {missing3(leg_time_med)}/{total_med} sentinel ({missing3(leg_time_med)/total_med*100:.1f}% missing)")
    print(f"  diving_score: {missing_dive(diving_score)}/{total_dive} sentinel ({missing_dive(diving_score)/total_dive*100:.1f}% missing)")


if __name__ == "__main__":
    main()
