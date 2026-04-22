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
import json
import subprocess
import sys
from pathlib import Path

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
DEFAULT_MOD = REPO_ROOT / "model" / "Swimplex_time_rw.mod"


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
) -> tuple[float | None, dict | None, dict | None]:
    """Fix 8 opponents, optimise *home_team*. Returns (obj, roster, relays)."""

    print(f"\n{'─'*60}")
    print(f"  Optimising: {home_team}")
    print(f"{'─'*60}")

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

    # Disable AMPL presolve; let solver handle it directly
    ampl.set_option("presolve", 0)

    # Solver options
    ampl.set_option("solver", solver)
    if time_limit and solver == "gurobi":
        ampl.set_option("gurobi_options", f"timelim={time_limit} outlev=1")

    ampl.solve()
    solve_result = ampl.get_value("solve_result")
    print(f"  Solve result: {solve_result}")

    if "infeasible" in str(solve_result):
        print("  *** INFEASIBLE — skipping ***")
        return None, None, None

    obj_val = ampl.get_value("TotalPoints")
    print(f"  TotalPoints: {obj_val:.1f}")

    opt_roster, opt_relays = extract_roster(ampl, home_team)
    return obj_val, opt_roster, opt_relays


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

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
    ap.add_argument("--model", default=str(DEFAULT_MOD),
                    help="Path to .mod file (default: Swimplex_time_rw.mod).")
    args = ap.parse_args()

    gender_lower = args.gender.lower()
    bp_rel_path  = f"{args.season}/best_performances_{gender_lower}.json"
    dat_path     = DATA_DIR / args.season / f"best_performances_{gender_lower}.dat"
    mod_path     = Path(args.model)

    # ── Step 1: Pipeline ─────────────────────────────────────────────────────
    print("="*60)
    print("  Step 1: Data pipeline")
    print("="*60)
    if args.skip_pipeline:
        print("  Skipped (--skip-pipeline).")
    else:
        run_pipeline(args.season, args.gender, args.date_to)

    if not dat_path.exists():
        sys.exit(f"ERROR: .dat file not found: {dat_path}\n"
                 f"Run without --skip-pipeline or generate it manually.")

    # ── Step 2: Greedy rosters ───────────────────────────────────────────────
    print("\n" + "="*60)
    print("  Step 2: Greedy rosters")
    print("="*60)

    rosters, relay_assignments, swimmers = load_greedy(bp_rel_path)
    indiv_scores = evaluate_rosters(rosters)
    relay_scores = evaluate_relay_scores(relay_assignments)
    greedy_totals = {t: indiv_scores.get(t, 0) + relay_scores.get(t, 0)
                     for t in SCIAC_TEAMS}

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

    # ── Step 3: Optimise each team individually ──────────────────────────────
    if not args.skip_all_teams:
        print("\n" + "="*60)
        print("  Step 3: Optimise each team (8 greedy opponents)")
        print("="*60)

        for home_team in SCIAC_TEAMS:
            obj, opt_r, opt_rl = optimize_team(
                ampl, home_team, all_rosters, all_relays,
                args.solver, args.time_limit,
            )
            if obj is not None:
                optimized_scores[home_team] = obj
                optimized_rosters[home_team] = opt_r
                optimized_relays[home_team]  = opt_rl
                print_roster(home_team, opt_r, opt_rl)

        print_scoreboard("Step 3: Each team optimised vs greedy opponents",
                         optimized_scores)

    # ── Step 4: Iterative best response ──────────────────────────────────────
    if args.iterations > 0 and len(args.br_teams) >= 2:
        print("\n" + "="*60)
        print(f"  Step 4: Iterative best response "
              f"({args.iterations} rounds, {', '.join(args.br_teams)})")
        print("="*60)

        # Seed with step-3 optimised rosters for BR teams (if available),
        # otherwise keep greedy.
        for team in args.br_teams:
            if team in optimized_rosters:
                all_rosters[team] = optimized_rosters[team]
                all_relays[team]  = optimized_relays[team]

        for rnd in range(1, args.iterations + 1):
            print(f"\n{'━'*60}")
            print(f"  Round {rnd}")
            print(f"{'━'*60}")

            for home_team in args.br_teams:
                obj, opt_r, opt_rl = optimize_team(
                    ampl, home_team, all_rosters, all_relays,
                    args.solver, args.time_limit,
                )
                if obj is not None:
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
    results_path = DATA_DIR / args.season / f"model_results_{gender_lower}.json"
    results = {
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


if __name__ == "__main__":
    main()
