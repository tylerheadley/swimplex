#!/usr/bin/env python3
"""
run_iterative.py — End-to-end Swimplex workflow:
  1. Pipeline: process_results → best_performances → ampl_export (with optional date cutoff)
  2. Greedy rosters for all 9 SCIAC teams
  3. AMPL optimization: for each team, fix 8 opponents to greedy, optimize the 9th
  4. Iterative best response between CMS and Pomona-Pitzer

Usage:
    # Full run with date cutoff before SCIAC champs:
    python3 model/run_iterative.py --season 2025-26 --gender Men --date-to 2026-02-17

    # Skip pipeline, use existing data:
    python3 model/run_iterative.py --season 2025-26 --gender Men --skip-pipeline

    # Only run iterative best response (skip step 3 full sweep):
    python3 model/run_iterative.py --season 2025-26 --gender Men --skip-pipeline --skip-all-teams
"""

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

try:
    import psutil as _psutil
    _PROC = _psutil.Process(os.getpid())
    def _rss_mb() -> float:
        return _PROC.memory_info().rss / 1024 ** 2
except ImportError:
    def _rss_mb() -> float:
        return 0.0

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from amplpy import AMPL, add_to_path
add_to_path("/Applications/AMPL")

from pipeline.ampl_export import (
    SOLO_EVENTS, RELAY_EVENTS, MEDLEY_EVENTS, DIVE_EVENTS, STROKES, SCIAC_TEAMS,
)
from model.greedy_rosters import (
    load_json_from_data, build_performance_entries,
    greedy_rosters as build_greedy_rosters,
    greedy_relay_assignment, evaluate_rosters, evaluate_relay_scores,
)

# ---------------------------------------------------------------------------
# Reverse maps: full event name → AMPL id
# ---------------------------------------------------------------------------
SOLO_REV: dict[str, str] = {v: k for k, v in SOLO_EVENTS.items()}
DIVE_REV: dict[str, str] = {v: k for k, v in DIVE_EVENTS.items()}

DATA_DIR = REPO_ROOT / "data"
DEFAULT_MOD = REPO_ROOT / "model" / "Swimplex_time.mod"


def q(s: str) -> str:
    """Single-quote a string for AMPL; doubles internal apostrophes."""
    return "'" + s.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Step 1: Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(season: str, gender: str, date_to: str | None = None) -> None:
    """Run process_results + best_performances + ampl_export."""
    base = [sys.executable]
    pr_args = base + [str(REPO_ROOT / "pipeline" / "process_results.py"),
                      "--season", season, "--gender", gender]
    if date_to:
        pr_args += ["--date-to", date_to]

    bp_args = base + [str(REPO_ROOT / "pipeline" / "best_performances.py"),
                      "--season", season, "--gender", gender]

    ae_args = base + [str(REPO_ROOT / "pipeline" / "ampl_export.py"),
                      "--season", season, "--gender", gender]

    for label, cmd in [("process_results", pr_args),
                       ("best_performances", bp_args),
                       ("ampl_export", ae_args)]:
        print(f"  Running {label} …")
        subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Step 2: Greedy rosters
# ---------------------------------------------------------------------------

def load_greedy(bp_path: str):
    """Load best_performances JSON → greedy rosters + relay assignments."""
    data, path = load_json_from_data(bp_path)
    swimmers = data.get("swimmers", {})
    entries = build_performance_entries(swimmers)
    print(f"  {len(entries)} performance entries across "
          f"{len({e['event'] for e in entries})} events.")
    rosters = build_greedy_rosters(entries)
    relay_assignments = greedy_relay_assignment(rosters, swimmers)
    return rosters, relay_assignments, swimmers


# ---------------------------------------------------------------------------
# AMPL helpers: fix / unfix / extract
# ---------------------------------------------------------------------------

def fix_team_to_greedy(ampl: AMPL, team: str, roster: dict, relay_data: dict) -> None:
    """Set and fix all decision variables for *team* to its greedy roster."""
    athletes_info = roster.get("athletes", {})
    qt = q(team)

    # Zero everything out first
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in SoloEvents}} "
              f"athlete_swims_event_solo[a,e] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in DivingEvents}} "
              f"athlete_dives_event[a,e] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} "
              f"athlete_swims_event_rel[a,e,l] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} "
              f"athlete_swims_event_med[a,e,l,s] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_scorer[a] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_diver_only[a] := 0;")

    # Set assigned individual events to 1
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")

        for assignment in ath_data.get("assignments", []):
            evt_name = assignment["event"]
            if evt_name in SOLO_REV:
                ampl.eval(f"let athlete_swims_event_solo[{qa}, "
                          f"'{SOLO_REV[evt_name]}'] := 1;")
            elif evt_name in DIVE_REV:
                ampl.eval(f"let athlete_dives_event[{qa}, "
                          f"'{DIVE_REV[evt_name]}'] := 1;")

    # Set assigned freestyle relay legs to 1
    for relay_id in RELAY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(relay_id, {}).get(heat)
            if heat_info and heat_info.get("legs"):
                for leg in heat_info["legs"]:
                    qa = q(leg["name"])
                    ampl.eval(f"let athlete_swims_event_rel[{qa}, "
                              f"'{relay_id}', '{heat}'] := 1;")

    # Set assigned medley relay legs to 1
    for med_id in MEDLEY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(med_id, {}).get(heat)
            if heat_info and heat_info.get("legs"):
                for leg in heat_info["legs"]:
                    qa = q(leg["name"])
                    stroke = leg["stroke"]
                    ampl.eval(f"let athlete_swims_event_med[{qa}, "
                              f"'{med_id}', '{heat}', '{stroke}'] := 1;")

    # Fix relay_enroll and med_relay_enroll for this team
    # (avoids presolve conflicts with is_team_faster when total_rel_time = 0)
    for relay_id in RELAY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(relay_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs")
                            and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")

    for med_id in MEDLEY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(med_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs")
                            and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix med_relay_enroll[{qt}, '{med_id}', '{heat}'];")

    # Fix everything for this team
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in SoloEvents}} "
              f"athlete_swims_event_solo[a,e];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in DivingEvents}} "
              f"athlete_dives_event[a,e];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} "
              f"athlete_swims_event_rel[a,e,l];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} "
              f"athlete_swims_event_med[a,e,l,s];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")


def unfix_team(ampl: AMPL, team: str) -> None:
    """Unfix all decision variables for *team*."""
    qt = q(team)
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}], e in SoloEvents}} "
              f"athlete_swims_event_solo[a,e];")
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}], e in DivingEvents}} "
              f"athlete_dives_event[a,e];")
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} "
              f"athlete_swims_event_rel[a,e,l];")
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} "
              f"athlete_swims_event_med[a,e,l,s];")
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"unfix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")
    ampl.eval(f"unfix {{r in RelayEvents, l in Level}} relay_enroll[{qt},r,l];")
    ampl.eval(f"unfix {{e in MedleyEvents, l in Level}} med_relay_enroll[{qt},e,l];")


def warmstart_team(ampl: AMPL, team: str, roster: dict, relay_data: dict) -> None:
    """Set (but do NOT fix) home team decision variables to greedy values as MIP warm start."""
    athletes_info = roster.get("athletes", {})
    qt = q(team)

    # Zero everything out first
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in SoloEvents}} "
              f"athlete_swims_event_solo[a,e] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in DivingEvents}} "
              f"athlete_dives_event[a,e] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} "
              f"athlete_swims_event_rel[a,e,l] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} "
              f"athlete_swims_event_med[a,e,l,s] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_scorer[a] := 0;")
    ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_diver_only[a] := 0;")
    ampl.eval(f"let {{r in RelayEvents, l in Level}} relay_enroll[{qt},r,l] := 0;")
    ampl.eval(f"let {{e in MedleyEvents, l in Level}} med_relay_enroll[{qt},e,l] := 0;")

    # Set individual event assignments
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")

        for assignment in ath_data.get("assignments", []):
            evt_name = assignment["event"]
            if evt_name in SOLO_REV:
                ampl.eval(f"let athlete_swims_event_solo[{qa}, "
                          f"'{SOLO_REV[evt_name]}'] := 1;")
            elif evt_name in DIVE_REV:
                ampl.eval(f"let athlete_dives_event[{qa}, "
                          f"'{DIVE_REV[evt_name]}'] := 1;")

    # Set freestyle relay participants and relay_enroll
    for relay_id in RELAY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(relay_id, {}).get(heat)
            if heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4:
                ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := 1;")
                for leg in heat_info["legs"]:
                    qa = q(leg["name"])
                    ampl.eval(f"let athlete_swims_event_rel[{qa}, "
                              f"'{relay_id}', '{heat}'] := 1;")

    # Set medley relay participants and med_relay_enroll
    for med_id in MEDLEY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay_data.get(med_id, {}).get(heat)
            if heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4:
                ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := 1;")
                for leg in heat_info["legs"]:
                    qa = q(leg["name"])
                    stroke = leg["stroke"]
                    ampl.eval(f"let athlete_swims_event_med[{qa}, "
                              f"'{med_id}', '{heat}', '{stroke}'] := 1;")


def extract_roster(ampl: AMPL, team: str) -> tuple[dict, dict]:
    """Read the solved roster for *team* from AMPL and return
    (roster_dict, relay_dict) in the same format that fix_team_to_greedy expects.
    """
    team_athletes = (ampl.get_set("AthletesTeam").get(team)
                     .getValues().toList())

    solo_vals = ampl.get_variable("athlete_swims_event_solo").get_values().to_dict()
    dive_vals = ampl.get_variable("athlete_dives_event").get_values().to_dict()
    rel_vals  = ampl.get_variable("athlete_swims_event_rel").get_values().to_dict()
    med_vals  = ampl.get_variable("athlete_swims_event_med").get_values().to_dict()
    scorer_vals     = ampl.get_variable("is_scorer").get_values().to_dict()
    diver_only_vals = ampl.get_variable("is_diver_only").get_values().to_dict()

    roster: dict = {"athletes": {}, "budget_used": 0}

    for ath in team_athletes:
        if scorer_vals.get(ath, 0) < 0.5:
            continue
        is_diver = diver_only_vals.get(ath, 0) > 0.5
        assignments: list[dict] = []

        for ampl_id, json_name in SOLO_EVENTS.items():
            if solo_vals.get((ath, ampl_id), 0) > 0.5:
                assignments.append({"event": json_name})
        for ampl_id, json_name in DIVE_EVENTS.items():
            if dive_vals.get((ath, ampl_id), 0) > 0.5:
                assignments.append({"event": json_name})

        if assignments or is_diver:
            roster["athletes"][ath] = {
                "type": "diver" if is_diver else "swimmer",
                "assignments": assignments,
            }

    # Relay assignments
    relay_out: dict = {}
    for relay_id in RELAY_EVENTS:
        relay_out[relay_id] = {}
        for heat in ["A", "B"]:
            legs = []
            for ath in team_athletes:
                if rel_vals.get((ath, relay_id, heat), 0) > 0.5:
                    legs.append({"name": ath, "leg": len(legs) + 1})
            relay_out[relay_id][heat] = {"legs": legs} if legs else None

    for med_id in MEDLEY_EVENTS:
        relay_out[med_id] = {}
        for heat in ["A", "B"]:
            legs = []
            for stroke in STROKES:
                for ath in team_athletes:
                    if med_vals.get((ath, med_id, heat, stroke), 0) > 0.5:
                        legs.append({"name": ath, "stroke": stroke,
                                     "leg": len(legs) + 1})
                        break
            relay_out[med_id][heat] = {"legs": legs} if len(legs) == 4 else None

    return roster, relay_out


# ---------------------------------------------------------------------------
# Step 3 / 4: Optimize one team
# ---------------------------------------------------------------------------

def optimize_team(
    ampl: AMPL,
    home_team: str,
    all_rosters: dict[str, dict],
    all_relays: dict[str, dict],
    solver: str = "gurobi",
    time_limit: int | None = None,
    mip_gap: float = 0.025,
) -> tuple[float | None, dict | None, dict | None, dict]:
    """Fix 8 opponents, optimise *home_team*.
    Returns (obj, roster, relays, solve_record).
    solve_record always present (contains result/timing even on infeasible).
    """

    print(f"\n{'─'*60}")
    print(f"  Optimising: {home_team}")
    print(f"{'─'*60}")

    t_start = time.perf_counter()
    ram_before = _rss_mb()

    # Reset: unfix everything so prior iteration state is cleared
    ampl.eval("unfix;")

    # Fix every team except home_team to its current roster
    for team in SCIAC_TEAMS:
        if team == home_team:
            continue
        fix_team_to_greedy(
            ampl, team,
            all_rosters.get(team, {"athletes": {}}),
            all_relays.get(team, {}),
        )

    # Set home_team param and objective
    ampl.param["home_team"] = home_team
    ampl.eval("objective TotalPoints;")

    # Warm-start home team from its current greedy/optimised roster
    warmstart_team(
        ampl, home_team,
        all_rosters.get(home_team, {"athletes": {}}),
        all_relays.get(home_team, {}),
    )

    # Disable AMPL presolve; let solver handle it directly
    ampl.set_option("presolve", 0)

    # Solver options (single call — multiple calls replace, not append)
    ampl.set_option("solver", solver)
    if solver == "gurobi":
        opts = f"outlev=1 mipgap={mip_gap} iisfind=1"
        if time_limit:
            opts += f" timelim={time_limit}"
        ampl.set_option("gurobi_options", opts)

    ampl.solve()
    solve_result = str(ampl.get_value("solve_result"))
    runtime_s = time.perf_counter() - t_start
    ram_after = _rss_mb()

    print(f"  Solve result: {solve_result}  ({runtime_s:.1f}s)")

    solve_record = {
        "result":    solve_result,
        "runtime_s": round(runtime_s, 2),
        "ram_before_mb": round(ram_before, 1),
        "ram_after_mb":  round(ram_after, 1),
        "obj": None,
        "mip_gap": None,
    }

    if "infeasible" in solve_result:
        print("  *** INFEASIBLE — skipping ***")
        return None, None, None, solve_record

    obj_val = ampl.get_value("TotalPoints")
    print(f"  TotalPoints: {obj_val:.1f}")

    # MIP gap: (best_bound - obj) / obj  — read from AMPL solve_message if available
    try:
        mip_gap = float(ampl.get_value("_mipgap"))
    except Exception:
        mip_gap = None

    solve_record["obj"]     = round(obj_val, 4)
    solve_record["mip_gap"] = round(mip_gap, 6) if mip_gap is not None else None

    opt_roster, opt_relays = extract_roster(ampl, home_team)
    return obj_val, opt_roster, opt_relays, solve_record


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def diff_rosters(
    old_roster: dict, new_roster: dict,
    old_relays: dict, new_relays: dict,
) -> dict:
    """Return a structured diff between two rosters (individual + relay) for the same team."""
    old_ath = old_roster.get("athletes", {})
    new_ath = new_roster.get("athletes", {})

    old_names = set(old_ath)
    new_names = set(new_ath)

    # Individual event changes
    event_changes: dict = {}
    for name in old_names & new_names:
        old_evts = {a["event"] for a in old_ath[name].get("assignments", [])}
        new_evts = {a["event"] for a in new_ath[name].get("assignments", [])}
        if old_evts != new_evts:
            event_changes[name] = {
                "dropped": sorted(old_evts - new_evts),
                "added":   sorted(new_evts - old_evts),
            }

    # Relay changes: compare enrolled heats and leg compositions
    relay_changes: dict = {}
    all_relay_ids = list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys())
    for rid in all_relay_ids:
        for heat in ["A", "B"]:
            key = f"{rid}-{heat}"
            old_heat = (old_relays.get(rid) or {}).get(heat)
            new_heat = (new_relays.get(rid) or {}).get(heat)
            old_legs = sorted(l["name"] for l in old_heat["legs"]) if old_heat and old_heat.get("legs") else []
            new_legs = sorted(l["name"] for l in new_heat["legs"]) if new_heat and new_heat.get("legs") else []
            old_enrolled = len(old_legs) == 4
            new_enrolled = len(new_legs) == 4
            if old_enrolled != new_enrolled or old_legs != new_legs:
                relay_changes[key] = {
                    "enrolled": {"before": old_enrolled, "after": new_enrolled},
                    "legs_dropped": sorted(set(old_legs) - set(new_legs)),
                    "legs_added":   sorted(set(new_legs) - set(old_legs)),
                }

    return {
        "added_to_roster":     sorted(new_names - old_names),
        "removed_from_roster": sorted(old_names - new_names),
        "event_changes":       event_changes,
        "relay_changes":       relay_changes,
    }


def print_roster(team: str, roster: dict, relay_data: dict) -> None:
    athletes = roster.get("athletes", {})
    swimmers = {n: a for n, a in athletes.items() if a["type"] == "swimmer"}
    divers   = {n: a for n, a in athletes.items() if a["type"] == "diver"}

    print(f"\n  Roster for {team} ({len(swimmers)} swimmers, {len(divers)} divers)")
    for label, section in [("Swimmers", swimmers), ("Divers", divers)]:
        if not section:
            continue
        print(f"    {label}:")
        for name, info in sorted(section.items()):
            evts = ", ".join(a["event"] for a in info["assignments"])
            print(f"      {name:<30} {evts}")

    print("    Relays:")
    all_relay_ids = list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys())
    for rid in all_relay_ids:
        for heat in ["A", "B"]:
            h = relay_data.get(rid, {}).get(heat)
            if h and h.get("legs"):
                names = [f"{l.get('stroke', '')}: {l['name']}"
                         if "stroke" in l else l["name"]
                         for l in h["legs"]]
                print(f"      {rid} {heat}: {', '.join(names)}")


def print_scoreboard(label: str, scores: dict[str, float]) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for team in sorted(SCIAC_TEAMS, key=lambda t: -scores.get(t, 0)):
        print(f"  {team:<28} {scores.get(team, 0):>7.1f}")


def plot_score_history(
    score_history: dict[str, list[float]],
    phase_labels: list[str],
    save_path: str,
) -> None:
    """Plot each team's score across all phases (greedy → step3 → IBR rounds)."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm
        import numpy as np
    except ImportError:
        print("matplotlib not installed — skipping plot.")
        return

    fig, ax = plt.subplots(figsize=(max(10, len(phase_labels) * 1.5), 6))

    colors = cm.tab10(np.linspace(0, 1, len(SCIAC_TEAMS)))
    x = range(len(phase_labels))

    for (team, scores), color in zip(
        sorted(score_history.items(), key=lambda kv: -kv[1][-1]), colors
    ):
        ax.plot(x, scores, marker="o", linewidth=2, label=team, color=color)
        ax.annotate(f"{scores[-1]:.0f}", xy=(len(phase_labels) - 1, scores[-1]),
                    xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=color)

    # Vertical separators between phase groups (Greedy | S3:* | R1:* | R2:* …)
    def phase_group(label: str) -> str:
        if label == "Greedy":
            return "Greedy"
        if label.startswith("S3:"):
            return "S3"
        # R1:CMS, R2:PP → group by round number
        return label.split(":")[0]

    phase_boundaries = []
    for i in range(1, len(phase_labels)):
        if phase_group(phase_labels[i]) != phase_group(phase_labels[i - 1]):
            phase_boundaries.append(i - 0.5)
    for xb in phase_boundaries:
        ax.axvline(xb, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)

    ax.set_xticks(list(x))
    ax.set_xticklabels(phase_labels, rotation=25, ha="right", fontsize=9)
    ax.set_ylabel("Score (points)")
    ax.set_title("SCIAC Team Scores: Greedy → Step 3 → Iterative Best Response")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"\n  Score history plot saved → {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season",  default="2025-26")
    ap.add_argument("--gender",  default="Men", choices=["Men", "Women"])
    ap.add_argument("--date-to", default=None,
                    help="Pipeline date cutoff (YYYY-MM-DD). "
                         "E.g. 2026-02-17 to exclude SCIAC champs.")
    ap.add_argument("--skip-pipeline", action="store_true",
                    help="Skip pipeline; use existing best_performances / .dat files.")
    ap.add_argument("--skip-all-teams", action="store_true",
                    help="Skip step 3 (optimise every team individually); "
                         "jump straight to iterative best response.")
    ap.add_argument("--iterations", type=int, default=3,
                    help="Best-response iterations between CMS and PP (default: 3).")
    ap.add_argument("--br-teams", nargs="+",
                    default=["Claremont-Mudd-Scripps", "Pomona-Pitzer"],
                    help="Teams for iterative best response.")
    ap.add_argument("--solver",  default="gurobi")
    ap.add_argument("--time-limit", type=int, default=None,
                    help="Solver time limit in seconds per solve.")
    ap.add_argument("--mip-gap", type=float, default=0.025,
                    help="Gurobi MIP gap tolerance per solve (default: 0.025).")
    ap.add_argument("--model", default=str(DEFAULT_MOD),
                    help="Path to .mod file (default: Swimplex_time_rw.mod).")
    args = ap.parse_args()

    gender_lower = args.gender.lower()
    bp_rel_path  = f"{args.season}/best_performances_{gender_lower}.json"
    dat_path     = DATA_DIR / args.season / f"best_performances_{gender_lower}.dat"
    mod_path     = Path(args.model)

    # ── Metadata setup ───────────────────────────────────────────────────────
    started_at = datetime.datetime.now()
    t0 = time.perf_counter()
    peak_ram_mb = _rss_mb()

    def update_peak() -> None:
        nonlocal peak_ram_mb
        peak_ram_mb = max(peak_ram_mb, _rss_mb())

    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git_commit = "unknown"

    timings: dict[str, float] = {}
    solve_records: dict[str, dict] = {}   # phase_label → solve_record

    # ── Step 1: Pipeline ─────────────────────────────────────────────────────
    print("="*60)
    print("  Step 1: Data pipeline")
    print("="*60)
    if args.skip_pipeline:
        print("  Skipped (--skip-pipeline).")
        timings["pipeline_s"] = 0.0
    else:
        _t = time.perf_counter()
        run_pipeline(args.season, args.gender, args.date_to)
        timings["pipeline_s"] = round(time.perf_counter() - _t, 2)
        update_peak()

    if not dat_path.exists():
        sys.exit(f"ERROR: .dat file not found: {dat_path}\n"
                 f"Run without --skip-pipeline or generate it manually.")

    # ── Step 2: Greedy rosters ───────────────────────────────────────────────
    print("\n" + "="*60)
    print("  Step 2: Greedy rosters")
    print("="*60)

    _t = time.perf_counter()
    rosters, relay_assignments, swimmers = load_greedy(bp_rel_path)
    indiv_scores = evaluate_rosters(rosters)
    relay_scores = evaluate_relay_scores(relay_assignments)
    greedy_totals = {t: indiv_scores.get(t, 0) + relay_scores.get(t, 0)
                     for t in SCIAC_TEAMS}
    timings["greedy_s"] = round(time.perf_counter() - _t, 2)
    update_peak()

    print_scoreboard("Greedy predicted scores", greedy_totals)

    # Save greedy results
    greedy_out = DATA_DIR / args.season / f"greedy_rosters_{gender_lower}.json"
    with open(greedy_out, "w") as f:
        json.dump({
            "rosters": rosters,
            "relay_assignments": relay_assignments,
            "individual_scores": indiv_scores,
            "relay_scores": relay_scores,
            "total_scores": greedy_totals,
        }, f, indent=2)
    print(f"\n  Greedy results saved to {greedy_out}")

    # Mutable copies: updated as teams get optimised
    all_rosters = {t: rosters.get(t, {"athletes": {}}) for t in SCIAC_TEAMS}
    all_relays  = {t: relay_assignments.get(t, {})      for t in SCIAC_TEAMS}

    # ── Load AMPL model + data ───────────────────────────────────────────────
    print(f"\n  Loading model {mod_path.name} …")
    ampl = AMPL()
    ampl.read(str(mod_path))
    ampl.read_data(str(dat_path))

    optimized_scores: dict[str, float] = {}
    optimized_rosters: dict[str, dict] = {}
    optimized_relays:  dict[str, dict] = {}

    # Score history: team → [score at each phase]; phase_labels tracks x-axis labels
    score_history: dict[str, list[float]] = {t: [greedy_totals.get(t, 0)] for t in SCIAC_TEAMS}
    phase_labels: list[str] = ["Greedy"]

    SHORT = {
        "Claremont-Mudd-Scripps": "CMS",
        "Pomona-Pitzer":          "PP",
        "Cal Lutheran":           "CLU",
        "Caltech":                "CIT",
        "Chapman":                "CHA",
        "Occidental":             "OXY",
        "Whittier":               "WHI",
        "Redlands":               "RED",
        "La Verne":               "LAV",
    }

    def record_phase(label: str, updated_team: str, new_score: float) -> None:
        """Append one phase: carry forward all teams, overwrite updated_team."""
        phase_labels.append(label)
        for t in SCIAC_TEAMS:
            prev = score_history[t][-1]
            score_history[t].append(new_score if t == updated_team else prev)

    # ── Step 3: Optimise each team individually ──────────────────────────────
    if not args.skip_all_teams:
        print("\n" + "="*60)
        print("  Step 3: Optimise each team (8 greedy opponents)")
        print("="*60)

        for home_team in SCIAC_TEAMS:
            prev_roster = all_rosters.get(home_team, {"athletes": {}})
            prev_relays = all_relays.get(home_team, {})
            obj, opt_r, opt_rl, srec = optimize_team(
                ampl, home_team, all_rosters, all_relays,
                args.solver, args.time_limit, args.mip_gap,
            )
            phase_key = f"S3:{SHORT.get(home_team, home_team)}"
            solve_records[phase_key] = {"team": home_team, **srec}
            update_peak()
            if obj is not None:
                solve_records[phase_key]["roster_diff"] = diff_rosters(prev_roster, opt_r, prev_relays, opt_rl)
                optimized_scores[home_team] = obj
                optimized_rosters[home_team] = opt_r
                optimized_relays[home_team]  = opt_rl
                print_roster(home_team, opt_r, opt_rl)
                record_phase(phase_key, home_team, obj)

        print_scoreboard("Step 3: Each team optimised vs greedy opponents",
                         optimized_scores)

    # ── Step 4: Iterative best response ──────────────────────────────────────
    if args.iterations > 0 and len(args.br_teams) >= 2:
        print("\n" + "="*60)
        print(f"  Step 4: Iterative best response "
              f"({args.iterations} rounds, {', '.join(args.br_teams)})")
        print("="*60)

        # Seed all_rosters with step-3 optimised rosters for every team that was
        # solved (not just BR teams), so IBR opponents use the best available
        # roster rather than the greedy baseline.
        for team in SCIAC_TEAMS:
            if team in optimized_rosters:
                all_rosters[team] = optimized_rosters[team]
                all_relays[team]  = optimized_relays[team]

        for rnd in range(1, args.iterations + 1):
            print(f"\n{'━'*60}")
            print(f"  Round {rnd}")
            print(f"{'━'*60}")

            for home_team in args.br_teams:
                prev_roster = all_rosters.get(home_team, {"athletes": {}})
                prev_relays = all_relays.get(home_team, {})
                obj, opt_r, opt_rl, srec = optimize_team(
                    ampl, home_team, all_rosters, all_relays,
                    args.solver, args.time_limit, args.mip_gap,
                )
                phase_key = f"R{rnd}:{SHORT.get(home_team, home_team)}"
                solve_records[phase_key] = {"team": home_team, **srec}
                update_peak()
                if obj is not None:
                    solve_records[phase_key]["roster_diff"] = diff_rosters(prev_roster, opt_r, prev_relays, opt_rl)
                    prev = optimized_scores.get(home_team, greedy_totals.get(home_team, 0))
                    optimized_scores[home_team] = obj
                    optimized_rosters[home_team] = opt_r
                    optimized_relays[home_team]  = opt_rl
                    all_rosters[home_team] = opt_r
                    all_relays[home_team]  = opt_rl
                    print(f"  {home_team}: {prev:.1f} → {obj:.1f} "
                          f"({'↑' if obj > prev else '↓' if obj < prev else '='}"
                          f" {abs(obj - prev):.1f})")
                    print_roster(home_team, opt_r, opt_rl)
                    record_phase(phase_key, home_team, obj)

    # ── Final summary ────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  Final Summary")
    print("="*60)
    print(f"  {'Team':<28} {'Greedy':>7}  {'Optimised':>9}  {'Delta':>7}")
    print(f"  {'─'*28} {'─'*7}  {'─'*9}  {'─'*7}")
    for team in sorted(SCIAC_TEAMS,
                       key=lambda t: -optimized_scores.get(t, greedy_totals.get(t, 0))):
        g = greedy_totals.get(team, 0)
        o = optimized_scores.get(team, g)
        d = o - g
        print(f"  {team:<28} {g:>7.1f}  {o:>9.1f}  {d:>+7.1f}")

    # Save results
    finished_at = datetime.datetime.now()
    total_runtime_s = round(time.perf_counter() - t0, 2)
    update_peak()

    results_path = DATA_DIR / args.season / f"model_results_{gender_lower}.json"
    results = {
        "meta": {
            "started_at":      started_at.isoformat(timespec="seconds"),
            "finished_at":     finished_at.isoformat(timespec="seconds"),
            "total_runtime_s": total_runtime_s,
            "peak_ram_mb":     round(peak_ram_mb, 1),
            "git_commit":      git_commit,
            "solver":          args.solver,
            "platform":        platform.platform(),
            "python_version":  platform.python_version(),
            "args": {
                "season":         args.season,
                "gender":         args.gender,
                "date_to":        args.date_to,
                "skip_pipeline":  args.skip_pipeline,
                "skip_all_teams": args.skip_all_teams,
                "iterations":     args.iterations,
                "br_teams":       args.br_teams,
                "time_limit":     args.time_limit,
                "mip_gap":        args.mip_gap,
                "model":          str(mod_path),
            },
        },
        "timings": timings,
        "solve_records": solve_records,
        "season": args.season,
        "gender": args.gender,
        "greedy_scores": greedy_totals,
        "optimized_scores": optimized_scores,
        "optimized_rosters": {
            team: {
                "athletes": {
                    name: {"type": info["type"],
                           "events": [a["event"] for a in info["assignments"]]}
                    for name, info in roster["athletes"].items()
                }
            }
            for team, roster in optimized_rosters.items()
        },
    }
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to {results_path}")
    print(f"  Total runtime: {total_runtime_s:.1f}s  |  Peak RAM: {peak_ram_mb:.0f} MB")

    # ── Plot ──────────────────────────────────────────────────────────────────
    if len(phase_labels) > 1:
        plot_path = str(DATA_DIR / args.season / f"score_history_{gender_lower}.png")
        plot_score_history(score_history, phase_labels, plot_path)


if __name__ == "__main__":
    main()
