"""
run_model.py — Run Swimplex_time.mod on a generated .dat file.

Usage:
    python3 model/run_model.py [--dat PATH] [--home-team TEAM] [--solver SOLVER]

Defaults:
    --dat        data/2025-26/best_performances_men.dat
    --home-team  value from param home_team in the .dat file
    --solver     gurobi
"""

import argparse
import os
import sys
import pickle

from amplpy import AMPL, add_to_path
add_to_path("/Applications/AMPL")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_FILE  = os.path.join(REPO_ROOT, "model", "Swimplex_time.mod")
DEFAULT_DAT = os.path.join(REPO_ROOT, "data", "2025-26", "best_performances_men.dat")


def parse_args():
    p = argparse.ArgumentParser(description="Run Swimplex AMPL model")
    p.add_argument("--dat",       default=DEFAULT_DAT, help="Path to .dat file")
    p.add_argument("--home-team", default=None,        help="Override home_team param")
    p.add_argument("--solver",    default="gurobi",    help="AMPL solver name")
    p.add_argument("--output",    default="model_test",    help="Pickled output name")
    return p.parse_args()


def main():
    args = parse_args()

    if not os.path.isfile(args.dat):
        sys.exit(f"ERROR: dat file not found: {args.dat}")
    if not os.path.isfile(MOD_FILE):
        sys.exit(f"ERROR: mod file not found: {MOD_FILE}")

    print(f"Model : {MOD_FILE}")
    print(f"Data  : {args.dat}")
    print(f"Solver: {args.solver}")

    ampl = AMPL()
    ampl.read(MOD_FILE)
    ampl.read_data(args.dat)
    ampl.set_option("solver", args.solver)

    if args.home_team:
        ampl.param["home_team"] = args.home_team
        print(f"home_team overridden → {args.home_team}")

    home_team = ampl.param["home_team"].value()
    print(f"home_team : {home_team}\n")

    ampl.solve()
    solve_result = ampl.get_value("solve_result")

    with open(f'args.output.pkl', 'wb') as f:
        pickle.dump(ampl, f)
        print(f"\nModel saved as Pickle under: {args.output}.pkl")

    print(f"\nSolve result: {solve_result}")

    if solve_result == "infeasible":
        print("\n--- INFEASIBILITY DETECTED ---")
        ampl.set_option("gurobi_options", "iisfind=1 outlev=1")
        for name, con in ampl.get_constraints():
            for index, instance in con:
                iis_values = instance.get_values("iis").toList()
                if iis_values and iis_values[0] != "non":
                    print(f"  Conflict: {name}[{index}]")
        return

    obj_val = ampl.get_value("TotalPoints")
    print(f"Objective (TotalPoints): {obj_val:.1f}")

    # ── Relay placements ──────────────────────────────────────────────────────
    try:
        placement_values = ampl.get_variable("placement").get_values().to_dict()
        if placement_values:
            print(f"\n{'RELAY EVENT':<25} {'Level':<6} {'Place'}")
            print("-" * 42)
            for (event, level), place in sorted(placement_values.items()):
                print(f"  {event:<23} {level:<6} {int(place)}")
    except Exception as e:
        print(f"(relay placement unavailable: {e})")

    # ── Solo placements ───────────────────────────────────────────────────────
    try:
        solo_place  = ampl.get_variable("placement_solo").get_values().to_dict()
        solo_swims  = ampl.get_variable("athlete_swims_event_solo").get_values().to_dict()
        if solo_place:
            print(f"\n{'SOLO EVENT':<20} {'Athlete':<35} {'Place'}")
            print("-" * 60)
            for (event, athlete), place in sorted(solo_place.items()):
                if solo_swims.get((athlete, event), 0) == 1 or solo_swims.get((event, athlete), 0) == 1:
                    print(f"  {event:<18} {athlete:<35} {int(place)}")
    except Exception as e:
        print(f"(solo placement unavailable: {e})")

    # ── Medley placements ─────────────────────────────────────────────────────
    try:
        med_values = ampl.get_variable("placement_med").get_values().to_dict()
        if med_values:
            print(f"\n{'MEDLEY EVENT':<25} {'Level':<6} {'Place'}")
            print("-" * 42)
            for (event, level), place in sorted(med_values.items()):
                print(f"  {event:<23} {level:<6} {int(place)}")
    except Exception as e:
        print(f"(medley placement unavailable: {e})")

    # ── Roster: who is assigned as a scorer ───────────────────────────────────
    try:
        scorer_values = ampl.get_variable("scorer").get_values().to_dict()
        scorers = [a for (a, t), v in scorer_values.items() if t == home_team and v == 1]
        print(f"\n{'SCORERS for ' + home_team} ({len(scorers)}):")
        for a in sorted(scorers):
            print(f"  {a}")
    except Exception as e:
        print(f"(scorer list unavailable: {e})")


if __name__ == "__main__":
    main()
