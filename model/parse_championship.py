#!/usr/bin/env python3
"""
Parse SCIAC 2026 championship results PDF into structured JSON.

Extracts individual swim results, relay results, diving results,
and final team scores for comparison against model predictions.

Usage:
    python3 model/parse_championship.py [--debug] [--pages N-M]
Output:
    data/2025-26-pre-sciac/ground_truth/results.json
"""

import re
import json
import sys
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH  = REPO_ROOT / "data/2025-26-pre-sciac/ground_truth/SCIAC 2026 results.pdf"
OUT_PATH  = REPO_ROOT / "data/2025-26-pre-sciac/ground_truth/results.json"

# ---------------------------------------------------------------------------
# School canonicalization
# Covers both the body of the PDF (e.g. "Claremont-Mudd-Scripps-CA")
# and the team-score page (e.g. "Claremont-Mudd-Scripps").
# ---------------------------------------------------------------------------
_SCHOOL_MAP = {
    "Claremont-Mudd-Scripps-CA":      "Claremont-Mudd-Scripps",
    "Pomona-Pitzer-CA":               "Pomona-Pitzer",
    "Chapman University-CA":          "Chapman",
    "California Institute of Techno": "Caltech",
    "Occidental College-CA":          "Occidental",
    "Whittier College":               "Whittier",
    "University of Redlands":         "Redlands",
    "University of La Verne-CA":      "La Verne",
    "Cal Lutheran University":        "Cal Lutheran",
    # variants on team-score page
    "Pomona-Pitzer":                  "Pomona-Pitzer",
    "Claremont-Mudd-Scripps":         "Claremont-Mudd-Scripps",
    "Chapman University":             "Chapman",
    "Occidental College":             "Occidental",
    "University of La Verne":         "La Verne",
}


def _canon_school(raw: str) -> str:
    s = raw.strip()
    # Exact match first
    if s in _SCHOOL_MAP:
        return _SCHOOL_MAP[s]
    # Prefix match for truncated names
    for k, v in _SCHOOL_MAP.items():
        if s.startswith(k):
            return v
    return s


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
EVENT_HDR  = re.compile(r'^Event\s+(\d+)\s+(Men|Women)\s+(.+)$')
CONT_HDR   = re.compile(r'\(Event\s+(\d+)\s+(Men|Women)\s+(.+)\)')
HEAT_HDR   = re.compile(r'^(A|B|C)\s*[-–]\s*(Final|Prelims?|Time\s+Trial)\s*$', re.I)
TIME_TRIAL = re.compile(r'^-\s*Time\s+Trial\s*$', re.I)
SCORES_HDR = re.compile(r'^Scores?\s*[-–]\s*(Men|Women)\s*$', re.I)

# Swim time: optional X prefix, optional m: part, ss.xx, optional #/@
# Negative look-around prevents matching inside longer numbers (e.g. diving scores like 535.15)
SWIM_TIME = re.compile(r'(?<!\d)(?:X)?(?:\d{1,2}:)?\d{2}\.\d{2}[#@]?(?!\d)')
# Diving score: any number with decimal (including 3+ digit scores)
DIVE_SCORE = re.compile(r'(?<!\d)(?:X)?\d+\.\d+[#@]?(?!\d)')

# Allow optional leading '*' for tied places (Hy-Tek uses *13 to mark ties)
PLACE_PAT = re.compile(r'^\*?(\d+|---)\s+')
YEAR_PAT  = re.compile(r'\b(FR|SO|JR|SR)\b')


def _is_relay(event_name: str) -> bool:
    return "relay" in event_name.lower()


def _is_diving(event_name: str) -> bool:
    return "diving" in event_name.lower()


# ---------------------------------------------------------------------------
# Line parsers
# ---------------------------------------------------------------------------

def _parse_indiv(line: str, is_diving_event: bool):
    """
    Parse an individual (swim or dive) result row.

    Swim:  place  Last, First  YR  School  [prelim]  finals  [points]
    Dive:  place  Last, First  YR  School  score  [points]

    Returns a dict or None.
    """
    pm = PLACE_PAT.match(line)
    if not pm:
        return None
    place_str = pm.group(1)
    rest = line[pm.end():]

    ym = YEAR_PAT.search(rest)
    if not ym:
        return None
    year = ym.group(1)
    name = rest[:ym.start()].strip()
    if "," not in name:
        return None  # relay-leg row or malformed; skip

    after = rest[ym.end():].strip()

    if is_diving_event:
        times = list(DIVE_SCORE.finditer(after))
        if not times:
            return None
        school = _canon_school(after[:times[0].start()])
        score  = times[0].group(0)
        tail   = after[times[0].end():].strip()
        pm2    = re.match(r'^(\d+\.?\d*)', tail)
        pts    = float(pm2.group(1)) if pm2 else 0.0
        return {
            "place":        int(place_str) if place_str != "---" else None,
            "name":         name,
            "year":         year,
            "school":       school,
            "finals_score": score,
            "points":       pts,
            "exhibition":   score.startswith("X"),
        }

    # Swimming: handle DQ with no time
    if not SWIM_TIME.search(after) and "DQ" in after:
        dq_pos = after.find("DQ")
        return {
            "place":       None,
            "name":        name,
            "year":        year,
            "school":      _canon_school(after[:dq_pos]),
            "prelim_time": None,
            "finals_time": "DQ",
            "points":      0.0,
            "exhibition":  False,
        }

    times = list(SWIM_TIME.finditer(after))
    if not times:
        return None

    school  = _canon_school(after[:times[0].start()])
    prelim  = times[0].group(0) if len(times) >= 2 else None
    finals  = times[1].group(0) if len(times) >= 2 else times[0].group(0)
    last_tm = times[1] if len(times) >= 2 else times[0]

    tail = after[last_tm.end():].strip()
    # Hy-Tek formats tied points as "3. 50" (space in decimal); collapse it
    tail = re.sub(r'^(\d+)\.\s+(\d+)', r'\1.\2', tail)
    pm2  = re.match(r'^(\d+\.?\d*)', tail)
    pts  = float(pm2.group(1)) if pm2 else 0.0

    return {
        "place":       int(place_str) if place_str != "---" else None,
        "name":        name,
        "year":        year,
        "school":      school,
        "prelim_time": prelim,
        "finals_time": finals,
        "points":      pts,
        "exhibition":  finals.startswith("X") if finals else False,
        "tied":        line.lstrip().startswith("*"),
    }


def _parse_relay_row(line: str):
    """
    Parse a relay team result row.

    Format: place  School  A/B/C  time_or_DQ  [points]

    Returns dict or None.
    """
    pm = PLACE_PAT.match(line)
    if not pm:
        return None
    place_str = pm.group(1)
    rest = line[pm.end():]

    # Individual rows have year codes; relay team rows don't
    if YEAR_PAT.search(rest):
        return None

    # Find relay heat letter followed by time or DQ
    lm = re.search(
        r'\s+([ABC])\s+((?:X)?(?:\d{1,2}:)?\d{2}\.\d{2}[#@]?|DQ)',
        rest,
    )
    if not lm:
        return None

    relay_letter = lm.group(1)
    finals_raw   = lm.group(2)
    school       = _canon_school(rest[:lm.start()])

    tail = rest[lm.end():].strip()
    pm2  = re.match(r'^(\d+\.?\d*)', tail)
    pts  = float(pm2.group(1)) if pm2 else 0.0

    return {
        "place":       int(place_str) if place_str != "---" else None,
        "school":      school,
        "heat":        relay_letter,
        "finals_time": finals_raw if finals_raw != "DQ" else None,
        "points":      pts,
        "dq":          finals_raw == "DQ",
    }


def _parse_relay_legs(line: str):
    """
    Parse a relay leg-names row: '1) Last, First YR  2) Last, First YR  ...'

    Returns list of {leg, name, year} or None.
    """
    stripped = line.strip()
    if not stripped.startswith("1)"):
        return None
    legs = []
    for part in re.split(r'(?=\d\))', stripped):
        m = re.match(r'^(\d)\)\s+(.*?)\s+(FR|SO|JR|SR)\s*$', part.strip())
        if m:
            legs.append({
                "leg":  int(m.group(1)),
                "name": m.group(2).strip(),
                "year": m.group(3),
            })
    return legs if legs else None


# ---------------------------------------------------------------------------
# Team-score page parser
# ---------------------------------------------------------------------------

def _parse_team_scores(text: str) -> dict:
    """Parse 'Scores - Women / Men' section from the last page."""
    scores: dict[str, dict] = {"Men": {}, "Women": {}}
    gender = None
    for line in text.splitlines():
        m = SCORES_HDR.match(line.strip())
        if m:
            gender = m.group(1).capitalize()
            continue
        if gender is None:
            continue
        # Each physical line may have 1 or 2 entries side by side
        for em in re.finditer(r'\d+\.\s+(.*?)\s+(\d+\.?\d*)', line):
            school_raw = em.group(1).strip()
            score      = float(em.group(2))
            school     = _canon_school(school_raw)
            if school:
                scores[gender][school] = score
    return scores


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    debug      = "--debug" in sys.argv
    page_range = None
    for arg in sys.argv[1:]:
        if re.match(r'^\d+-\d+$', arg):
            lo, hi = arg.split("-")
            page_range = range(int(lo) - 1, int(hi))

    individual_results: list[dict] = []
    relay_results:      list[dict] = []
    diving_results:     list[dict] = []
    team_scores:        dict       = {}

    state = {
        "event_num":      None,
        "event_name":     None,
        "gender":         None,
        "is_relay_ev":    False,
        "is_diving_ev":   False,
        "heat":           None,
        "pending_relay":  None,   # relay entry waiting for its leg row
    }

    def _flush_relay():
        if state["pending_relay"]:
            relay_results.append(state["pending_relay"])
            state["pending_relay"] = None

    # Lines we always skip
    SKIP_RE = re.compile(
        r'^(?:HY-TEK|ALSO Swimming|2026 SCIAC|Results'
        r'|Name\s+Yr|Team\s+Relay'
        r'|Meet:|SCIAC:)',
        re.I,
    )

    with pdfplumber.open(PDF_PATH) as pdf:
        pages = pdf.pages
        if page_range:
            pages = [pdf.pages[i] for i in page_range if i < len(pdf.pages)]

        for page_i, page in enumerate(pages):
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            if debug:
                print(f"\n{'='*60}\nPage {page_i+1}\n{'='*60}")

            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if debug:
                    print(f"  {repr(stripped)}")

                if SKIP_RE.match(stripped):
                    continue

                # ── Event header ────────────────────────────────────────────
                m = EVENT_HDR.match(stripped)
                if m:
                    _flush_relay()
                    state.update(
                        event_num=int(m.group(1)),
                        event_name=m.group(3).strip(),
                        gender=m.group(2),
                        is_relay_ev=_is_relay(m.group(3)),
                        is_diving_ev=_is_diving(m.group(3)),
                        heat=None,
                    )
                    continue

                # ── Continuation header (event spans page break) ─────────────
                m = CONT_HDR.search(stripped)
                if m:
                    _flush_relay()
                    state.update(
                        event_num=int(m.group(1)),
                        event_name=m.group(3).strip(),
                        gender=m.group(2),
                        is_relay_ev=_is_relay(m.group(3)),
                        is_diving_ev=_is_diving(m.group(3)),
                    )
                    continue

                # ── Heat section header ──────────────────────────────────────
                m = HEAT_HDR.match(stripped)
                if m:
                    letter     = m.group(1).upper()
                    heat_label = m.group(2).strip()
                    if "final" in heat_label.lower():
                        state["heat"] = f"{letter}-Final"
                    elif "prelim" in heat_label.lower():
                        state["heat"] = "Prelims"
                    else:
                        state["heat"] = "Time Trial"
                    continue

                m = TIME_TRIAL.match(stripped)
                if m:
                    state["heat"] = "Time Trial"
                    continue

                if state["event_num"] is None:
                    continue

                # ── Relay leg row ────────────────────────────────────────────
                legs = _parse_relay_legs(stripped)
                if legs is not None:
                    if state["pending_relay"] is not None:
                        state["pending_relay"]["legs"] = legs
                        relay_results.append(state["pending_relay"])
                        state["pending_relay"] = None
                    continue

                # ── Relay event ──────────────────────────────────────────────
                if state["is_relay_ev"]:
                    r = _parse_relay_row(stripped)
                    if r:
                        _flush_relay()
                        state["pending_relay"] = {
                            "event_num":  state["event_num"],
                            "event_name": f"{state['gender']} {state['event_name']}",
                            "gender":     state["gender"],
                            "heat":       state["heat"],
                            **r,
                            "legs": [],
                        }
                        continue

                # ── Diving event ─────────────────────────────────────────────
                if state["is_diving_ev"]:
                    r = _parse_indiv(stripped, is_diving_event=True)
                    if r:
                        diving_results.append({
                            "event_num":  state["event_num"],
                            "event_name": f"{state['gender']} {state['event_name']}",
                            "gender":     state["gender"],
                            "heat":       state["heat"],
                            **r,
                        })
                        continue

                # ── Individual swim event ────────────────────────────────────
                r = _parse_indiv(stripped, is_diving_event=False)
                if r:
                    individual_results.append({
                        "event_num":  state["event_num"],
                        "event_name": f"{state['gender']} {state['event_name']}",
                        "gender":     state["gender"],
                        "heat":       state["heat"],
                        **r,
                    })

    _flush_relay()

    # ── Team scores from last page ───────────────────────────────────────────
    with pdfplumber.open(PDF_PATH) as pdf:
        last_text = pdf.pages[-1].extract_text(x_tolerance=3, y_tolerance=3) or ""
        team_scores = _parse_team_scores(last_text)

    # ── Compute per-team point totals from parsed results (sanity check) ────
    computed: dict[str, dict[str, float]] = {"Men": {}, "Women": {}}
    for rec in individual_results + diving_results:
        g = rec["gender"]
        s = rec["school"]
        computed[g][s] = computed[g].get(s, 0.0) + rec.get("points", 0.0)
    for rec in relay_results:
        g = rec["gender"]
        s = rec["school"]
        computed[g][s] = computed[g].get(s, 0.0) + rec.get("points", 0.0)

    output = {
        "individual_results": individual_results,
        "relay_results":      relay_results,
        "diving_results":     diving_results,
        "team_scores":        team_scores,
        "computed_team_scores": computed,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"Parsed {len(individual_results)} individual swim results")
    print(f"Parsed {len(relay_results)} relay results")
    print(f"Parsed {len(diving_results)} diving results")
    print(f"\nOfficial team scores (from PDF page 127):")
    for gender in ("Men", "Women"):
        print(f"  {gender}:")
        for team, score in sorted(team_scores[gender].items(), key=lambda x: -x[1]):
            computed_score = computed[gender].get(team, 0.0)
            print(f"    {team:40s}  official={score:7.1f}  computed={computed_score:7.1f}")
    print(f"\nOutput: {OUT_PATH}")


if __name__ == "__main__":
    main()
