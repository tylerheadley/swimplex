#!/usr/bin/env python3
"""
IIS diagnostic: fix Cal Lutheran is_scorer + relay_enroll (test C that's infeasible),
then ask Gurobi for the IIS to identify the exact constraint(s) causing infeasibility.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from amplpy import AMPL, add_to_path
add_to_path("/Applications/AMPL")

from pipeline.ampl_export import (
    SOLO_EVENTS, RELAY_EVENTS, MEDLEY_EVENTS, DIVE_EVENTS, SCIAC_TEAMS,
)
from model.greedy_rosters import (
    load_json_from_data, build_performance_entries,
    greedy_rosters as build_greedy_rosters,
    greedy_relay_assignment,
)
from model.run_iterative import q

SEASON = "2025-26-pre-sciac"
MOD = REPO_ROOT / "model" / "Swimplex_time.mod"
DAT = REPO_ROOT / "data" / SEASON / "best_performances_men.dat"
BP  = f"{SEASON}/best_performances_men.json"

CULPRIT = "Cal Lutheran"


def load_greedy():
    data, _ = load_json_from_data(BP)
    swimmers = data.get("swimmers", {})
    entries = build_performance_entries(swimmers)
    rosters = build_greedy_rosters(entries)
    relay_assignments = greedy_relay_assignment(rosters, swimmers)
    return rosters, relay_assignments


def main():
    print("Loading greedy rosters …")
    rosters, relay_assignments = load_greedy()

    ampl = AMPL()
    ampl.read(str(MOD))
    ampl.read_data(str(DAT))
    ampl.set_option("presolve", 0)
    ampl.set_option("solver", "gurobi")

    # Zero all variables
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

    # Fix Cal Lutheran: is_scorer + relay_enroll only (Test C equivalent)
    qt = q(CULPRIT)
    roster = rosters.get(CULPRIT, {"athletes": {}})
    relay = relay_assignments.get(CULPRIT, {})
    athletes_info = roster.get("athletes", {})

    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")

    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")

    enrolled_list = []
    for relay_id in RELAY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay.get(relay_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
            if enrolled:
                enrolled_list.append(f"{relay_id}-{heat}")

    for med_id in MEDLEY_EVENTS:
        for heat in ["A", "B"]:
            heat_info = relay.get(med_id, {}).get(heat)
            enrolled = 1 if (heat_info and heat_info.get("legs") and len(heat_info["legs"]) == 4) else 0
            ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix med_relay_enroll[{qt}, '{med_id}', '{heat}'];")
            if enrolled:
                enrolled_list.append(f"{med_id}-{heat}")

    print(f"Cal Lutheran enrolled in: {enrolled_list}")

    ampl.param["home_team"] = "Claremont-Mudd-Scripps"
    ampl.eval("objective TotalPoints;")

    # Use outlev=1 to see Gurobi output; also request IIS
    ampl.set_option("gurobi_options", "outlev=1 iisfind=1")
    ampl.solve()
    result = ampl.get_value("solve_result")
    print(f"\nSolve result: {result}")

    if "infeasible" in str(result):
        # Try to write IIS
        print("\nAttempting to get IIS via gurobi_ampl iis command ...")
        try:
            ampl.eval("write 'giis.ilp';")
        except Exception as e:
            print(f"  write iis failed: {e}")

        # Alternative: try relaxing the relay_enroll constraint
        print("\nTest: what if we allow relay_enroll to vary (unfix it)?")
        for relay_id in RELAY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"unfix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
        for med_id in MEDLEY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"unfix med_relay_enroll[{qt}, '{med_id}', '{heat}'];")

        ampl.set_option("gurobi_options", "outlev=0")
        ampl.solve()
        result2 = ampl.get_value("solve_result")
        print(f"  Unfixed relay_enroll → {result2}")

        # Test with relay_enroll fixed to 0 instead
        print("\nTest: fix all relay_enroll = 0 for Cal Lutheran")
        for relay_id in RELAY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := 0;")
                ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
        for med_id in MEDLEY_EVENTS:
            for heat in ["A", "B"]:
                ampl.eval(f"let med_relay_enroll[{qt}, '{med_id}', '{heat}'] := 0;")
                ampl.eval(f"fix med_relay_enroll[{qt}, '{med_id}', '{heat}'];")

        ampl.set_option("gurobi_options", "outlev=0")
        ampl.solve()
        result3 = ampl.get_value("solve_result")
        print(f"  relay_enroll=0 for Cal Lutheran → {result3}")

        # Test: fix relay_enroll = 1 but also fix all relay participants to 0
        print("\nTest: relay_enroll=1 AND fix ALL relay participants to 0 for Cal Lutheran")
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

        # Also fix relay participants to 0
        ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in RelayEvents, l in Level}} athlete_swims_event_rel[a,e,l];")
        ampl.eval(f"fix {{a in AthletesTeam[{qt}], e in MedleyEvents, l in Level, s in Stroke}} athlete_swims_event_med[a,e,l,s];")

        ampl.set_option("gurobi_options", "outlev=0")
        ampl.solve()
        result4 = ampl.get_value("solve_result")
        print(f"  relay_enroll=1, relay_participants fixed to 0 → {result4}")
        print("  (This should be infeasible: relay_enroll=1 requires 4 athletes but 0 assigned)")


if __name__ == "__main__":
    main()
