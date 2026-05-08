#!/usr/bin/env python3
# /Users/tylerheadley/Desktop/Swimplex/model/greedy_rosters.py

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDIVIDUAL_POINTS: Dict[int, float] = {
    1: 20, 2: 17, 3: 16, 4: 15, 5: 14, 6: 13, 7: 12, 8: 11,
    9:  9, 10:  7, 11:  6, 12:  5, 13:  4, 14:  3, 15:  2, 16:  1,
}

DIVING_EVENTS = frozenset({"1 mtr Diving", "3 mtr Diving"})

INDIVIDUAL_EVENTS = frozenset({
    "50 Yard Freestyle", "100 Yard Freestyle", "200 Yard Freestyle",
    "500 Yard Freestyle", "1650 Yard Freestyle",
    "100 Yard Butterfly", "200 Yard Butterfly",
    "100 Yard Backstroke", "200 Yard Backstroke",
    "100 Yard Breaststroke", "200 Yard Breaststroke",
    "200 Yard IM", "400 Yard IM",
    "1 mtr Diving", "3 mtr Diving",
})

MAX_EVENTS_PER_ATHLETE = 3   # individual events per athlete
MAX_TOTAL_EVENTS = 7         # individual + relay appearances per athlete
SCORING_BUDGET = 18.0        # units: swimmer=1, diver=1/3
DIVER_COST = 1 / 3

EXCHANGE_ADVANTAGE = 0.7  # relay splits are ~0.7s faster than flat starts

# Freestyle relay events: relay_key = split event in best_performances,
# flat_key = individual event used as flat-start fallback / leadoff time.
RELAY_EVENTS: Dict[str, Dict[str, str]] = {
    "FR200": {"relay_key": "50 Yard Freestyle (Relay Split)",  "flat_key": "50 Yard Freestyle"},
    "FR400": {"relay_key": "100 Yard Freestyle (Relay Split)", "flat_key": "100 Yard Freestyle"},
    "FR800": {"relay_key": "200 Yard Freestyle (Relay Split)", "flat_key": "200 Yard Freestyle"},
}

# Medley relay strokes. Back leg is always the flat-start leadoff (relay_leg=1
# in the data, stored without the "(Relay Split)" suffix per CLAUDE.md).
MEDLEY_EVENTS: Dict[str, Dict[str, Dict]] = {
    "MED200": {
        "Back":   {"flat_key": "50 Yard Backstroke",  "relay_key": None},
        "Breast": {"flat_key": None, "relay_key": "50 Yard Breaststroke (Relay Split)"},
        "Fly":    {"flat_key": None, "relay_key": "50 Yard Butterfly (Relay Split)"},
        "Free":   {"flat_key": "50 Yard Freestyle",   "relay_key": "50 Yard Freestyle (Relay Split)"},
    },
    "MED400": {
        "Back":   {"flat_key": "100 Yard Backstroke",  "relay_key": None},
        "Breast": {"flat_key": None, "relay_key": "100 Yard Breaststroke (Relay Split)"},
        "Fly":    {"flat_key": None, "relay_key": "100 Yard Butterfly (Relay Split)"},
        "Free":   {"flat_key": "100 Yard Freestyle",   "relay_key": "100 Yard Freestyle (Relay Split)"},
    },
}

MEDLEY_STROKE_ORDER = ["Back", "Breast", "Fly", "Free"]

# Relay points: 2× solo individual points.
# A heat (9 lanes) → overall places 1–9.
# B heat (9 lanes) → overall places 10–18 (place 7 in B = 16th overall = 2 pts, 8–9 = 0).
RELAY_POINTS_A: List[int] = [40, 34, 32, 30, 28, 26, 24, 22, 18]
RELAY_POINTS_B: List[int] = [14, 12, 10,  8,  6,  4,  2,  0,  0]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_json_from_data(path_str: str) -> Tuple[Dict[str, Any], Path]:
    """Load a JSON file. If the path doesn't start with 'data' and isn't
    absolute, it is interpreted as relative to the 'data' folder."""
    p = Path(path_str)
    if not p.is_absolute() and (not p.parts or p.parts[0] != "data"):
        p = Path("data") / path_str

    if not p.exists() or not p.is_file():
        print(f"Error: file not found: {p}", file=sys.stderr)
        sys.exit(1)

    with p.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    if not isinstance(obj, dict):
        print(f"Warning: JSON root is {type(obj).__name__}, expected dict.", file=sys.stderr)

    return obj, p


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def _parse_seconds(time_str: str) -> float:
    """Convert 'M:SS.ss' or 'SS.ss' to float seconds. Returns inf on failure."""
    try:
        if ":" in time_str:
            minutes, rest = time_str.split(":", 1)
            return int(minutes) * 60 + float(rest)
        return float(time_str)
    except (ValueError, AttributeError):
        return float("inf")


# ---------------------------------------------------------------------------
# Build flat performance list
# ---------------------------------------------------------------------------

def build_performance_entries(swimmers: Dict[str, Any]) -> List[Dict]:
    """
    Given the 'swimmers' dict from best_performances JSON, produce a flat list
    of per-(athlete, event) entries. Each athlete appears at most once per event
    (their season best). Relay splits are excluded.

    Each entry:
        name, school, type ('swimmer'|'diver'), event, value (seconds or score),
        best (raw string), meet, date
    """
    event_map: Dict[str, List[Dict]] = {}  # event -> list of candidates

    for name, info in swimmers.items():
        school = info.get("school", "")
        athlete_type = info.get("type", "swimmer")

        for event, perf in info.get("events", {}).items():
            if "(Relay Split)" in event:
                continue
            if event not in INDIVIDUAL_EVENTS:
                continue

            is_diving = event in DIVING_EVENTS
            raw = perf.get("best", "")
            if is_diving:
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue
            else:
                value = _parse_seconds(raw)
                if value == float("inf"):
                    continue

            event_map.setdefault(event, []).append({
                "name": name,
                "school": school,
                "type": athlete_type,
                "value": value,
                "best": raw,
                "meet": perf.get("meet", ""),
                "date": perf.get("date", ""),
            })

    # For each event: deduplicate by athlete name (keep best), sort, assign points
    all_entries: List[Dict] = []

    for event, candidates in event_map.items():
        is_diving = event in DIVING_EVENTS

        # Deduplicate: one entry per athlete (best performance)
        best_per_athlete: Dict[str, Dict] = {}
        for c in candidates:
            n = c["name"]
            if n not in best_per_athlete:
                best_per_athlete[n] = c
            else:
                existing = best_per_athlete[n]["value"]
                new_val = c["value"]
                if is_diving:
                    if new_val > existing:
                        best_per_athlete[n] = c
                else:
                    if new_val < existing:
                        best_per_athlete[n] = c

        ranked = sorted(
            best_per_athlete.values(),
            key=lambda x: x["value"],
            reverse=is_diving,
        )

        for rank, entry in enumerate(ranked, 1):
            pts: float = INDIVIDUAL_POINTS.get(rank, 1.0 / rank)
            all_entries.append({
                "name": entry["name"],
                "school": entry["school"],
                "type": entry["type"],
                "event": event,
                "rank": rank,
                "predicted_points": pts,
                "best": entry["best"],
                "meet": entry["meet"],
                "date": entry["date"],
            })

    return all_entries


# ---------------------------------------------------------------------------
# Athlete bundle builder
# ---------------------------------------------------------------------------

def _build_athlete_bundles(all_entries: List[Dict]) -> List[Dict]:
    """
    Group entries by (school, name) and compute each athlete's best bundle.

    Each athlete's bundle is their top N events by predicted_points, where
    N = min(MAX_EVENTS_PER_ATHLETE, number of available events).

    Returns a list of dicts, each with:
        name, school, type, bundle (list of entries sorted by predicted_points
        desc), bundle_value (sum of predicted_points in bundle).
    """
    grouped: Dict[Tuple[str, str], List[Dict]] = {}
    for entry in all_entries:
        key = (entry["school"], entry["name"])
        grouped.setdefault(key, []).append(entry)

    bundles = []
    for (school, name), entries in grouped.items():
        sorted_by_pts = sorted(entries, key=lambda e: -e["predicted_points"])
        bundle = sorted_by_pts[:MAX_EVENTS_PER_ATHLETE]
        bundles.append({
            "name": name,
            "school": school,
            "type": entries[0]["type"],
            "bundle": bundle,
            "bundle_value": sum(e["predicted_points"] for e in bundle),
        })

    return bundles


# ---------------------------------------------------------------------------
# Greedy roster builder
# ---------------------------------------------------------------------------

def greedy_rosters(
    all_entries: List[Dict],
    target_teams: List[str] | None = None,
) -> Dict[str, Dict]:
    """
    Greedy athlete-level roster assignment.

    For each athlete, pre-computes their best 3-event bundle (sum of
    predicted points across their top events). Athletes are sorted by
    bundle value and assigned in that order, so an athlete who scores
    moderately in 3 events is preferred over one who scores slightly
    higher in only 1 event.

    Rules
    -----
    - Each athlete may be assigned to at most MAX_EVENTS_PER_ATHLETE (3) events.
    - Each team has a SCORING_BUDGET (18) of "athlete units":
        swimmer = 1 unit, diver = 1/3 unit.
    - Athletes are added to the team roster at most once; additional event
      assignments for an already-rostered athlete cost no extra budget.
    - When a new swimmer would be added (cost 1), the algorithm checks
      whether unrostered divers for that team (costing up to 1 unit total)
      would collectively yield more bundle points. If so, those divers are
      assigned first, and then the swimmer is still assigned immediately after
      (if budget remains).

    Returns
    -------
    Dict keyed by team name, each value:
        {
            "budget_used": float,
            "athletes": {
                <athlete_name>: {
                    "school": str,
                    "type": str,
                    "assignments": [
                        {"event": str, "rank": int, "predicted_points": float, "best": str},
                        ...
                    ]
                }
            }
        }
    """
    athlete_bundles = _build_athlete_bundles(all_entries)

    # Sort athletes by bundle value descending, breaking ties by best single
    # event (favoring a dominant event), then by name for determinism.
    athlete_bundles.sort(
        key=lambda a: (-a["bundle_value"],
                       -max(e["predicted_points"] for e in a["bundle"]),
                       a["name"]),
    )

    # Index bundles by (school, name) for the diver look-ahead
    bundle_by_key: Dict[Tuple[str, str], Dict] = {
        (a["school"], a["name"]): a for a in athlete_bundles
    }

    # Per-team state
    teams: Dict[str, Dict] = {}

    def _team(school: str) -> Dict:
        if school not in teams:
            teams[school] = {"budget_used": 0.0, "athletes": {}}
        return teams[school]

    def _budget_remaining(school: str) -> float:
        return SCORING_BUDGET - _team(school)["budget_used"]

    def _can_add_new(school: str, athlete_type: str) -> bool:
        cost = DIVER_COST if athlete_type == "diver" else 1.0
        return _budget_remaining(school) + 1e-9 >= cost

    def _assign(school: str, entry: Dict) -> None:
        """Assign entry to athlete; add to roster if new (budget already validated)."""
        team = _team(school)
        name = entry["name"]
        assignment = {
            "event": entry["event"],
            "rank": entry["rank"],
            "predicted_points": entry["predicted_points"],
            "best": entry["best"],
        }
        if name not in team["athletes"]:
            cost = DIVER_COST if entry["type"] == "diver" else 1.0
            team["budget_used"] += cost
            team["athletes"][name] = {
                "school": school,
                "type": entry["type"],
                "assignments": [assignment],
            }
        else:
            team["athletes"][name]["assignments"].append(assignment)

    def _assign_bundle(school: str, athlete: Dict) -> None:
        """Assign all events in an athlete's bundle."""
        team = _team(school)
        name = athlete["name"]
        already_assigned = set()
        if name in team["athletes"]:
            already_assigned = {a["event"] for a in team["athletes"][name]["assignments"]}
        remaining_slots = MAX_EVENTS_PER_ATHLETE - len(already_assigned)
        for entry in athlete["bundle"]:
            if remaining_slots <= 0:
                break
            if entry["event"] not in already_assigned:
                _assign(school, entry)
                already_assigned.add(entry["event"])
                remaining_slots -= 1

    def _top_unrostered_diver_bundles(school: str) -> Tuple[List[Dict], float]:
        """
        Find the best set of unrostered divers for this school that fit
        within 1.0 budget unit (the cost of one swimmer).

        For partially-rostered divers, only counts the value of their
        unassigned bundle events.

        Returns (list_of_athlete_bundle_dicts, total_remaining_value).
        """
        team = _team(school)
        # Collect diver bundles for this school, sorted by remaining value
        diver_candidates = []
        for ab in athlete_bundles:
            if ab["school"] != school or ab["type"] != "diver":
                continue
            name = ab["name"]
            if name in team["athletes"]:
                # Already rostered: marginal cost = 0, value = unassigned events only
                assigned_events = {a["event"] for a in team["athletes"][name]["assignments"]}
                remaining_entries = [e for e in ab["bundle"] if e["event"] not in assigned_events]
                remaining_value = sum(e["predicted_points"] for e in remaining_entries)
                if remaining_value <= 0:
                    continue
                diver_candidates.append((ab, 0.0, remaining_value))
            else:
                # Not yet rostered
                if not _can_add_new(school, "diver"):
                    continue
                diver_candidates.append((ab, DIVER_COST, ab["bundle_value"]))

        # Sort by remaining value descending
        diver_candidates.sort(key=lambda x: -x[2])

        # Greedily pack divers within 1.0 budget unit
        selected = []
        cost_used = 0.0
        total_value = 0.0
        for ab, cost, value in diver_candidates:
            if cost_used + cost > 1.0 + 1e-9:
                continue
            selected.append(ab)
            cost_used += cost
            total_value += value

        return selected, total_value

    # Main loop: iterate athletes by bundle value
    for athlete in athlete_bundles:
        school = athlete["school"]
        if target_teams and school not in target_teams:
            continue

        name = athlete["name"]
        athlete_type = athlete["type"]
        team = _team(school)

        # Already rostered (e.g. via earlier diver swap): assign remaining bundle events
        if name in team["athletes"]:
            _assign_bundle(school, athlete)
            continue

        # New athlete: check budget
        if not _can_add_new(school, athlete_type):
            continue

        # New swimmer: if divers offer more value per budget unit, pick them first.
        # Then still assign this swimmer (they remain next in line after the diver picks).
        if athlete_type == "swimmer":
            diver_picks, diver_total_value = _top_unrostered_diver_bundles(school)
            if diver_total_value > athlete["bundle_value"]:
                for diver_ab in diver_picks:
                    _assign_bundle(school, diver_ab)
                # Re-check budget: divers may have consumed the last available unit
                if not _can_add_new(school, athlete_type):
                    continue

        # Assign this athlete's full bundle
        _assign_bundle(school, athlete)

    return teams


# ---------------------------------------------------------------------------
# Relay helpers
# ---------------------------------------------------------------------------

def _get_relay_times(
    athlete_events: Dict,
    flat_key: str | None,
    relay_key: str | None,
    is_medley_back: bool = False,
) -> Dict | None:
    """
    Compute relay timing metrics for one athlete on one relay leg.

    Returns a dict with:
        flat_start    – individual flat-start time in seconds (None if unavailable)
        relay_split   – exchange-start relay split in seconds  (None if unavailable)
        exchange_time – best estimate for a non-leadoff leg
                        (relay_split, or flat_start − EXCHANGE_ADVANTAGE)
        leadoff_time  – best estimate for the leadoff leg
                        (flat_start, or relay_split + EXCHANGE_ADVANTAGE)
        leadoff_gap   – flat_start − relay_split; smaller means the athlete
                        benefits less from an exchange start (better leadoff)
    Returns None if no usable time exists.
    """
    flat_start = None
    relay_split = None

    if flat_key and flat_key in athlete_events:
        t = _parse_seconds(athlete_events[flat_key].get("best", ""))
        if t != float("inf"):
            flat_start = t

    if relay_key and relay_key in athlete_events:
        t = _parse_seconds(athlete_events[relay_key].get("best", ""))
        if t != float("inf"):
            relay_split = t

    if flat_start is None and relay_split is None:
        return None

    if is_medley_back:
        # Backstroke is always the medley relay leadoff (flat start, dives in).
        # No relay split exists for this leg; use individual time directly.
        if flat_start is None:
            return None
        return {
            "flat_start": flat_start,
            "relay_split": None,
            "exchange_time": flat_start,   # contribution to relay total
            "leadoff_time": flat_start,
            "leadoff_gap": float("inf"),   # not used for stroke-assigned medley legs
        }

    exchange_time = relay_split if relay_split is not None else flat_start - EXCHANGE_ADVANTAGE
    leadoff_time  = flat_start  if flat_start  is not None else relay_split + EXCHANGE_ADVANTAGE
    leadoff_gap   = (flat_start - relay_split) if (flat_start is not None and relay_split is not None) \
                    else float("inf")

    return {
        "flat_start": flat_start,
        "relay_split": relay_split,
        "exchange_time": exchange_time,
        "leadoff_time": leadoff_time,
        "leadoff_gap": leadoff_gap,
    }


def _fmt_relay_time(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}" if m >= 1 else f"{s:.3f}"


# ---------------------------------------------------------------------------
# Greedy relay assignment
# ---------------------------------------------------------------------------

def greedy_relay_assignment(
    rosters: Dict[str, Dict],
    swimmers_data: Dict[str, Any],
) -> Dict[str, Dict]:
    """
    Greedy relay assignment for all 5 SCIAC relay events (FR200, FR400, FR800,
    MED200, MED400). Must be called after greedy_rosters().

    Modifies rosters in-place: adds a "relay_count" field per athlete tracking
    the number of relay appearances (used to enforce MAX_TOTAL_EVENTS = 7).

    Rules
    -----
    - Only athletes already on the scoring roster may swim relays.
    - Each athlete may not exceed MAX_TOTAL_EVENTS (7) total events
      (individual assignments + relay appearances).
    - A relay: top-4 eligible swimmers by exchange_time; B relay: next 4.
    - Freestyle relay leadoff: swimmer with the smallest absolute gap between
      flat-start and relay-split time (benefits least from exchange start).
    - Freestyle relay legs 2–4: ordered slowest → fastest exchange_time.
    - Medley relay: fixed stroke order Back → Breast → Fly → Free.
      Back leg uses flat-start individual time; other legs use relay splits
      (or flat_start − EXCHANGE_ADVANTAGE if no relay split).

    Returns
    -------
    {
        team: {
            relay_id: {
                "A": {"legs": [...], "total_time": float} or None,
                "B": {"legs": [...], "total_time": float} or None,
            }
        }
    }
    Each leg dict: name, leg (1–4), is_leadoff, time_used, flat_start,
                   relay_split, and stroke (medley only).
    """
    # Initialise relay_count for every rostered athlete
    for team_data in rosters.values():
        for ath_data in team_data["athletes"].values():
            ath_data.setdefault("relay_count", 0)

    def _total_events(team: str, name: str) -> int:
        ath = rosters[team]["athletes"].get(name)
        if ath is None:
            return 0
        return len(ath["assignments"]) + ath.get("relay_count", 0)

    def _can_relay(team: str, name: str) -> bool:
        return _total_events(team, name) < MAX_TOTAL_EVENTS

    def _increment(team: str, name: str) -> None:
        rosters[team]["athletes"][name]["relay_count"] = \
            rosters[team]["athletes"][name].get("relay_count", 0) + 1

    relay_assignments: Dict[str, Dict] = {team: {} for team in rosters}

    # ------------------------------------------------------------------
    # Freestyle relays
    # ------------------------------------------------------------------
    for relay_id, keys in RELAY_EVENTS.items():
        flat_key  = keys["flat_key"]
        relay_key = keys["relay_key"]

        for team, team_data in rosters.items():
            # Collect eligible swimmers with timing data
            candidates = []
            for name, ath_data in team_data["athletes"].items():
                if ath_data["type"] == "diver":
                    continue
                if not _can_relay(team, name):
                    continue
                ev = swimmers_data.get(name, {}).get("events", {})
                info = _get_relay_times(ev, flat_key, relay_key)
                if info is None:
                    continue
                candidates.append({"name": name, **info})

            # Sort by exchange_time ascending; A relay = top 4, B relay = next 4
            candidates.sort(key=lambda x: x["exchange_time"])
            pools = {"A": candidates[:4], "B": candidates[4:8]}

            relay_assignments[team][relay_id] = {}

            for heat, pool in pools.items():
                if len(pool) < 4:
                    relay_assignments[team][relay_id][heat] = None
                    continue

                # Leadoff: smallest leadoff_gap (benefits least from exchange start)
                leadoff_idx = min(range(len(pool)), key=lambda i: pool[i]["leadoff_gap"])
                leadoff = pool[leadoff_idx]
                others  = [p for i, p in enumerate(pool) if i != leadoff_idx]

                # Legs 2–4: slowest → fastest exchange_time
                others_ordered = sorted(others, key=lambda x: x["exchange_time"], reverse=True)

                legs = [{
                    "name": leadoff["name"],
                    "leg": 1,
                    "is_leadoff": True,
                    "time_used": leadoff["leadoff_time"],
                    "flat_start": leadoff["flat_start"],
                    "relay_split": leadoff["relay_split"],
                }] + [
                    {
                        "name": s["name"],
                        "leg": i + 2,
                        "is_leadoff": False,
                        "time_used": s["exchange_time"],
                        "flat_start": s["flat_start"],
                        "relay_split": s["relay_split"],
                    }
                    for i, s in enumerate(others_ordered)
                ]

                total_time = sum(leg["time_used"] for leg in legs)
                relay_assignments[team][relay_id][heat] = {"legs": legs, "total_time": total_time}
                for leg in legs:
                    _increment(team, leg["name"])

    # ------------------------------------------------------------------
    # Medley relays
    # ------------------------------------------------------------------
    for relay_id, stroke_map in MEDLEY_EVENTS.items():
        for team, team_data in rosters.items():
            relay_assignments[team][relay_id] = {}

            # Pre-build per-stroke candidate lists (checked inline for capacity)
            stroke_candidates: Dict[str, List] = {}
            for stroke in MEDLEY_STROKE_ORDER:
                s_keys = stroke_map[stroke]
                is_back = (stroke == "Back")
                cands = []
                for name, ath_data in team_data["athletes"].items():
                    if ath_data["type"] == "diver":
                        continue
                    ev = swimmers_data.get(name, {}).get("events", {})
                    info = _get_relay_times(ev, s_keys["flat_key"], s_keys["relay_key"],
                                            is_medley_back=is_back)
                    if info is None:
                        continue
                    cands.append({"name": name, **info})
                cands.sort(key=lambda x: x["exchange_time"])
                stroke_candidates[stroke] = cands

            used_in_a: set = set()  # swimmers on A relay; excluded from B relay

            for heat in ["A", "B"]:
                # B relay may not reuse any swimmer from the A relay for this event
                assigned_this_relay: set = set(used_in_a) if heat == "B" else set()
                legs = []
                valid = True

                for stroke_pos, stroke in enumerate(MEDLEY_STROKE_ORDER):
                    chosen = None
                    for c in stroke_candidates[stroke]:
                        if c["name"] not in assigned_this_relay and _can_relay(team, c["name"]):
                            chosen = c
                            break
                    if chosen is None:
                        valid = False
                        break
                    assigned_this_relay.add(chosen["name"])
                    legs.append({
                        "name": chosen["name"],
                        "stroke": stroke,
                        "leg": stroke_pos + 1,
                        "is_leadoff": (stroke == "Back"),
                        "time_used": chosen["exchange_time"],
                        "flat_start": chosen["flat_start"],
                        "relay_split": chosen["relay_split"],
                    })

                if valid and len(legs) == 4:
                    total_time = sum(leg["time_used"] for leg in legs)
                    relay_assignments[team][relay_id][heat] = {"legs": legs, "total_time": total_time}
                    for leg in legs:
                        _increment(team, leg["name"])
                    if heat == "A":
                        used_in_a = {leg["name"] for leg in legs}
                else:
                    relay_assignments[team][relay_id][heat] = None

    return relay_assignments


# ---------------------------------------------------------------------------
# Relay evaluation
# ---------------------------------------------------------------------------

def evaluate_relay_scores(relay_assignments: Dict[str, Dict]) -> Dict[str, int]:
    """
    For each relay event, rank all A relays by total time (places 1–9) and
    all B relays by total time (places 1–9 within the B heat = overall 10–18).
    Award RELAY_POINTS_A / RELAY_POINTS_B accordingly.

    Returns {team_name: total_relay_points}.
    """
    team_scores: Dict[str, int] = {team: 0 for team in relay_assignments}

    all_relay_ids = list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys())

    for relay_id in all_relay_ids:
        for heat, points_table in [("A", RELAY_POINTS_A), ("B", RELAY_POINTS_B)]:
            entries = []
            for team, relays in relay_assignments.items():
                heat_data = relays.get(relay_id, {}).get(heat)
                if heat_data and heat_data.get("total_time") is not None:
                    entries.append({"team": team, "total_time": heat_data["total_time"]})
            entries.sort(key=lambda x: x["total_time"])
            for rank, entry in enumerate(entries):
                pts = points_table[rank] if rank < len(points_table) else 0
                if pts:
                    team_scores[entry["team"]] += pts

    return team_scores


# ---------------------------------------------------------------------------
# Relay pretty-print
# ---------------------------------------------------------------------------

def print_relays(relay_assignments: Dict[str, Dict], relay_scores: Dict[str, int]) -> None:
    all_relay_ids = list(RELAY_EVENTS.keys()) + list(MEDLEY_EVENTS.keys())

    for team in sorted(relay_assignments.keys()):
        team_pts = relay_scores.get(team, 0)
        print(f"\n{'='*60}")
        print(f"  {team}  |  relay pts: {team_pts}")
        print(f"{'='*60}")

        for relay_id in all_relay_ids:
            relays = relay_assignments[team].get(relay_id, {})
            for heat in ["A", "B"]:
                heat_data = relays.get(heat) if relays else None
                if heat_data is None:
                    print(f"  {relay_id} {heat}: —")
                    continue
                time_str = _fmt_relay_time(heat_data["total_time"])
                print(f"  {relay_id} {heat}  ({time_str})")
                for leg in heat_data["legs"]:
                    stroke_str  = f" {leg['stroke']:<7}" if "stroke" in leg else "        "
                    leadoff_str = " *" if leg["is_leadoff"] else "  "
                    fs  = f"{leg['flat_start']:.2f}s" if leg["flat_start"]  is not None else "  —  "
                    rs  = f"{leg['relay_split']:.2f}s" if leg["relay_split"] is not None else "  —  "
                    print(f"    Leg {leg['leg']}{stroke_str}{leadoff_str} {leg['name']:<26}"
                          f"  used={leg['time_used']:.2f}s  flat={fs}  split={rs}")


# ---------------------------------------------------------------------------
# Roster evaluation
# ---------------------------------------------------------------------------

def evaluate_rosters(rosters: Dict[str, Dict]) -> Dict[str, int]:
    """
    Compute each team's actual score after all rosters are finalised.

    For every event, collect only the athletes who were assigned to it,
    re-rank them by season best (since higher-ranked athletes in the full
    field may not have been assigned), and award INDIVIDUAL_POINTS by actual
    placement. Ranks beyond 16 score 0 (no fractional heuristic).

    Returns a dict of {team_name: total_points}.
    """
    # Collect all assigned (athlete, team, value) entries per event
    event_field: Dict[str, List[Dict]] = {}

    for team, data in rosters.items():
        for name, info in data["athletes"].items():
            is_diving = info["type"] == "diver"
            for assignment in info["assignments"]:
                event = assignment["event"]
                raw = assignment["best"]
                if is_diving:
                    try:
                        value = float(raw)
                    except (ValueError, TypeError):
                        continue
                else:
                    value = _parse_seconds(raw)
                    if value == float("inf"):
                        continue
                event_field.setdefault(event, []).append({
                    "team": team,
                    "name": name,
                    "value": value,
                    "is_diving": is_diving,
                })

    team_scores: Dict[str, int] = {team: 0 for team in rosters}

    for event, entries in event_field.items():
        is_diving = entries[0]["is_diving"]
        entries.sort(key=lambda x: x["value"], reverse=is_diving)
        for rank, entry in enumerate(entries, 1):
            pts = INDIVIDUAL_POINTS.get(rank, 0)
            if pts:
                team_scores[entry["team"]] += pts

    return team_scores


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

def print_rosters(rosters: Dict[str, Dict]) -> None:
    for team, data in sorted(rosters.items()):
        budget = data["budget_used"]
        athletes = data["athletes"]
        total_pts = sum(
            a["assignments"][i]["predicted_points"]
            for a in athletes.values()
            for i in range(len(a["assignments"]))
        )
        print(f"\n{'='*60}")
        print(f"  {team}  |  roster units: {budget:.2f}/{SCORING_BUDGET}  |  predicted pts: {total_pts:.1f}")
        print(f"{'='*60}")

        swimmers = {n: a for n, a in athletes.items() if a["type"] == "swimmer"}
        divers   = {n: a for n, a in athletes.items() if a["type"] == "diver"}

        for section_label, section in [("Swimmers", swimmers), ("Divers", divers)]:
            if not section:
                continue
            print(f"\n  {section_label}:")
            for name, info in sorted(section.items()):
                pts_list = [f"{ev['event']} (rank {ev['rank']}, {ev['predicted_points']:.0f}pts)"
                            for ev in info["assignments"]]
                print(f"    {name:<28}  {' | '.join(pts_list)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Greedy individual-event roster assignment from best_performances JSON."
    )
    parser.add_argument(
        "input",
        help="Path to best_performances JSON (e.g. '2025-26/best_performances_men.json').",
    )
    parser.add_argument(
        "--team", "-t",
        action="append",
        dest="teams",
        metavar="TEAM",
        help="Restrict output to this team (repeatable). Default: all teams.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON to stdout instead of human-readable text.",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write full results to a JSON file (e.g. results.json). "
             "Human-readable output is still printed unless --json is also given.",
    )
    args = parser.parse_args()

    data, path = load_json_from_data(args.input)
    print(f"Loaded: {path}", file=sys.stderr)

    swimmers = data.get("swimmers", {})
    entries = build_performance_entries(swimmers)
    print(f"Built {len(entries)} performance entries across "
          f"{len({e['event'] for e in entries})} events.", file=sys.stderr)

    rosters = greedy_rosters(entries, target_teams=args.teams)
    indiv_scores = evaluate_rosters(rosters)

    relay_assignments = greedy_relay_assignment(rosters, swimmers)
    relay_scores = evaluate_relay_scores(relay_assignments)

    results = {
        "input": str(path),
        "rosters": rosters,
        "relay_assignments": relay_assignments,
        "individual_scores": indiv_scores,
        "relay_scores": relay_scores,
        "total_scores": {
            t: indiv_scores.get(t, 0) + relay_scores.get(t, 0)
            for t in set(indiv_scores) | set(relay_scores)
        },
    }

    if args.output:
        out_path = Path(args.output)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results written to: {out_path}", file=sys.stderr)

    if args.json:
        print(json.dumps(results, indent=2))

        with open("rosters_output.json", "w") as f:
            json.dump(results, f, indent=2)
        print("JSON data saved to rosters_output.json", file=sys.stderr)
    else:
        print_rosters(rosters)
        print_relays(relay_assignments, relay_scores)

        print(f"\n{'='*60}")
        print("  Final scores (individual + relay)")
        print(f"{'='*60}")
        all_teams = sorted(set(indiv_scores) | set(relay_scores),
                           key=lambda t: -(indiv_scores.get(t, 0) + relay_scores.get(t, 0)))
        for team in all_teams:
            i_pts = indiv_scores.get(team, 0)
            r_pts = relay_scores.get(team, 0)
            print(f"  {team:<28} indiv={i_pts:>4}  relay={r_pts:>4}  total={i_pts + r_pts:>4}")


if __name__ == "__main__":
    main()
