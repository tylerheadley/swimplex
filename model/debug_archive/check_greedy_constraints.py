#!/usr/bin/env python3
"""
Check greedy rosters for model constraint violations WITHOUT running AMPL.
Tests all constraints that apply to fixed variables.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GREEDY = REPO_ROOT / "data/2025-26-pre-sciac/greedy_rosters_men.json"

RELAY_EVENT_LIM = 5
SOLO_EVENT_LIM  = 3
TOTAL_EVENT_LIM = 7
ENROLLMENT_CAP  = 18
DIVER_COST      = 1/3

RELAY_IDS  = ["FR200", "FR400", "FR800"]
MEDLEY_IDS = ["MED200", "MED400"]
ALL_RELAY_IDS = RELAY_IDS + MEDLEY_IDS

RELAY_EVENTS_FULL = {
    "FR200": "200 Yard Freestyle Relay",
    "FR400": "400 Yard Freestyle Relay",
    "FR800": "800 Yard Freestyle Relay",
}
MEDLEY_EVENTS_FULL = {
    "MED200": "200 Yard Medley Relay",
    "MED400": "400 Yard Medley Relay",
}


def main():
    with open(GREEDY) as f:
        data = json.load(f)

    rosters = data["rosters"]
    relay_assignments = data["relay_assignments"]

    total_violations = 0

    for team, team_data in sorted(rosters.items()):
        athletes = team_data["athletes"]
        team_violations = []

        # 1. Enrollment cap
        swimmers = {n: a for n, a in athletes.items() if a["type"] == "swimmer"}
        divers   = {n: a for n, a in athletes.items() if a["type"] == "diver"}
        score_val = len(swimmers) + len(divers) * DIVER_COST
        if score_val > ENROLLMENT_CAP + 1e-9:
            team_violations.append(f"  ENROLLMENT CAP VIOLATED: {score_val:.2f} > {ENROLLMENT_CAP}")

        team_relay = relay_assignments.get(team, {})

        # Build per-athlete relay participation
        ath_relays: dict[str, list[str]] = {n: [] for n in athletes}
        for rid in ALL_RELAY_IDS:
            for heat in ["A", "B"]:
                heat_info = team_relay.get(rid, {}).get(heat)
                if not heat_info or not heat_info.get("legs"):
                    continue
                legs = heat_info["legs"]

                # 2. Relay must have exactly 4 legs
                if len(legs) != 4:
                    team_violations.append(
                        f"  RELAY LEG COUNT: {rid}-{heat} has {len(legs)} legs (need 4)")

                for leg in legs:
                    name = leg["name"]
                    ath_relays.setdefault(name, []).append(f"{rid}-{heat}")

                    # 3. Athlete must be on roster
                    if name not in athletes:
                        team_violations.append(
                            f"  NON-ROSTER RELAY: {name} in {rid}-{heat} not in roster")

        for name, ath_data in athletes.items():
            solo_events = [a["event"] for a in ath_data.get("assignments", [])]
            relay_events = ath_relays.get(name, [])

            solo_ct  = len(solo_events)
            relay_ct = len(relay_events)
            total_ct = solo_ct + relay_ct

            # 4. Solo event cap (≤ 3 individual events)
            if solo_ct > SOLO_EVENT_LIM:
                team_violations.append(
                    f"  SOLO CAP: {name}: {solo_ct} solo events > {SOLO_EVENT_LIM}")

            # 5. Relay event cap (≤ 5 relay appearances)
            if relay_ct > RELAY_EVENT_LIM:
                team_violations.append(
                    f"  RELAY CAP: {name}: {relay_ct} relay appearances > {RELAY_EVENT_LIM}"
                    f"\n    {relay_events}")

            # 6. Total event cap (≤ 7 total)
            if total_ct > TOTAL_EVENT_LIM:
                team_violations.append(
                    f"  TOTAL CAP: {name}: {solo_ct} solo + {relay_ct} relay = {total_ct} > {TOTAL_EVENT_LIM}"
                    f"\n    solo:  {solo_events}"
                    f"\n    relay: {relay_events}")

            # 7. No athlete in both A and B of the same relay
            relay_event_names = [r.rsplit("-", 1)[0] for r in relay_events]
            for rid in ALL_RELAY_IDS:
                in_a = f"{rid}-A" in relay_events
                in_b = f"{rid}-B" in relay_events
                if in_a and in_b:
                    team_violations.append(
                        f"  A/B CONFLICT: {name} in both {rid}-A and {rid}-B")

            # 8. Diver must not swim (swim vars must be 0)
            if ath_data["type"] == "diver" and relay_events:
                team_violations.append(
                    f"  DIVER IN RELAY: {name} (diver) assigned relay: {relay_events}")

        if team_violations:
            print(f"\n{'='*60}")
            print(f"TEAM: {team}")
            print(f"{'='*60}")
            for v in team_violations:
                print(v)
            total_violations += len(team_violations)
        else:
            # Print summary only
            n_ath = len(athletes)
            budget = len(swimmers) + len(divers) * DIVER_COST
            # Count relay enrollments
            enrolled = sum(
                1 for rid in ALL_RELAY_IDS for heat in ["A", "B"]
                if (team_relay.get(rid, {}).get(heat) or {}).get("legs")
            )
            print(f"  OK  {team:<30} {n_ath:>3} athletes  budget={budget:.2f}/{ENROLLMENT_CAP}  relay_heats={enrolled}")

    print(f"\n{'='*60}")
    if total_violations == 0:
        print("ALL CONSTRAINTS SATISFIED in greedy rosters")
        print("The infeasibility must come from the AMPL model interaction, not the data.")
    else:
        print(f"TOTAL VIOLATIONS: {total_violations}")
    print()

    # Print detailed relay summary
    print("\n=== RELAY ENROLLMENT SUMMARY ===")
    for team, team_data in sorted(rosters.items()):
        team_relay = relay_assignments.get(team, {})
        print(f"\n{team}:")
        for rid in ALL_RELAY_IDS:
            for heat in ["A", "B"]:
                heat_info = team_relay.get(rid, {}).get(heat)
                if heat_info and heat_info.get("legs"):
                    names = [l["name"] for l in heat_info["legs"]]
                    print(f"  {rid}-{heat}: {len(names)} legs: {names}")
                else:
                    print(f"  {rid}-{heat}: (not enrolled)")


if __name__ == "__main__":
    main()
