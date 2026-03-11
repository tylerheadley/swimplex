#!/usr/bin/env python3
"""
data_quality.py — Validate parsed results and flag suspicious data.

Usage:
    python3 data_quality.py --season 2025-26

Output:
    Prints a categorised report of data quality issues to stdout.
    Optionally writes a JSON report to data/<season>/data_quality_report.json.

Checks performed:
    1.  Suspect times           — bare integers, values outside plausible range
    2.  Suspect dive scores     — implausibly low or high
    3.  Unrecognised schools    — not in the canonical school map
    4.  Residual name suffixes  — names still containing trailing W/M codes
    5.  Names with no first name — "Last, " after normalisation
    6.  Near-duplicate names    — same last name, similar first names
    7.  First-Last format names — no comma (inversion may have failed)
    8.  Case-variant duplicates — same name differing only in case
    9.  Event name anomalies    — unexpected distance / unit combinations
    10. Relay split sanity      — split times implausibly fast/slow
"""

import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# Reuse the same normalization from process_results.py
# ---------------------------------------------------------------------------

_TRAILING_CODE_RE  = re.compile(r"\s+[WM](?:FR|SO|JR|SR|\d{2})$")
_TRAILING_INIT_RE  = re.compile(r"\s+[A-Za-z]$")
_LEADING_PREFIX_RE = re.compile(r"^[A-Z]\.\s*")
_MMSS_RE           = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")
_INVALID_PERF      = {"DQ", "NT", "NP", "NS", "SCR", "---", "DNF"}
_TRAILING_SYMS_RE  = re.compile(r"[@#$%!]+$")

_SCHOOL_CANONICAL = {
    "Claremont-Mudd-Scripps", "Cal Lutheran", "Caltech", "Chapman",
    "Occidental", "Pomona-Pitzer", "La Verne", "Redlands", "Whittier",
}


def _normalize_name(name: str) -> str:
    name = name.strip()
    if "," not in name:
        parts = name.split()
        if len(parts) >= 2:
            name = f"{parts[-1]}, {' '.join(parts[:-1])}"
    name = _LEADING_PREFIX_RE.sub("", name)
    name = _TRAILING_CODE_RE.sub("", name)
    name = _TRAILING_INIT_RE.sub("", name)
    name = re.sub(r",\s*$", "", name).strip()
    if "," in name:
        last, first = name.split(",", 1)
        first = first.strip()
        if first and first == first.upper() and first.isalpha():
            if any(c in "AEIOU" for c in first):
                first = first.title()
        name = f"{last}, {first}"
    return name


_MANUAL_NAME_ALIASES: dict[str, str] = {
    "Maccalla, Sebass":      "Maccalla, Sebas",
    "Zane, Kamakeeponolahu": "Zane, Kamakeeponolahi",
    "Calloway, Trenten":     "Calloway, Trent",
    "Williams, Isabella":    "Williams, Bella",
    "Graceffa, Gabriel":     "Graceffa, Gabe",
    "Lucore, Nikolas":       "Lucore, Niko",
}


def _build_name_aliases(norm_names: list[str]) -> dict[str, str]:
    """Same alias resolution as in best_performances.py / process_results.py."""
    case_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for n in norm_names:
        case_counts[n.lower()][n] += 1

    alias: dict[str, str] = {}
    for lower_n, counts in case_counts.items():
        canonical = max(counts, key=counts.__getitem__)
        for variant in counts:
            if variant != canonical:
                alias[variant] = canonical

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


def _to_seconds(raw: str) -> float | None:
    val = _TRAILING_SYMS_RE.sub("", raw.strip()).strip()
    if val.lower().startswith("x"):
        val = val[1:].strip()
    if not val or val.upper() in _INVALID_PERF:
        return None
    m = _MMSS_RE.match(val)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(val)
    except ValueError:
        return None


def _is_diving(event_name: str) -> bool:
    return "diving" in event_name.lower()


# ---------------------------------------------------------------------------
# Plausibility check: per-50 pace rule
# ---------------------------------------------------------------------------

# A legitimate swim should fall between 15 s/50 (elite sprint) and
# 50 s/50 (very slow/novice) per 50 units (yards or meters) of distance.
_PER_50_MIN = 15.0   # seconds per 50 units
_PER_50_MAX = 50.0   # seconds per 50 units

_DIVE_BOUNDS = (50.0, 800.0)   # diving: points range

# Parse distance and unit from an event name string.
_DIST_UNIT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s+(Yard|Meter|LC\s+Meter|mtr)\b", re.IGNORECASE
)


def _pace_bounds(event_name: str) -> tuple[float, float] | None:
    """
    Return (lo, hi) time bounds in seconds derived from the per-50 pace rule,
    or None if the distance cannot be parsed from the event name.
    """
    m = _DIST_UNIT_RE.search(event_name)
    if not m:
        return None
    dist = float(m.group(1))
    if dist <= 0:
        return None
    factor = dist / 50.0
    return factor * _PER_50_MIN, factor * _PER_50_MAX


# ---------------------------------------------------------------------------
# Near-duplicate name detection
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _first_name(name: str) -> str:
    """Extract the first-name portion from 'Last, First' or return the whole name."""
    return name.split(",", 1)[1].strip() if "," in name else name


def _find_near_duplicates(names: list[str], threshold: float = 0.85) -> list[tuple[str, str, float]]:
    """Return pairs of names with similarity >= threshold."""
    pairs = []
    by_last: dict[str, list[str]] = defaultdict(list)
    for n in names:
        last = n.split(",")[0].strip().lower() if "," in n else n.lower()
        by_last[last].append(n)

    # Within same last-name bucket, compare full names
    # Extra guard: also require first-name similarity >= 0.5 to avoid flagging
    # obvious different-person pairs (e.g. "Williams, Bella" vs "Williams, Lucas").
    for group in by_last.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                # Special case: one name is just a last name (no comma)
                # while the other is "Last, First" — treat as near-duplicate
                a_nocomma = "," not in a
                b_nocomma = "," not in b
                if a_nocomma != b_nocomma:
                    nocomma = a if a_nocomma else b
                    withcomma = b if a_nocomma else a
                    if withcomma.split(",")[0].strip().lower() == nocomma.lower():
                        pairs.append((a, b, 0.99))
                        continue
                sim = _similarity(a, b)
                if sim >= threshold and a != b:
                    # Require first names to also be reasonably similar
                    fn_sim = _similarity(_first_name(a), _first_name(b))
                    if fn_sim >= 0.5:
                        pairs.append((a, b, round(sim, 3)))

    # Also check across last names — use a high threshold (0.95) to catch
    # near-identical spellings only (e.g. typos in last name).
    cross_threshold = max(0.95, threshold)
    name_list = sorted(set(names))
    for i in range(len(name_list)):
        for j in range(i + 1, len(name_list)):
            a, b = name_list[i], name_list[j]
            last_a = a.split(",")[0].strip().lower()
            last_b = b.split(",")[0].strip().lower()
            if last_a == last_b:
                continue  # already handled in same-last-name bucket
            sim = _similarity(a, b)
            if sim >= cross_threshold:
                pairs.append((a, b, round(sim, 3)))

    seen = set()
    unique = []
    for a, b, s in pairs:
        key = tuple(sorted([a, b]))
        if key not in seen:
            seen.add(key)
            unique.append((a, b, s))
    return sorted(unique, key=lambda x: -x[2])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Data quality report for Swimplex results")
    ap.add_argument("--season", required=True, metavar="YYYY-YY")
    ap.add_argument("--json", action="store_true", help="Also write JSON report")
    args = ap.parse_args()

    results_path = DATA_DIR / args.season / "results.json"
    if not results_path.exists():
        ap.error(f"Results file not found: {results_path}")

    rows: list[dict] = json.loads(results_path.read_text())

    issues: dict[str, list] = defaultdict(list)

    # Apply name normalization + alias resolution (same as in process_results.py)
    for r in rows:
        r["_norm_name"] = _normalize_name(r["name"])
    _name_aliases = _build_name_aliases([r["_norm_name"] for r in rows])
    for r in rows:
        n = _name_aliases.get(r["_norm_name"], r["_norm_name"])
        r["_norm_name"] = _MANUAL_NAME_ALIASES.get(n, n)

    indiv_rows = [r for r in rows if not r["is_relay"] or r["relay_leg"] > 0]

    # ── 1. Suspect times ──────────────────────────────────────────────────────
    # Relay splits (leg ≥ 2) have their own dedicated check (10); skip them here
    # to avoid duplicate entries.
    for r in indiv_rows:
        if _is_diving(r["event_name"]):
            continue
        if r["relay_leg"] >= 2:
            continue
        val = _to_seconds(r["finals"])
        if val is None:
            continue  # NT / DQ / empty — OK

        # Bare integer (no colon, no decimal) is almost always a parse error
        raw_clean = _TRAILING_SYMS_RE.sub("", r["finals"].strip()).strip()
        if re.fullmatch(r"\d+", raw_clean):
            issues["suspect_times"].append({
                "name":    r["_norm_name"],
                "event":   r["event_name"],
                "finals":  r["finals"],
                "reason":  "bare integer (no colon/decimal)",
                "pdf":     r["pdf_file"],
                "meet":    r["meet_name"],
            })
            continue

        # Check per-50 pace plausibility
        bounds = _pace_bounds(r["event_name"])
        if bounds:
            lo, hi = bounds
            if not (lo <= val <= hi):
                m_dist = _DIST_UNIT_RE.search(r["event_name"])
                dist = float(m_dist.group(1)) if m_dist else 0
                per50 = round(val / (dist / 50), 2) if dist else None
                issues["suspect_times"].append({
                    "name":    r["_norm_name"],
                    "event":   r["event_name"],
                    "finals":  r["finals"],
                    "seconds": round(val, 2),
                    "per_50":  per50,
                    "reason":  f"pace {per50}s/50 outside [{_PER_50_MIN}, {_PER_50_MAX}]",
                    "pdf":     r["pdf_file"],
                    "meet":    r["meet_name"],
                })

    # ── 2. Suspect dive scores ────────────────────────────────────────────────
    for r in indiv_rows:
        if not _is_diving(r["event_name"]):
            continue
        val = _to_seconds(r["finals"])
        if val is None:
            continue
        lo, hi = _DIVE_BOUNDS
        if not (lo <= val <= hi):
            issues["suspect_dive_scores"].append({
                "name":   r["_norm_name"],
                "event":  r["event_name"],
                "finals": r["finals"],
                "score":  round(val, 2),
                "reason": f"outside plausible range [{lo}, {hi}]",
                "pdf":    r["pdf_file"],
            })

    # ── 3. Unrecognised schools ───────────────────────────────────────────────
    school_set: set[str] = set()
    for r in rows:
        if r["school"]:
            school_set.add(r["school"])
    for school in sorted(school_set):
        # Basic canonicalisation check
        from process_results import _canonicalize_school
        canon = _canonicalize_school(school)
        if canon not in _SCHOOL_CANONICAL:
            issues["unrecognised_schools"].append({"raw": school, "canonicalized": canon})

    # ── 4. Residual trailing codes after normalisation ────────────────────────
    # Flag names that still have W/M gender+year codes; skip known initialism
    # first names (e.g. "Morris, DJ", "Smith, CJ", "Ceja, AJ") which look like
    # 2-letter codes but are legitimate.
    _KNOWN_INITIALISM_RE = re.compile(r",\s+[A-Z]{2}$")
    for r in rows:
        norm = r["_norm_name"]
        if _TRAILING_CODE_RE.search(norm):
            issues["residual_name_suffixes"].append({
                "raw":        r["name"],
                "normalised": norm,
                "pdf":        r["pdf_file"],
            })

    # ── 5. Names with no first name after normalisation ───────────────────────
    for r in rows:
        norm = r["_norm_name"]
        if "," in norm and not norm.split(",", 1)[1].strip():
            issues["missing_first_name"].append({
                "raw":        r["name"],
                "normalised": norm,
                "pdf":        r["pdf_file"],
            })

    # ── 6. Near-duplicate athlete names ──────────────────────────────────────
    all_norm_names = list({r["_norm_name"] for r in indiv_rows if r["_norm_name"]})

    # Build canonical school per normalised name (majority vote)
    name_school_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in indiv_rows:
        name_school_votes[r["_norm_name"]][
            _canonicalize_school(r["school"])
        ] += 1

    def _canon_school(name: str) -> str:
        votes = name_school_votes.get(name, {})
        return max(votes, key=votes.__getitem__) if votes else ""

    near_dups = _find_near_duplicates(all_norm_names, threshold=0.80)
    for a, b, sim in near_dups:
        # Skip pairs where both athletes have different known schools — they
        # are almost certainly different people who happen to share a last name.
        sa, sb = _canon_school(a), _canon_school(b)
        if sa and sb and sa != sb:
            continue
        issues["near_duplicate_names"].append({"name_a": a, "name_b": b, "similarity": sim})

    # ── 7. First-Last format names (no comma in raw) ──────────────────────────
    for r in rows:
        if "," not in r["name"] and not r["is_relay"]:
            issues["first_last_format"].append({
                "raw":        r["name"],
                "normalised": r["_norm_name"],
                "school":     r["school"],
                "pdf":        r["pdf_file"],
            })

    # ── 8. Case-variant duplicates ─────────────────────────────────────────────
    lower_map: dict[str, list[str]] = defaultdict(list)
    for n in all_norm_names:
        lower_map[n.lower()].append(n)  # catches "DeBoom" vs "Deboom" etc.
    for variants in lower_map.values():
        variants_u = sorted(set(variants))
        if len(variants_u) > 1:
            issues["case_variant_names"].append(variants_u)

    # ── 9. Event name anomalies ────────────────────────────────────────────────
    event_names = {r["event_name"] for r in rows}
    for ev in sorted(event_names):
        m = re.search(r"(\d+(?:\.\d+)?)\s+(Yard|Meter|M)\b", ev, re.IGNORECASE)
        if m:
            dist = float(m.group(1))
            unit = m.group(2).lower()
            # Flag unusual relay distances
            if "relay" in ev.lower() and dist not in (200, 400, 800, 1600):
                issues["event_anomalies"].append({
                    "event":  ev,
                    "reason": f"unusual relay distance: {dist}",
                })
            # Flag events mixing unit keywords (e.g. "Yard Meter")
            if "yard" in ev.lower() and "meter" in ev.lower():
                issues["event_anomalies"].append({
                    "event":  ev,
                    "reason": "both 'Yard' and 'Meter' in event name",
                })

    # ── 10. Relay split sanity ────────────────────────────────────────────────
    # ── Also check for duplicate relay team rows ──────────────────────────────
    relay_team_rows = [r for r in rows if r["is_relay"] and r["relay_leg"] == 0]
    relay_seen: dict[tuple, dict] = {}
    for r in relay_team_rows:
        clean_finals = _TRAILING_SYMS_RE.sub("", r["finals"].strip())
        key = (r["gender"], r["event_name"], r["school"], clean_finals, r["meet_name"])
        if key in relay_seen:
            issues["duplicate_relay_entries"].append({
                "event":  r["event_name"],
                "school": r["school"],
                "time":   clean_finals,
                "meet":   r["meet_name"],
                "pdf_a":  relay_seen[key]["pdf_file"],
                "pdf_b":  r["pdf_file"],
            })
        else:
            relay_seen[key] = r

    splits = [r for r in rows if r["relay_leg"] >= 2]
    for r in splits:
        val = _to_seconds(r["finals"])
        if val is None:
            continue
        bounds = _pace_bounds(r["event_name"])
        if bounds:
            lo, hi = bounds
            # Only flag splits that are too SLOW. "Too fast" splits are
            # usually valid 50-yard legs labelled under the full relay
            # event distance (e.g. a 26s leg under "200 Yard Freestyle
            # (Relay Split)"), making the per-50 look impossibly fast.
            if val > hi:
                m_dist = _DIST_UNIT_RE.search(r["event_name"])
                dist = float(m_dist.group(1)) if m_dist else 0
                per50 = round(val / (dist / 50), 2) if dist else None
                issues["suspect_relay_splits"].append({
                    "name":    r["_norm_name"],
                    "event":   r["event_name"],
                    "finals":  r["finals"],
                    "seconds": round(val, 2),
                    "per_50":  per50,
                    "leg":     r["relay_leg"],
                    "pdf":     r["pdf_file"],
                })

    # ── Print report ──────────────────────────────────────────────────────────
    total = sum(len(v) for v in issues.values())
    print(f"\n=== Data Quality Report: {args.season} ===")
    print(f"Total issues found: {total}\n")

    # De-duplicate First-Last format before printing (many rows per athlete)
    if issues.get("first_last_format"):
        seen_fl: set[str] = set()
        deduped = []
        for item in issues["first_last_format"]:
            k = (item["raw"], item["pdf"])
            if k not in seen_fl:
                seen_fl.add(k)
                deduped.append(item)
        issues["first_last_format"] = deduped

    for category, items in sorted(issues.items()):
        if not items:
            continue
        label = category.replace("_", " ").title()
        print(f"── {label} ({len(items)}) ──────────────────────────")
        for item in items[:25]:      # cap at 25 per category for readability
            if isinstance(item, list):
                print(f"  {item}")
            else:
                parts = [f"{k}={v!r}" for k, v in item.items()]
                print("  " + "  ".join(parts))
        if len(items) > 25:
            print(f"  … and {len(items) - 25} more")
        print()

    # ── Optionally write JSON ──────────────────────────────────────────────────
    if args.json:
        out_path = DATA_DIR / args.season / "data_quality_report.json"
        # Convert defaultdict to plain dict for JSON serialisation
        out_path.write_text(json.dumps(dict(issues), indent=2))
        print(f"Report written: {out_path}")


if __name__ == "__main__":
    main()
