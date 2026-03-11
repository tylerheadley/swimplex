#!/usr/bin/env python3
"""
process_results.py — Build event rankings and athlete profiles from parsed results.

Usage:
    python3 process_results.py --season 2025-26 --gender Men
    python3 process_results.py --season 2025-26 --gender Women

Output (in data/<season>/):
    event_rankings_<gender>.json
        {
          "season": "2025-26", "gender": "Men",
          "individual": {
            "<event>": {
              "1": {"name":..,"school":..,"year":..,"age":..,"time":<seconds>|null,
                    "meet":..,"date":..,"place":..},
              ...
            }
          },
          "relays": {
            "<event>": {
              "1": {"team":..,"school":..,"time":<seconds>|null,
                    "meet":..,"date":..,"place":..},
              ...
            }
          }
        }

    athlete_profiles_<gender>.json  (same numeric time/score fields per entry)

Relay-leg rules:
    relay_leg == 0, is_relay == False  →  individual section (regular swim)
    relay_leg == 1                      →  individual section (flat-start leadoff,
                                           equivalent to individual; no relay-split flag)
    relay_leg >= 2                      →  "(Relay Split)" section

Event ordering:
    Individual section — standard yard first, then non-standard:
      50/100/200/500/1000/1650 Yd Freestyle  (each + its relay splits)
      50/100/200 Yd Butterfly / Backstroke / Breaststroke  (each + splits)
      200/400 Yd IM  (+ splits)
      1 mtr / 3 mtr Diving
      → all other events sorted by (distance asc, stroke: free/fly/back/breast/IM/…)

    Relay section — standard yard first, then non-standard:
      200/400/800 Yd Freestyle Relay, 200/400 Yd Medley Relay
      → all other relays sorted by (distance asc, stroke order)
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    from sklearn.mixture import GaussianMixture
    import numpy as np
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MMSS_RE           = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")
_INVALID_PERF      = {"DQ", "NT", "NP", "NS", "SCR", "---", "DNF"}
_TRAILING_SYMS_RE  = re.compile(r"[@#$%!]+$")
_TRAILING_CODE_RE  = re.compile(r"\s+[WM](?:FR|SO|JR|SR|\d{2})$")
_TRAILING_INIT_RE  = re.compile(r"\s+[A-Za-z]$")
_LEADING_PREFIX_RE = re.compile(r"^[A-Z]\.\s*")
_YEAR_VALUES       = {"FR", "SO", "JR", "SR"}
_VALID_AGE_RE      = re.compile(r"^\d{1,2}$")

# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """
    Normalise an athlete name to a canonical "Last, First" form.

    Steps applied in order:
    1. "First Last" (no comma) → "Last, First"   (PDFs that invert name order)
    2. Strip leading team/gender identifier, e.g. "M.Kiss" → "Kiss"
    3. Strip trailing school/year codes: WSO WFR MSO M18 W21 WJR …
    4. Strip trailing middle initial (single letter, any case)
    5. Strip orphaned trailing comma  ("Vanluvanee, " → "Vanluvanee")
    6. Title-case all-uppercase first names that contain a vowel
       ("Zheng, BO" → "Zheng, Bo") while leaving initialism-style
       abbreviations alone (AJ, DJ, CJ — no vowels → unchanged)
    """
    name = name.strip()

    # 1. Invert "First Last" → "Last, First"
    if "," not in name:
        parts = name.split()
        if len(parts) >= 2:
            name = f"{parts[-1]}, {' '.join(parts[:-1])}"

    # 2. Strip leading single-letter team/gender prefix ("M.Kiss" → "Kiss")
    name = _LEADING_PREFIX_RE.sub("", name)

    # 3. Strip trailing school/year/gender codes (WSO, WFR, W18, MSO, M21 …)
    name = _TRAILING_CODE_RE.sub("", name)

    # 4. Strip trailing middle initial (e.g. " J" or stray lowercase " u")
    name = _TRAILING_INIT_RE.sub("", name)

    # 5. Strip orphaned trailing comma
    name = re.sub(r",\s*$", "", name).strip()

    # 6. Title-case all-uppercase first names that look like real words
    if "," in name:
        last, first = name.split(",", 1)
        first = first.strip()
        if first and first == first.upper() and first.isalpha():
            if any(c in "AEIOU" for c in first):   # has a vowel → real word
                first = first.title()
        name = f"{last}, {first}"

    return name


# Manually-verified same-person name pairs that differ in spelling/nickname.
_MANUAL_NAME_ALIASES: dict[str, str] = {
    "Maccalla, Sebass":      "Maccalla, Sebas",
    "Zane, Kamakeeponolahu": "Zane, Kamakeeponolahi",
    "Calloway, Trenten":     "Calloway, Trent",
    "Williams, Isabella":    "Williams, Bella",
    "Graceffa, Gabriel":     "Graceffa, Gabe",
    "Lucore, Nikolas":       "Lucore, Niko",
}


def _build_name_aliases(norm_names: list[str]) -> dict[str, str]:
    """
    Build a mapping from variant name forms to canonical names.

    1. Case-variant resolution: within each case-insensitive group, pick the
       most frequent capitalisation (e.g. "Deboom, Poet" → "DeBoom, Poet").
    2. Last-name-only merging: map bare "LastName" → "LastName, FirstName" when
       exactly one full form exists for that last name (handles truncated names
       from PDFs that drop the first name).
    """
    # 1. Case-variant: group by lowercase, tally occurrences
    case_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for n in norm_names:
        case_counts[n.lower()][n] += 1

    alias: dict[str, str] = {}
    for lower_n, counts in case_counts.items():
        canonical = max(counts, key=counts.__getitem__)
        for variant in counts:
            if variant != canonical:
                alias[variant] = canonical

    # 2. Last-name-only merging
    canonical_names: set[str] = {alias.get(n, n) for n in set(norm_names)}
    last_to_full: dict[str, list[str]] = defaultdict(list)
    for cn in canonical_names:
        if "," in cn:
            last = cn.split(",", 1)[0].strip()
            last_to_full[last].append(cn)

    for n in set(norm_names):
        if "," not in n:
            cn = alias.get(n, n)
            if "," not in cn:
                full_forms = last_to_full.get(cn, [])
                if len(full_forms) == 1:
                    alias[n] = full_forms[0]

    return alias


# ---------------------------------------------------------------------------
# School canonicalisation
# ---------------------------------------------------------------------------

_SCHOOL_MAP: dict[str, str] = {
    # Claremont-Mudd-Scripps (all variants, including letter/year-prefixed)
    "CMS-CA":                         "Claremont-Mudd-Scripps",
    "Claremont-Mudd-Scripps-CA":      "Claremont-Mudd-Scripps",
    "C 21 CMS-CA":                    "Claremont-Mudd-Scripps",
    "D 20 CMS-CA":                    "Claremont-Mudd-Scripps",
    "R 21 CMS-CA":                    "Claremont-Mudd-Scripps",
    "V 19 CMS-CA":                    "Claremont-Mudd-Scripps",
    # Cal Lutheran
    "Cal Lutheran University":        "Cal Lutheran",
    "California Lutheran":            "Cal Lutheran",
    "California Lutheran University": "Cal Lutheran",
    # Caltech
    "California Institute":           "Caltech",
    "California Institute of Techno": "Caltech",
    # Chapman
    "Chapman University":             "Chapman",
    "Chapman University-CA":          "Chapman",
    # Occidental
    "Occidental College":             "Occidental",
    "Occidental College-CA":          "Occidental",
    # Pomona-Pitzer
    "Pomona-Pitzer":                  "Pomona-Pitzer",
    "Pomona-Pitzer-CA":               "Pomona-Pitzer",
    # La Verne
    "University of La Verne-CA":      "La Verne",
    # Redlands
    "University of Redlands":         "Redlands",
    "University of Redlands-CA":      "Redlands",
    # Whittier
    "Whittier College":               "Whittier",
    "Whittier College-CA":            "Whittier",
}


def _canonicalize_school(school: str) -> str:
    if school in _SCHOOL_MAP:
        return _SCHOOL_MAP[school]
    # Catch any remaining CMS variants with letter/number prefix (e.g. "X 22 CMS-CA")
    if re.search(r"\bCMS\b", school):
        return "Claremont-Mudd-Scripps"
    return school


# ---------------------------------------------------------------------------
# Performance value parsing
# ---------------------------------------------------------------------------

def _clean_raw(raw: str) -> str:
    """Strip Hy-Tek qualifier symbols and normalise 'DQ DQ' → 'DQ'."""
    val = _TRAILING_SYMS_RE.sub("", raw.strip()).strip()
    val = re.sub(r"^DQ\s+DQ$", "DQ", val, flags=re.IGNORECASE)
    return val


def _to_seconds(val: str) -> float | None:
    """Convert a cleaned time/score string to a float, or None if invalid."""
    if not val or val.upper() in _INVALID_PERF:
        return None
    m = _MMSS_RE.match(val)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(val)
    except ValueError:
        return None


def _parse_performance(raw: str, diving: bool) -> tuple[str, object]:
    """
    Returns (field_name, value).
    - Diving events  → field "score",  value is float (or None if invalid)
    - Swim events    → field "time",   value is cleaned string (e.g. "1:54.66",
                       "DQ", "NT") — never converted to seconds
    """
    cleaned = _clean_raw(raw)
    if diving:
        return "score", _to_seconds(cleaned)   # float or None
    # Swim: keep as string; empty/blank → None.
    # Bare integers (no colon/decimal) are place numbers mis-parsed as times.
    if cleaned and re.fullmatch(r"\d+", cleaned):
        return "time", None
    return "time", cleaned if cleaned else None


def _perf_sort_key(entry: dict, diving: bool) -> tuple:
    """Valid results before invalid; swim: ascending (by seconds); dive: descending."""
    if diving:
        val = entry.get("score")
        if val is None:
            return (1, 0.0)
        return (0, -val)
    else:
        raw = entry.get("time")
        val = _to_seconds(raw) if isinstance(raw, str) else None
        if val is None:
            return (1, 0.0)
        return (0, val)


# ---------------------------------------------------------------------------
# Age / academic-year classification
# ---------------------------------------------------------------------------

def _classify_age(val: str) -> tuple[str, str]:
    """Returns (year, age) where year ∈ {FR,SO,JR,SR} and age is numeric."""
    if val.upper() in _YEAR_VALUES:
        return val.upper(), ""
    if _VALID_AGE_RE.match(val):
        return "", val
    return "", ""


# ---------------------------------------------------------------------------
# Event name normalisation
# ---------------------------------------------------------------------------

def _normalize_event_name(name: str, relay_leg: int = 0, gender: str = "") -> str:
    """
    - Keep 'Time Trial' suffix so TT results remain in their own event bucket
      and do not contaminate regular-event rankings.
    - relay_leg >= 1: ensure gender prefix is present.
    - relay_leg >= 2: ensure '(Relay Split)' suffix is present.
    """
    s = re.sub(r"\s+", " ", name).strip()

    if relay_leg >= 1:
        has_prefix = bool(re.match(r"^(Men|Women|Mixed)\s+", s, re.IGNORECASE))
        if gender and not has_prefix:
            s = f"{gender} {s}"

    if relay_leg >= 2:
        if "(Relay Split)" not in s:
            s = s + " (Relay Split)"

    return s


# ---------------------------------------------------------------------------
# Canonical event ordering
# ---------------------------------------------------------------------------

_STD_INDIV = [
    (50,   "freestyle"),
    (100,  "freestyle"),
    (200,  "freestyle"),
    (500,  "freestyle"),
    (1000, "freestyle"),
    (1650, "freestyle"),
    (50,   "butterfly"),
    (100,  "butterfly"),
    (200,  "butterfly"),
    (50,   "backstroke"),
    (100,  "backstroke"),
    (200,  "backstroke"),
    (50,   "breaststroke"),
    (100,  "breaststroke"),
    (200,  "breaststroke"),
    (200,  "im"),
    (400,  "im"),
]
_STD_INDIV_IDX = {v: i for i, v in enumerate(_STD_INDIV)}

_STD_RELAY = [
    (200, "freestyle relay"),
    (400, "freestyle relay"),
    (800, "freestyle relay"),
    (200, "medley relay"),
    (400, "medley relay"),
]
_STD_RELAY_IDX = {v: i for i, v in enumerate(_STD_RELAY)}

_STD_DIVING_IDX = {1: 0, 3: 1}

_STROKE_ORDER = {
    "freestyle":        0,
    "butterfly":        1,
    "backstroke":       2,
    "breaststroke":     3,
    "im":               4,
    "medley":           4,
    "freestyle relay":  0,
    "butterfly relay":  1,
    "backstroke relay": 2,
    "breaststroke relay": 3,
    "medley relay":     4,
}


def _parse_event(name: str) -> dict:
    s = re.sub(r"^(Men|Women|Mixed)\s+", "", name, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    is_split = "(Relay Split)" in s
    s = s.replace("(Relay Split)", "").strip()
    m = re.match(
        r"^(\d+(?:\.\d+)?)\s+(Yard|Meter|LC\s+Meter|mtr)\s+(.+)$", s, re.IGNORECASE
    )
    if m:
        dist   = float(m.group(1))
        unit   = re.sub(r"\s+", " ", m.group(2)).lower()
        stroke = re.sub(r"^individual medley$", "im", m.group(3).strip().lower())
        return {"dist": dist, "unit": unit, "stroke": stroke, "is_split": is_split}
    return {"dist": 0.0, "unit": "", "stroke": s.lower(), "is_split": is_split}


def _is_diving(event_name: str) -> bool:
    return "diving" in event_name.lower()


def _indiv_sort_key(event_name: str) -> tuple:
    p = _parse_event(event_name)
    dist, unit, stroke, is_split = p["dist"], p["unit"], p["stroke"], p["is_split"]
    if "mtr" in unit and "diving" in stroke:
        return (1, _STD_DIVING_IDX.get(int(dist), len(_STD_DIVING_IDX)), 0)
    if unit == "yard":
        idx = _STD_INDIV_IDX.get((int(dist), stroke))
        if idx is not None:
            return (0, idx, 1 if is_split else 0)
    return (2, dist, _STROKE_ORDER.get(stroke, 99), 1 if is_split else 0)


def _relay_sort_key(event_name: str) -> tuple:
    p = _parse_event(event_name)
    dist, unit, stroke = p["dist"], p["unit"], p["stroke"]
    if unit == "yard":
        idx = _STD_RELAY_IDX.get((int(dist), stroke))
        if idx is not None:
            return (0, idx)
    return (1, dist, _STROKE_ORDER.get(stroke, 99))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _strip_gender(name: str) -> str:
    """Remove leading 'Men / Women / Mixed' from an event name."""
    return re.sub(r"^(Men|Women|Mixed)\s+", "", name, flags=re.IGNORECASE).strip()


def _ranked_dict(entries: list[dict], diving: bool) -> dict:
    sorted_ = sorted(entries, key=lambda e: _perf_sort_key(e, diving))
    return {str(i + 1): e for i, e in enumerate(sorted_)}


def _canonical(votes: dict[str, int]) -> str:
    return max(votes, key=votes.__getitem__) if votes else ""


# ---------------------------------------------------------------------------
# Dive-format classification (6-dive vs 11-dive list)
# ---------------------------------------------------------------------------

# Hard-threshold boundaries — no D3 6-dive list reaches 450; no 11-dive list
# (at D3 competitive level) falls below 200.
_DIVE_11_THRESHOLD = 450.0
_DIVE_6_THRESHOLD  = 200.0
_DIVE_LOW_CONF     = 0.80   # warn below this GMM posterior confidence


def _dive_board(event_name: str) -> str:
    """Return '1 mtr' or '3 mtr' from a diving event name, or '' if unrecognised."""
    if "1 mtr" in event_name:
        return "1 mtr"
    if "3 mtr" in event_name:
        return "3 mtr"
    return ""


# Key type for dive-format classification: (meet_name, board)
# Board is "1 mtr" or "3 mtr" — classified independently because teams sometimes
# do 6 dives on one board and 11 on the other within the same meet.
_DiveKey = tuple[str, str]


def _classify_dive_format(
    current_rows: list[dict],
    aux_rows: list[list[dict]] | None = None,
) -> dict[_DiveKey, tuple[str, float]]:
    """
    Classify each (meet, board) pair in *current_rows* as "6-dive" or "11-dive".

    Keyed by (meet_name, board) where board is "1 mtr" or "3 mtr", so that
    a meet where 1m uses 11 dives and 3m uses 6 dives is handled correctly.
    Men and women on the same board at the same meet share a format, so their
    scores are pooled when computing the per-(meet, board) max.

    Strategy
    --------
    1. Compute the max score per (meet, board) across both genders.
    2. Hard thresholds for unambiguous cases:
         max >= 450  →  "11-dive"  (no D3 diver reaches 450 on 6 dives)
         max <  200  →  "6-dive"   (unlikely to fall below 200 on 11 dives)
    3. 2-component GMM on all (meet, board) max scores pooled across current
       and any auxiliary seasons. Higher-mean component = "11-dive".
    4. Confidence = GMM posterior probability for the assigned component.

    Returns
    -------
    {(meet_name, board): ("6-dive" | "11-dive", confidence)}
    Only (meet, board) pairs that appear in *current_rows* are returned.
    """
    def _group_max_scores(rows: list[dict]) -> dict[_DiveKey, float]:
        """Max diving score per (meet_name, board)."""
        group_max: dict[_DiveKey, float] = {}
        for r in rows:
            if not _is_diving(r.get("event_name", "")):
                continue
            board = _dive_board(r.get("event_name", ""))
            if not board:
                continue
            try:
                score = float(r["finals"])
            except (ValueError, TypeError, KeyError):
                continue
            key = (r["meet_name"], board)
            if key not in group_max or score > group_max[key]:
                group_max[key] = score
        return group_max

    current_max  = _group_max_scores(current_rows)
    aux_maxes: list[dict[_DiveKey, float]] = [_group_max_scores(ar) for ar in (aux_rows or [])]

    if not current_max:
        return {}

    # Pool all max scores for GMM fitting (values only — keys don't matter for fitting)
    all_max_values: list[float] = list(current_max.values())
    for am in aux_maxes:
        all_max_values.extend(am.values())

    # Hard-threshold assignments for current (meet, board) pairs
    result: dict[_DiveKey, tuple[str, float]] = {}
    gmm_candidates: list[_DiveKey] = []

    for key, max_score in current_max.items():
        if max_score >= _DIVE_11_THRESHOLD:
            result[key] = ("11-dive", 1.0)
        elif max_score < _DIVE_6_THRESHOLD:
            result[key] = ("6-dive", 1.0)
        else:
            gmm_candidates.append(key)

    if not gmm_candidates:
        return result

    if not _SKLEARN_AVAILABLE:
        mid = (_DIVE_11_THRESHOLD + _DIVE_6_THRESHOLD) / 2
        for key in gmm_candidates:
            fmt = "11-dive" if current_max[key] >= mid else "6-dive"
            result[key] = (fmt, 0.5)
        print(
            "WARNING: scikit-learn not installed — GMM dive classification unavailable. "
            "Install with: pip install scikit-learn numpy",
            file=sys.stderr,
        )
        return result

    # Fit 2-component GMM on all pooled max scores
    X = np.array(all_max_values).reshape(-1, 1)
    gmm = GaussianMixture(n_components=2, random_state=42)
    gmm.fit(X)

    comp_means  = gmm.means_.flatten()
    eleven_comp = int(np.argmax(comp_means))

    for key in gmm_candidates:
        x     = np.array([[current_max[key]]])
        proba = gmm.predict_proba(x)[0]
        conf  = float(proba[eleven_comp])
        fmt   = "11-dive" if conf >= 0.5 else "6-dive"
        if fmt == "6-dive":
            conf = float(proba[1 - eleven_comp])
        result[key] = (fmt, conf)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build event rankings and athlete profiles for a season/gender"
    )
    ap.add_argument("--season", required=True, metavar="YYYY-YY")
    ap.add_argument("--gender", required=True, choices=["Men", "Women", "Mixed"])
    ap.add_argument(
        "--aux-seasons", nargs="*", metavar="YYYY-YY", default=[],
        help="Additional seasons whose diving data is pooled when fitting the GMM "
             "(improves classification stability). Files that don't exist are skipped.",
    )
    args = ap.parse_args()

    results_path = DATA_DIR / args.season / "results.json"
    if not results_path.exists():
        ap.error(
            f"Results file not found: {results_path}\n"
            f"Run: python3 main.py --parse --season {args.season}"
        )

    rows: list[dict] = json.loads(results_path.read_text())

    # Load auxiliary seasons for GMM fitting (silently skip missing files)
    aux_rows: list[list[dict]] = []
    for aux_season in args.aux_seasons:
        aux_path = DATA_DIR / aux_season / "results.json"
        if aux_path.exists():
            aux_rows.append(json.loads(aux_path.read_text()))
        else:
            print(f"NOTE: aux-season file not found, skipping: {aux_path}", file=sys.stderr)

    # ── Classify dive meets (6-dive vs 11-dive) ───────────────────────────────
    # Done on raw rows (before name/school normalisation) since only meet_name,
    # event_name, and finals are needed — those fields are stable pre-normalisation.
    dive_format: dict[str, tuple[str, float]] = _classify_dive_format(rows, aux_rows)
    # Print classification summary and warnings
    if dive_format:
        print("Dive format classification:", file=sys.stderr)
        for (meet, board) in sorted(dive_format, key=lambda k: (-dive_format[k][1], k)):
            fmt, conf = dive_format[(meet, board)]
            flag = "  *** LOW CONFIDENCE ***" if conf < _DIVE_LOW_CONF else ""
            print(f"  {fmt}  (conf={conf:.2f})  [{board}]  {meet}{flag}", file=sys.stderr)

    # Normalise names, schools, and event names
    for r in rows:
        r["name"]       = _normalize_name(r["name"])
        r["school"]     = _canonicalize_school(r.get("school", ""))
        r["event_name"] = _normalize_event_name(
            r["event_name"], r["relay_leg"], r["gender"]
        )

    # ── Resolve name aliases (case variants + last-name-only + manual) ────────
    _name_aliases = _build_name_aliases([r["name"] for r in rows])
    for r in rows:
        n = _name_aliases.get(r["name"], r["name"])
        r["name"] = _MANUAL_NAME_ALIASES.get(n, n)

    rows = [r for r in rows if r["gender"] == args.gender]

    # ── Accumulate into event buckets ─────────────────────────────────────────

    individual_events: dict[str, list[dict]] = defaultdict(list)
    relay_events:      dict[str, list[dict]] = defaultdict(list)
    _relay_seen:       set[tuple]            = set()  # dedup relay team rows

    athlete_events: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    school_votes:   dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    year_votes:     dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    age_votes:      dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        event  = r["event_name"]
        diving = _is_diving(event)
        field, value = _parse_performance(r["finals"], diving)
        meet   = r["meet_name"]
        date   = r["meet_date"]
        place  = r["place"]
        yr, ag = _classify_age(r.get("age", ""))

        if r["is_relay"] and r["relay_leg"] == 0:
            # ── Relay team row ────────────────────────────────────────────────
            # Skip exact duplicates that slipped past the main.py dedup
            # (can happen when qualifier symbols differ, e.g. "1:21.57#" vs "1:21.57").
            relay_dedup_key = (event, r["school"], field, str(value), meet)
            if relay_dedup_key in _relay_seen:
                continue
            _relay_seen.add(relay_dedup_key)

            entry: dict = {
                "team":   r["name"],
                "school": r["school"],
                field:    value,
                "meet":   meet,
                "date":   date,
                "place":  place,
            }
            if r["relay_swimmers"]:
                entry["swimmers"] = r["relay_swimmers"]
            relay_events[event].append(entry)

        else:
            # ── Individual swim, leadoff (relay_leg=1), or relay split (>=2) ─
            entry = {
                "name":   r["name"],
                "school": r["school"],
                "year":   yr,
                "age":    ag,
                field:    value,
                "meet":   meet,
                "date":   date,
                "place":  place,
            }
            if r["relay_leg"] >= 2:
                entry["relay_leg"] = r["relay_leg"]
            individual_events[event].append(entry)

            # Athlete profile accumulation
            name = r["name"]
            school_votes[name][r["school"]] += 1
            if yr:
                year_votes[name][yr] += 1
            if ag:
                age_votes[name][ag] += 1

            ath_entry = {field: value, "meet": meet, "date": date, "place": place}
            if r["relay_leg"] >= 2:
                ath_entry["relay_leg"] = r["relay_leg"]
            if _is_diving(event):
                board = _dive_board(event)
                key   = (meet, board)
                if key in dive_format:
                    fmt, conf = dive_format[key]
                    ath_entry["dive_format"]      = fmt
                    ath_entry["dive_format_conf"] = round(conf, 3)
            athlete_events[name][event].append(ath_entry)

    # ── Build event rankings ───────────────────────────────────────────────────

    def build_section(buckets: dict[str, list[dict]], sort_key_fn) -> dict:
        return {
            _strip_gender(ev): _ranked_dict(buckets[ev], _is_diving(ev))
            for ev in sorted(buckets, key=sort_key_fn)
        }

    event_rankings = {
        "season":     args.season,
        "gender":     args.gender,
        "individual": build_section(individual_events, _indiv_sort_key),
        "relays":     build_section(relay_events,      _relay_sort_key),
    }

    # ── Build athlete profiles ─────────────────────────────────────────────────

    athletes_out: dict[str, dict] = {}
    for name in sorted(athlete_events):
        events_out: dict[str, dict] = {}
        for ev in sorted(athlete_events[name], key=_indiv_sort_key):
            events_out[_strip_gender(ev)] = _ranked_dict(athlete_events[name][ev], _is_diving(ev))

        # Classify as swimmer or diver.
        # Count distinct event types, excluding relay splits (those are assigned,
        # not self-entered) so a diver who legs a relay doesn't flip to "swimmer".
        n_dive = sum(1 for ev in events_out if _is_diving(ev))
        n_swim = sum(1 for ev in events_out
                     if not _is_diving(ev) and "(Relay Split)" not in ev)
        if n_dive > 0 and n_swim > 0:
            # "hybrid" if the minority type is at least 1/3 of the majority type
            if min(n_dive, n_swim) * 3 >= max(n_dive, n_swim):
                athlete_type = "hybrid"
            else:
                athlete_type = "diver" if n_dive > n_swim else "swimmer"
            print(
                f"WARNING mixed swimmer/diver: {name:<30}  ({_canonical(school_votes[name])})  "
                f"swim_events={n_swim}  dive_events={n_dive}  → {athlete_type}",
                file=sys.stderr,
            )
        elif n_dive > 0:
            athlete_type = "diver"
        else:
            athlete_type = "swimmer"

        athletes_out[name] = {
            "school": _canonical(school_votes[name]),
            "year":   _canonical(year_votes[name]),
            "age":    _canonical(age_votes[name]),
            "type":   athlete_type,
            "events": events_out,
        }

    athlete_profiles = {
        "season":   args.season,
        "gender":   args.gender,
        "athletes": athletes_out,
    }

    # ── Write outputs ──────────────────────────────────────────────────────────
    out_dir = DATA_DIR / args.season

    rankings_path = out_dir / f"event_rankings_{args.gender.lower()}.json"
    rankings_path.write_text(json.dumps(event_rankings, indent=2))

    profiles_path = out_dir / f"athlete_profiles_{args.gender.lower()}.json"
    profiles_path.write_text(json.dumps(athlete_profiles, indent=2))

    n_ind = len(event_rankings["individual"])
    n_rel = len(event_rankings["relays"])
    n_ath = len(athletes_out)
    print(f"Written: {rankings_path}")
    print(f"  {n_ind} individual events, {n_rel} relay events")
    print(f"Written: {profiles_path}")
    print(f"  {n_ath} athletes")


if __name__ == "__main__":
    main()
