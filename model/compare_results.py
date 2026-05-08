#!/usr/bin/env python3
"""
Compare model predictions (model_results_men.json) against
actual championship results (ground_truth/results.json).

Reports:
  1. Score comparison (predicted vs actual) for all 9 teams
  2. Roster accuracy per team: correct picks, missed athletes, phantom picks
  3. Event-level accuracy: correct event assignments per athlete
  4. Detailed breakdown for CMS and Pomona-Pitzer

Usage:
    python3 model/compare_results.py [--team "Team Name"]
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH  = REPO_ROOT / "data/2025-26-pre-sciac/model_results_men.json"
GREEDY_PATH = REPO_ROOT / "data/2025-26-pre-sciac/greedy_rosters_men.json"
GT_PATH     = REPO_ROOT / "data/2025-26-pre-sciac/ground_truth/results.json"

# Map model team names → canonical names used in ground truth
# (model uses pipeline canonical names; GT uses same canonicalization)
# Both should be identical; this is a safety mapping
TEAM_ALIAS = {
    "Claremont-Mudd-Scripps": "Claremont-Mudd-Scripps",
    "Pomona-Pitzer":          "Pomona-Pitzer",
    "Chapman":                "Chapman",
    "Caltech":                "Caltech",
    "Occidental":             "Occidental",
    "Whittier":               "Whittier",
    "Redlands":               "Redlands",
    "La Verne":               "La Verne",
    "Cal Lutheran":           "Cal Lutheran",
}

# Model event names (from pipeline) → ground truth event name fragment
# Ground truth event names look like "Men 500 Yard Freestyle"
MODEL_TO_GT_EVENT = {
    "50 Yard Freestyle":    "50 Yard Freestyle",
    "100 Yard Freestyle":   "100 Yard Freestyle",
    "200 Yard Freestyle":   "200 Yard Freestyle",
    "500 Yard Freestyle":   "500 Yard Freestyle",
    "1650 Yard Freestyle":  "1650 Yard Freestyle",
    "100 Yard Butterfly":   "100 Yard Butterfly",
    "200 Yard Butterfly":   "200 Yard Butterfly",
    "100 Yard Backstroke":  "100 Yard Backstroke",
    "200 Yard Backstroke":  "200 Yard Backstroke",
    "100 Yard Breaststroke":"100 Yard Breaststroke",
    "200 Yard Breaststroke":"200 Yard Breaststroke",
    "200 Yard IM":          "200 Yard IM",
    "400 Yard IM":          "400 Yard IM",
    "1 mtr Diving":         "1 mtr Diving",
    "3 mtr Diving":         "3 mtr Diving",
}


def load_data():
    with open(MODEL_PATH) as f:
        model = json.load(f)
    with open(GT_PATH) as f:
        gt = json.load(f)

    # If optimized scores/rosters are empty (optimizer infeasible), fall back to greedy
    if not model.get("optimized_scores") and GREEDY_PATH.exists():
        with open(GREEDY_PATH) as f:
            greedy = json.load(f)
        model["optimized_scores"] = model.get("greedy_scores", {})
        # Build optimized_rosters from greedy rosters format
        opt_rosters = {}
        for team, team_body in greedy.get("rosters", {}).items():
            athletes = {}
            for group in team_body.values():
                if isinstance(group, dict):
                    for name, info in group.items():
                        events = [a["event"] for a in info.get("assignments", [])]
                        athletes[name] = {
                            "type": info.get("type", "swimmer"),
                            "events": events,
                        }
            opt_rosters[team] = {"athletes": athletes}
        model["optimized_rosters"] = opt_rosters
        model["_using_greedy_fallback"] = True

    return model, gt


def build_gt_rosters(gt):
    """
    Build per-team actual rosters from ground truth finals results.
    Returns: {team: {athlete_name: set_of_events}}
    (Only A-Final and B-Final entries; not prelims or time trials.)
    """
    rosters = defaultdict(lambda: defaultdict(set))

    finals_heats = {"A-Final", "B-Final"}

    for r in gt["individual_results"]:
        if r["gender"] != "Men":
            continue
        if r["heat"] not in finals_heats:
            continue
        if r["exhibition"]:
            continue
        team  = r["school"]
        name  = r["name"]
        # Strip "Men " prefix from event_name
        event = r["event_name"].replace("Men ", "", 1)
        # Normalize IM: "200 Yard IM" not "200 Yard Individual Medley"
        rosters[team][name].add(event)

    for r in gt["diving_results"]:
        if r["gender"] != "Men":
            continue
        if r["exhibition"]:
            continue
        team  = r["school"]
        name  = r["name"]
        event = r["event_name"].replace("Men ", "", 1)
        rosters[team][name].add(event)

    return {t: dict(v) for t, v in rosters.items()}


def build_gt_relay_rosters(gt):
    """
    Build per-team relay participants from ground truth relay results.
    Returns: {team: {event_fragment: {heat: [athlete_names]}}}
    """
    relay_rosters = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for r in gt["relay_results"]:
        if r["gender"] != "Men":
            continue
        if r.get("dq"):
            continue
        team  = r["school"]
        event = r["event_name"].replace("Men ", "", 1)
        heat  = r["heat"]  # 'A' or 'B'
        for leg in r.get("legs", []):
            relay_rosters[team][event][heat].append(leg["name"])

    return relay_rosters


def name_in_model_roster(name: str, model_athletes: dict) -> bool:
    """Check if a ground-truth athlete name appears in the model roster (exact or close)."""
    return name in model_athletes


def compare_scores(model, gt):
    """Compare predicted scores vs official scores."""
    official = gt["team_scores"]["Men"]
    optimized = model["optimized_scores"]
    greedy    = model["greedy_scores"]

    label = "Greedy (optimizer fallback)" if model.get("_using_greedy_fallback") else "Model Optimized"
    print("=" * 72)
    print(f"SCORE COMPARISON  (Greedy → {label} vs Actual)")
    print("=" * 72)
    print(f"{'Team':<30} {'Greedy':>8} {'Model':>10} {'Actual':>8} {'Error':>8} {'Err%':>6}")
    print("-" * 72)

    teams = sorted(official.keys(), key=lambda t: -official[t])
    total_abs_error = 0
    for team in teams:
        act  = official.get(team, 0)
        opt  = optimized.get(team, 0)
        grd  = greedy.get(team, 0)
        err  = opt - act
        pct  = 100 * err / act if act else 0
        total_abs_error += abs(err)
        print(f"{team:<30} {grd:>8.0f} {opt:>10.1f} {act:>8.1f} {err:>+8.1f} {pct:>+5.1f}%")

    print("-" * 72)
    # Overall rank comparison
    model_rank = sorted(optimized.keys(), key=lambda t: -optimized[t])
    actual_rank = sorted(official.keys(), key=lambda t: -official[t])
    print(f"\nModel ranking:  {' > '.join(model_rank)}")
    print(f"Actual ranking: {' > '.join(actual_rank)}")
    correct_order = sum(m == a for m, a in zip(model_rank, actual_rank))
    print(f"\nRank positions correct: {correct_order}/{len(model_rank)}")
    print(f"Total absolute score error: {total_abs_error:.1f} pts")
    print()


def compare_rosters(model, gt_rosters, gt_relay_rosters, focus_teams=None):
    """Per-team roster and event accuracy."""
    teams = sorted(model["optimized_rosters"].keys())
    if focus_teams:
        teams = [t for t in teams if t in focus_teams]

    summary_rows = []

    for team in teams:
        gt_team = TEAM_ALIAS.get(team, team)
        model_athletes = model["optimized_rosters"][team]["athletes"]
        gt_athletes    = gt_rosters.get(gt_team, {})

        model_names = set(model_athletes.keys())
        gt_names    = set(gt_athletes.keys())

        correct_athletes = model_names & gt_names
        phantom_athletes = model_names - gt_names   # model picked, didn't compete
        missed_athletes  = gt_names - model_names   # competed but model didn't pick

        # Event-level accuracy for correctly identified athletes
        event_correct = 0
        event_total   = 0
        event_details = []
        for name in sorted(correct_athletes):
            model_events = set(model_athletes[name].get("events", []))
            gt_events    = gt_athletes.get(name, set())
            for evt in model_events:
                # Normalize event name for comparison
                gt_fragment = MODEL_TO_GT_EVENT.get(evt, evt)
                matched = any(gt_fragment in ge for ge in gt_events)
                event_total += 1
                if matched:
                    event_correct += 1
                else:
                    event_details.append(f"  WRONG EVENT: {name} → {evt} (actual: {sorted(gt_events)})")
            # Events athlete competed in but model didn't assign
            for ge in gt_events:
                if not any(MODEL_TO_GT_EVENT.get(me, me) in ge for me in model_events):
                    event_details.append(f"  MISSED ASSIGNMENT: {name} in {ge} (model had: {sorted(model_events)})")

        event_pct = 100 * event_correct / event_total if event_total else 0

        summary_rows.append((team, len(model_names), len(gt_names),
                              len(correct_athletes), len(phantom_athletes),
                              len(missed_athletes), event_correct, event_total))

        print("=" * 72)
        print(f"TEAM: {team}")
        print("=" * 72)
        print(f"  Model selected {len(model_names)} athletes, "
              f"actual roster had {len(gt_names)} athletes")
        print(f"  Roster overlap: {len(correct_athletes)}/{len(gt_names)} actual athletes predicted "
              f"({100*len(correct_athletes)/len(gt_names):.0f}%)")
        print(f"  Event assignments: {event_correct}/{event_total} correct ({event_pct:.0f}%)")

        if phantom_athletes:
            print(f"\n  ┌─ PHANTOM (model picked, didn't compete finals) [{len(phantom_athletes)}]:")
            for a in sorted(phantom_athletes):
                evts = model_athletes[a].get("events", [])
                print(f"  │   {a}: {evts}")

        if missed_athletes:
            print(f"\n  ├─ MISSED (competed but model didn't pick) [{len(missed_athletes)}]:")
            for a in sorted(missed_athletes):
                evts = sorted(gt_athletes[a])
                print(f"  │   {a}: {evts}")

        if event_details:
            print(f"\n  └─ EVENT ASSIGNMENT DIFFERENCES:")
            for d in event_details:
                print(f"  {d}")

        # Relay comparison
        gt_relay = gt_relay_rosters.get(gt_team, {})
        if gt_relay:
            print(f"\n  RELAY PARTICIPANTS (actual):")
            for evt in sorted(gt_relay.keys()):
                for heat in sorted(gt_relay[evt].keys()):
                    names = gt_relay[evt][heat]
                    print(f"    {evt} ({heat}): {', '.join(names)}")
        print()

    # Summary table
    print("=" * 72)
    print("ROSTER ACCURACY SUMMARY")
    print("=" * 72)
    print(f"{'Team':<28} {'Mod':>4} {'Act':>4} {'Hit':>4} {'Phan':>5} {'Miss':>5} "
          f"{'EvtOK':>6} {'EvtTot':>7} {'Evt%':>5}")
    print("-" * 72)
    for row in summary_rows:
        team, n_mod, n_act, hit, phan, miss, eok, etot = row
        epct = 100*eok/etot if etot else 0
        roster_pct = 100*hit/n_act if n_act else 0
        print(f"{team:<28} {n_mod:>4} {n_act:>4} {hit:>4} ({roster_pct:>3.0f}%) "
              f"{phan:>5} {miss:>5} {eok:>6}/{etot:<7} {epct:>4.0f}%")
    print()


def score_breakdown_by_event(gt, teams=None):
    """Show actual points scored per event per team (Men finals only)."""
    official = gt["team_scores"]["Men"]
    team_list = sorted(official.keys(), key=lambda t: -official[t])
    if teams:
        team_list = [t for t in team_list if t in teams]

    # Aggregate points by team × event_type
    pts = defaultdict(lambda: defaultdict(float))
    for r in gt["individual_results"]:
        if r["gender"] != "Men" or r["heat"] not in ("A-Final", "B-Final"):
            continue
        pts[r["school"]][r["event_name"].replace("Men ", "")] += r["points"]
    for r in gt["diving_results"]:
        if r["gender"] != "Men":
            continue
        pts[r["school"]][r["event_name"].replace("Men ", "")] += r["points"]
    for r in gt["relay_results"]:
        if r["gender"] != "Men":
            continue
        pts[r["school"]][r["event_name"].replace("Men ", "")] += r["points"]

    events_ordered = [
        "500 Yard Freestyle", "200 Yard IM", "50 Yard Freestyle",
        "100 Yard Butterfly", "400 Yard IM", "200 Yard Freestyle",
        "100 Yard Breaststroke", "100 Yard Backstroke", "1650 Yard Freestyle",
        "200 Yard Backstroke", "100 Yard Freestyle", "200 Yard Breaststroke",
        "200 Yard Butterfly", "1 mtr Diving", "3 mtr Diving",
        "200 Yard Medley Relay", "200 Yard Freestyle Relay",
        "400 Yard Medley Relay", "400 Yard Freestyle Relay",
        "800 Yard Freestyle Relay",
    ]

    print("=" * 90)
    print("ACTUAL POINTS BY EVENT (Men)")
    print("=" * 90)
    hdr = f"{'Event':<28}" + "".join(f"{t[:9]:>10}" for t in team_list)
    print(hdr)
    print("-" * 90)

    for evt in events_ordered:
        row = f"{evt:<28}"
        for t in team_list:
            v = pts[t].get(evt, 0)
            row += f"{v:>10.1f}" if v else " " * 9 + "-"
        print(row)

    print("-" * 90)
    row = f"{'TOTAL':<28}"
    for t in team_list:
        row += f"{official[t]:>10.1f}"
    print(row)
    print()


def main():
    focus_arg = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--team" and i + 1 < len(sys.argv) - 1:
            focus_arg = sys.argv[i + 2]

    model, gt = load_data()
    gt_rosters       = build_gt_rosters(gt)
    gt_relay_rosters = build_gt_relay_rosters(gt)

    compare_scores(model, gt)

    focus_teams = [focus_arg] if focus_arg else None

    if focus_teams is None:
        score_breakdown_by_event(gt)

    compare_rosters(model, gt_rosters, gt_relay_rosters, focus_teams=focus_teams)


if __name__ == "__main__":
    main()
