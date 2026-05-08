#!/usr/bin/env python3
"""
More targeted IIS analysis:
1. Read the IIS suffix to identify exact constraints
2. Test fixing individual relay heats to find minimal infeasible set
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from amplpy import AMPL, add_to_path
add_to_path("/Applications/AMPL")

from pipeline.ampl_export import (
    RELAY_EVENTS, MEDLEY_EVENTS, SCIAC_TEAMS,
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


def make_ampl():
    ampl = AMPL()
    ampl.read(str(MOD))
    ampl.read_data(str(DAT))
    ampl.set_option("presolve", 0)
    ampl.set_option("solver", "gurobi")
    return ampl


def zero_all(ampl: AMPL):
    """Initialize all variables to 0."""
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


def fix_scorer(ampl: AMPL, team: str, roster: dict):
    """Fix is_scorer/is_diver_only for a team."""
    qt = q(team)
    athletes_info = roster.get("athletes", {})
    for ath_name, ath_data in athletes_info.items():
        qa = q(ath_name)
        is_diver = ath_data.get("type") == "diver"
        ampl.eval(f"let is_scorer[{qa}] := 1;")
        if is_diver:
            ampl.eval(f"let is_diver_only[{qa}] := 1;")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_scorer[a];")
    ampl.eval(f"fix {{a in AthletesTeam[{qt}]}} is_diver_only[a];")


def solve_quick(ampl: AMPL, home: str) -> str:
    ampl.param["home_team"] = home
    ampl.eval("objective TotalPoints;")
    ampl.set_option("gurobi_options", "outlev=0")
    ampl.solve()
    return str(ampl.get_value("solve_result"))


def main():
    print("Loading greedy rosters …")
    rosters, relay_assignments = load_greedy()
    roster = rosters.get(CULPRIT, {"athletes": {}})
    relay = relay_assignments.get(CULPRIT, {})

    ampl = make_ampl()
    qt = q(CULPRIT)
    home = "Claremont-Mudd-Scripps"

    # --- Test 1: Only fix is_scorer (no relay_enroll) ---
    ampl.eval("unfix;")
    zero_all(ampl)
    fix_scorer(ampl, CULPRIT, roster)
    r = solve_quick(ampl, home)
    print(f"Test 1: fix is_scorer only → {r}")

    # --- Test 2: Fix one relay_enroll at a time ---
    all_relays = [(rid, heat, 1 if (relay.get(rid, {}).get(heat) and
                   len(relay.get(rid, {}).get(heat, {}).get("legs", [])) == 4) else 0)
                 for rid in list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys())
                 for heat in ["A", "B"]]

    print("\nTest 2: Fix is_scorer + ONE relay_enroll=1 at a time:")
    for relay_id, heat, enrolled in all_relays:
        if enrolled == 0:
            continue
        ampl.eval("unfix;")
        zero_all(ampl)
        fix_scorer(ampl, CULPRIT, roster)
        # Fix just this one relay_enroll
        if relay_id in RELAY_EVENTS:
            ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := 1;")
            ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
        else:
            ampl.eval(f"let med_relay_enroll[{qt}, '{relay_id}', '{heat}'] := 1;")
            ampl.eval(f"fix med_relay_enroll[{qt}, '{relay_id}', '{heat}'];")
        r = solve_quick(ampl, home)
        print(f"  {relay_id}-{heat}: {r}")

    # --- Test 3: Fix all relay_enroll for Cal Lutheran, then read IIS ---
    print("\nTest 3: Fix all relay_enroll for Cal Lutheran (IIS analysis):")
    ampl.eval("unfix;")
    zero_all(ampl)
    fix_scorer(ampl, CULPRIT, roster)

    for relay_id, heat, enrolled in all_relays:
        if relay_id in RELAY_EVENTS:
            ampl.eval(f"let relay_enroll[{qt}, '{relay_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix relay_enroll[{qt}, '{relay_id}', '{heat}'];")
        else:
            ampl.eval(f"let med_relay_enroll[{qt}, '{relay_id}', '{heat}'] := {enrolled};")
            ampl.eval(f"fix med_relay_enroll[{qt}, '{relay_id}', '{heat}'];")

    ampl.param["home_team"] = home
    ampl.eval("objective TotalPoints;")
    ampl.set_option("gurobi_options", "outlev=0 iisfind=1")
    ampl.solve()
    result = ampl.get_value("solve_result")
    print(f"  Result: {result}")

    # Read IIS suffix
    print("\n  IIS constraint membership:")
    for con_name in ["Participant_Limit_Relay", "Participant_Limit_Medley",
                     "Relay_Event_Cap", "Overall_Event_Cap",
                     "Relay_Scorers_Score", "Medley_Scorers_Score",
                     "Set_Relay_Enroll", "Set_Medley_Enroll",
                     "Seperate_AB", "Seperate_AB_Stroke",
                     "Faster_Team_Const", "is_And_Rel",
                     "Team_Scorer_Cap"]:
        try:
            con = ampl.get_constraint(con_name)
            vals = con.get_values()
            iis_entries = []
            for idx in vals.get_index_names():
                iis = vals.get_column("iis") if "iis" in vals.get_column_names() else None
                if iis:
                    iis_entries.append(f"{idx}={iis}")
            if iis_entries:
                print(f"    {con_name}: {iis_entries[:5]}")
        except Exception as e:
            pass

    # Try reading the iis suffix directly via AMPL display
    print("\n  Trying to display IIS constraints via AMPL suffix:")
    try:
        ampl.eval("""
display {con in {'Participant_Limit_Relay', 'Participant_Limit_Medley'}}:
  if con.iis != 0 then con.iis;
""")
    except Exception as e:
        print(f"  AMPL display error: {e}")


if __name__ == "__main__":
    main()
