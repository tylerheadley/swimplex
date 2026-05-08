#!/usr/bin/env python3
"""
Diagnose AMPL infeasibility when fixing 8 opponent teams to greedy.
Identifies which team(s) or constraints cause infeasibility.

Usage:
    python3 model/debug_infeasible.py
"""

import json
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
    greedy_relay_assignment,
)
from model.run_iterative import fix_team_to_greedy, q

SEASON = "2025-26-pre-sciac"
MOD = REPO_ROOT / "model" / "Swimplex_time.mod"
DAT = REPO_ROOT / "data" / SEASON / "best_performances_men.dat"
BP  = f"{SEASON}/best_performances_men.json"


def load_greedy():
    data, _ = load_json_from_data(BP)
    swimmers = data.get("swimmers", {})
    entries = build_performance_entries(swimmers)
    rosters = build_greedy_rosters(entries)
    relay_assignments = greedy_relay_assignment(rosters, swimmers)
    return rosters, relay_assignments


def make_ampl():
    ampl = AMPL()
    ampl.read(str(MOD))
    ampl.read_data(str(DAT))
    ampl.set_option("presolve", 0)
    ampl.set_option("solver", "gurobi")
    return ampl


def check_feasible(ampl: AMPL, home_team: str, opponents_fixed: list[str],
                   rosters: dict, relay_assignments: dict) -> str:
    """Fix the given opponents and optimize home_team. Returns solve_result."""
    ampl.eval("unfix;")

    # Zero everything first
    for team in SCIAC_TEAMS:
        qt = q(team)
        ampl.eval(f"let {{a in AthletesTeam[{qt}], e in SoloEvents}} athlete_swims_event_solo[a,e] := 0;")
        ampl.eval(f"let {{a in AthletesTeam[{qt}], e in DivingEvents}} athlete_dives_event[a,e] := 0;")
        ampl.eval(f"let {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} athlete_swims_event_rel[a,e,l] := 0;")
        ampl.eval(f"let {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} athlete_swims_event_med[a,e,l,s] := 0;")
        ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_scorer[a] := 0;")
        ampl.eval(f"let {{a in AthletesTeam[{qt}]}} is_diver_only[a] := 0;")
        for relay_id in RELAY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := 0;")
        for med_id in MEDLEY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := 0;")

    for team in opponents_fixed:
        fix_team_to_greedy(
            ampl, team,
            rosters.get(team, {"athletes": {}}),
            relay_assignments.get(team, {}),
        )

    ampl.param["home_team"] = home_team
    ampl.eval("objective TotalPoints;")
    ampl.set_option("gurobi_options", "outlev=0")
    ampl.solve()
    return str(ampl.get_value("solve_result"))


def bisect_infeasibility():
    print("Loading greedy rosters …")
    rosters, relay_assignments = load_greedy()

    home = "Claremont-Mudd-Scripps"
    opponents = [t for t in SCIAC_TEAMS if t != home]
    print(f"Home team: {home}")
    print(f"Opponents: {opponents}\n")

    ampl = make_ampl()

    # Test 1: No opponents fixed — should be feasible
    print("Test 1: No opponents fixed")
    r = check_feasible(ampl, home, [], rosters, relay_assignments)
    print(f"  Result: {r}\n")
    if "infeasible" in r:
        print("  ERROR: bare solve is infeasible — model or data issue!")
        return

    # Test 2: Add opponents one at a time until infeasible
    print("Test 2: Adding opponents one at a time")
    fixed_so_far = []
    for opp in opponents:
        fixed_so_far.append(opp)
        r = check_feasible(ampl, home, fixed_so_far[:], rosters, relay_assignments)
        status = "OK" if "infeasible" not in r else "INFEASIBLE"
        print(f"  Fixed {len(fixed_so_far)}: {opp:<28} → {r}  [{status}]")
        if "infeasible" in r:
            print(f"\n  >>> Infeasibility triggered by adding: {opp}")
            # Binary search within this team's fix
            diagnose_team(ampl, home, fixed_so_far[:-1], opp, rosters, relay_assignments)
            break


def diagnose_team(ampl: AMPL, home: str, prev_fixed: list[str], culprit: str,
                  rosters: dict, relay_assignments: dict):
    """Determine which part of fixing `culprit` causes infeasibility."""
    print(f"\nDiagnosing culprit team: {culprit}")
    qt = q(culprit)
    roster = rosters.get(culprit, {"athletes": {}})
    relay = relay_assignments.get(culprit, {})

    def base_fix():
        """Fix prev_fixed teams only (baseline = feasible)."""
        ampl.eval("unfix;")
        for team in SCIAC_TEAMS:
            qt2 = q(team)
            ampl.eval(f"let {{a in AthletesTeam[{qt2}], e in SoloEvents}} athlete_swims_event_solo[a,e] := 0;")
            ampl.eval(f"let {{a in AthletesTeam[{qt2}], e in DivingEvents}} athlete_dives_event[a,e] := 0;")
            ampl.eval(f"let {{a in AthletesTeam[{qt2}], e in RelayEvents, l in Level}} athlete_swims_event_rel[a,e,l] := 0;")
            ampl.eval(f"let {{a in AthletesTeam[{qt2}], e in MedleyEvents, l in Level, s in Stroke}} athlete_swims_event_med[a,e,l,s] := 0;")
            ampl.eval(f"let {{a in AthletesTeam[{qt2}]}} is_scorer[a] := 0;")
            ampl.eval(f"let {{a in AthletesTeam[{qt2}]}} is_diver_only[a] := 0;")
            for relay_id in RELAY_EVENTS:
                for heat in ["A", "B"]:
                    ampl.eval(f"let relay_enroll[{qt2}, '{relay_id}', '{heat}'] := 0;")
            for med_id in MEDLEY_EVENTS:
                for heat in ["A", "B"]:
                    ampl.eval(f"let med_relay_enroll[{qt2}, '{med_id}', '{heat}'] := 0;")
        for team in prev_fixed:
            fix_team_to_greedy(ampl, team,
                               rosters.get(team, {"athletes": {}}),
                               relay_assignments.get(team, {}))

    def solve_test() -> str:
        ampl.param["home_team"] = home
        ampl.eval("objective TotalPoints;")
        ampl.set_option("gurobi_options", "outlev=0")
        ampl.solve()
        return str(ampl.get_value("solve_result"))

    # Test A: fix only is_scorer/is_diver_only for culprit
    base_fix()
    athletes_info = roster.get("athletes", {})
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")
    r = solve_test()
    print(f"  A. Fix is_scorer/is_diver_only only: {r}")

    # Test B: fix is_scorer/is_diver_only + solo events
    base_fix()
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")
        for assignment in ath_data.get("assignments", []):
            evt_name = assignment["event"]
            SOLO_REV = {v: k for k, v in SOLO_EVENTS.items()}
            DIVE_REV = {v: k for k, v in DIVE_EVENTS.items()}
            if evt_name in SOLO_REV:
                ampl.eval(f"let athlete_swims_event_solo[{qa}, '{SOLO_REV[evt_name]}'] := 1;")
            elif evt_name in DIVE_REV:
                ampl.eval(f"let athlete_dives_event[{qa}, '{DIVE_REV[evt_name]}'] := 1;")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in SoloEvents}} athlete_swims_event_solo[a,e];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in DivingEvents}} athlete_dives_event[a,e];")
    r = solve_test()
    print(f"  B. Fix solo/dive events too: {r}")

    # Test C: fix relay_enroll only (no relay participant assignments)
    base_fix()
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")
    for relay_id in RELAY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay.get(relay_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
    for med_id in MEDLEY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay.get(med_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix med_relay_enroll[{qt}, '{med_id}', '{heat}'];")
    r = solve_test()
    print(f"  C. Fix is_scorer + relay_enroll (no relay participants): {r}")

    # Test D: full fix including relay participants
    base_fix()
    fix_team_to_greedy(ampl, culprit, roster, relay)
    r = solve_test()
    print(f"  D. Full fix_team_to_greedy: {r}")

    if "infeasible" in r:
        # Test E: check individual relay events
        print("\n  Checking individual relay assignments for over-limit athletes:")
        SOLO_REV = {v: k for k, v in SOLO_EVENTS.items()}
        DIVE_REV = {v: k for k, v in DIVE_EVENTS.items()}

        # Count events per athlete
        for ath_name, ath_data in athletes_info.items():
            solo_ct = sum(1 for a in ath_data.get("assignments", []) if a["event"] in SOLO_REV or a["event"] in DIVE_REV)
            relay_ct = 0
            relay_events_for_ath = []
            for rid in list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys()):
                for heat in ["A", "B"]:
                    heat_info = relay.get(rid, {}).get(heat)
                    if heat_info and heat_info.get("legs"):
                        for leg in heat_info["legs"]:
                            if leg["name"] == ath_name:
                                relay_ct += 1
                                relay_events_for_ath.append(f"{rid}-{heat}")
            total = solo_ct + relay_ct
            if total > 7:
                print(f"    OVER LIMIT: {ath_name}: solo={solo_ct}, relay={relay_ct}, total={total} > 7")
                print(f"      Relay events: {relay_events_for_ath}")
            elif relay_ct > 5:
                print(f"    RELAY OVER LIMIT: {ath_name}: relay={relay_ct} > 5")
                print(f"      Relay events: {relay_events_for_ath}")


if __name__ == "__main__":
    bisect_infeasibility()
