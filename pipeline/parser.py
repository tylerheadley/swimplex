"""
Hy-Tek meet results PDF parser for Swimplex.

Uses pdfplumber word-coordinate extraction to reliably parse columns,
since school names contain spaces and vary in length.

Column layout (x positions) observed across SCIAC Hy-Tek PDFs:
  place   : x < 46
  name    : 46 <= x < 187  (individual) / team name for relays
  age     : 187 <= x < 210 (individual) / relay letter for relays
  school  : 210 <= x < 360
  seed    : 360 <= x < 440
  finals  : 440 <= x < 525
  points  : x >= 525

Relay rows have the team name in the name+age columns, relay letter (A/B/C)
somewhere around the age-column boundary, and no school column entry.

Relay sub-rows:
  swimmers : "1) Last, First Age  2) Last, First Age  3) …  4) …"
  splits   : cumulative times with parenthesised leg-delta values
"""

import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PDF text normalization
# ---------------------------------------------------------------------------

# Some PDFs encode ligatures as CID codes.  Map the ones we encounter to the
# correct Unicode characters so event names stay consistent across PDFs.
_CID_MAP = {
    "974": "fi",   # fi ligature (full)
    "975": "fi",   # fi ligature (alternate)
    "976": "f",    # f glyph encoded as CID in this font family (e.g. "Butter(cid:976)ly" → "Butterfly")
    "977": "ff",
    "978": "ffi",
}
_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _normalize_text(text: str) -> str:
    return _CID_RE.sub(lambda m: _CID_MAP.get(m.group(1), ""), text)


def _normalize_words(words: list[dict]) -> list[dict]:
    """Normalize word dicts: fix CID ligature codes and round x0 to avoid
    floating-point boundary misses (e.g. 209.9999… < 210 fails the column check)."""
    return [dict(w, text=_normalize_text(w["text"]), x0=round(w["x0"], 1)) for w in words]


# ---------------------------------------------------------------------------
# Column x-boundaries (calibrated against SCIAC PDFs)
# ---------------------------------------------------------------------------
X_PLACE_MAX  = 46    # place  < 46
X_NAME_MAX   = 187   # name   46..187
X_AGE_MIN    = 187   # age   187..210
X_AGE_MAX    = 210   # school 210..360
X_SCHOOL_MAX = 360
X_SEED_MAX   = 440
X_FINALS_MAX = 525
# anything >= X_FINALS_MAX is points

Y_ROW_TOL = 3   # points — words within this y-distance share a row


# ---------------------------------------------------------------------------
# Stroke tables
# ---------------------------------------------------------------------------

# Stroke for each leg of a medley relay (back, breast, fly, free)
MEDLEY_LEG_STROKES = ["Backstroke", "Breaststroke", "Butterfly", "Freestyle"]


def _leg_stroke(relay_stroke: str, leg: int) -> str:
    """Return the stroke for leg `leg` (1-based) of a relay."""
    if "medley" in relay_stroke.lower():
        return MEDLEY_LEG_STROKES[leg - 1]
    return "Freestyle"


def _split_event_name(relay_stroke: str, relay_dist: int, unit: str, leg: int) -> str:
    """
    Build the event_name for an individual relay-split record.

    Leg 1 is a flat-start leadoff — treat it the same as the standalone event.
    Legs 2-4 are relay-start splits — labeled "(Relay Split)".
    """
    leg_dist = relay_dist // 4
    stroke = _leg_stroke(relay_stroke, leg)
    if leg == 1:
        return f"{leg_dist} {unit} {stroke}"
    return f"{leg_dist} {unit} {stroke} (Relay Split)"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SwimResult:
    pdf_file:       str
    event_num:      int
    event_name:     str
    gender:         str       # Men / Women / Mixed
    distance:       str       # e.g. "200"
    unit:           str       # Yard / Meter
    stroke:         str       # e.g. "Freestyle", "3 mtr Diving"
    is_relay:       bool
    relay_leg:      int       # 0 = not a relay split; 1–4 = which leg
    place:          str       # "1" … "99", "---"
    name:           str       # athlete "Last, First" or relay team name
    age:            str       # numeric age, class year (FR/SO/JR/SR), or ""
    school:         str
    relay_swimmers: str       # for relay TEAM rows: pipe-sep "Name (Age)|…"; else ""
    seed:           str       # raw seed time / score / "NT" / "NP"
    finals:         str       # finals time / score / "DQ" (exhibition 'x' prefix stripped)
    points:         str
    # Meet-level metadata — populated after all per-page parsing is done
    meet_name:      str = ""  # e.g. "2026 SCIAC SWIMMING AND DIVING CHAMPS-entries"
    meet_date:      str = ""  # e.g. "2/18/2026 to 2/21/2026" or "11/8/2025"


def result_to_dict(r: SwimResult) -> dict:
    d = asdict(r)
    # Surface meet_name and meet_date right after pdf_file for readability
    meet_name = d.pop("meet_name")
    meet_date = d.pop("meet_date")
    return {"pdf_file": d.pop("pdf_file"),
            "meet_name": meet_name,
            "meet_date": meet_date,
            **d}


# ---------------------------------------------------------------------------
# Meet-header extraction
# ---------------------------------------------------------------------------

# Matches a Hy-Tek date like "2/7/2026" or "11/18/2025"
_HDR_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def _parse_meet_header(pdf) -> tuple[str, str]:
    """
    Extract the meet name and date(s) from the Hy-Tek PDF header (first page).

    Hy-Tek titles look like:
        "2026 SCIAC SWIMMING AND DIVING CHAMPS-entries - 2/18/2026 to 2/21/2026"
        "Caltech vs. Oxy - 11/8/2025"

    Returns (meet_name, meet_date) as raw strings; both empty if not found.
    """
    page = pdf.pages[0]
    words = _normalize_words(page.extract_words(x_tolerance=3, y_tolerance=3))

    # Group words into rows by y-position
    row_map: dict[int, list] = {}
    for w in words:
        row_map.setdefault(round(w["top"]), []).append(w)

    for y in sorted(row_map):
        ws = sorted(row_map[y], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws).strip()
        tl = text.lower()

        # Skip the Hy-Tek system line and generic labels
        if "hy-tek" in tl or "meet manager" in tl:
            continue
        if tl in ("results", "results - by name"):
            continue
        # Stop as soon as we hit an event header
        if tl.startswith("event "):
            break

        m = _HDR_DATE_RE.search(text)
        if not m:
            continue

        # Everything before the first date (minus trailing " -") is the name
        name_part = re.sub(r"\s*-\s*$", "", text[: m.start()]).strip()
        date_part = text[m.start():].strip()
        return name_part, date_part

    return "", ""


# ---------------------------------------------------------------------------
# Row grouping
# ---------------------------------------------------------------------------

def _group_rows(words: list[dict]) -> list[list[dict]]:
    if not words:
        return []
    rows: list[list[dict]] = []
    current: list[dict] = [words[0]]
    cy = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - cy) <= Y_ROW_TOL:
            current.append(w)
        else:
            rows.append(sorted(current, key=lambda d: d["x0"]))
            current = [w]
            cy = w["top"]
    if current:
        rows.append(sorted(current, key=lambda d: d["x0"]))
    return rows


def _row_text(row: list[dict]) -> str:
    return " ".join(w["text"] for w in row)


def _words_in(row: list[dict], x_min: float, x_max: float) -> str:
    return " ".join(w["text"] for w in row if x_min <= w["x0"] < x_max).strip()


def _first_x(row: list[dict]) -> float:
    return row[0]["x0"] if row else 9999.0


# ---------------------------------------------------------------------------
# Event header parsing
# ---------------------------------------------------------------------------

_EVENT_RE = re.compile(
    r"^Event\s+(\d+[A-Za-z]?)\s+(Men|Women|Mixed)\s+([\d.]+(?:-\w+)?)\s+(Yard|Meter|M)\s+(.+)",
    re.IGNORECASE,
)
_EVENT_RE2 = re.compile(
    r"^Event\s+(\d+[A-Za-z]?)\s+(Men|Women|Mixed)\s+(.+)",
    re.IGNORECASE,
)
_DIST_RE = re.compile(
    r"^([\d.]+(?:-\w+)?)\s+(Yard|Meter|M)\s+(.+)", re.IGNORECASE
)


def _parse_event_header(text: str):
    """
    Returns (event_num, gender, distance, unit, stroke) or None.
    """
    m = _EVENT_RE.match(text)
    if m:
        num = int(re.match(r"\d+", m.group(1)).group())
        return num, m.group(2).capitalize(), m.group(3), m.group(4).capitalize(), m.group(5).strip()

    m = _EVENT_RE2.match(text)
    if m:
        num = int(re.match(r"\d+", m.group(1)).group())
        gender = m.group(2).capitalize()
        rest = m.group(3).strip()
        m2 = _DIST_RE.match(rest)
        if m2:
            return num, gender, m2.group(1), m2.group(2).capitalize(), m2.group(3).strip()
        return num, gender, "", "", rest
    return None


# ---------------------------------------------------------------------------
# Row classification helpers
# ---------------------------------------------------------------------------

_SKIP_FIRST = {
    "name", "team", "(event", "results", "california institute",
}
_TIME_RE = re.compile(r"^\d+[\.:]\d+")
_PLACE_RE = re.compile(r"^(\d+|---?-?)$")
_SWIMMER_NUM_RE = re.compile(r"^\d+\)$")


def _is_skip_row(row: list[dict]) -> bool:
    if not row:
        return True
    first = row[0]["text"].lower()
    rt = _row_text(row).lower()
    if "hy-tek" in rt or "meet manager" in rt:
        return True
    if first in _SKIP_FIRST:
        return True
    # Relay-member rows: "1) Name Age 2) …"  — handled separately, skip here
    if _SWIMMER_NUM_RE.match(row[0]["text"]):
        return True
    return False


def _is_swimmer_row(row: list[dict]) -> bool:
    """True if this row starts with '1)' and contains at least one more 'N)' marker."""
    texts = [w["text"] for w in row]
    return (
        bool(texts)
        and _SWIMMER_NUM_RE.match(texts[0])
        and any(_SWIMMER_NUM_RE.match(t) for t in texts[1:])
    )


def _is_split_row(row: list[dict]) -> bool:
    """True if this row looks like cumulative-split data (times, not a place number)."""
    if not row:
        return False
    first = row[0]["text"]
    return bool(_TIME_RE.match(first)) and _first_x(row) > X_PLACE_MAX


# ---------------------------------------------------------------------------
# Relay swimmer-name parsing
# ---------------------------------------------------------------------------

_CLASS_YEARS = {"FR", "SO", "JR", "SR"}


def _parse_relay_swimmers(row: list[dict]) -> list[tuple[str, str]]:
    """
    Parse "1) Last, First Age  2) Last, First Age  …" into [(name, age), …].
    Age may be a bare integer (e.g. "20") or a class year (FR/SO/JR/SR).
    """
    words = [w["text"] for w in row]
    swimmers: list[tuple[str, str]] = []
    i = 0
    while i < len(words):
        if _SWIMMER_NUM_RE.match(words[i]):
            j = i + 1
            parts: list[str] = []
            while j < len(words) and not _SWIMMER_NUM_RE.match(words[j]):
                parts.append(words[j])
                j += 1
            # Last token is numeric age or class year
            if parts and (parts[-1].isdigit() or parts[-1].upper() in _CLASS_YEARS):
                age = parts[-1]
                name = " ".join(parts[:-1])
            else:
                age = ""
                name = " ".join(parts)
            swimmers.append((name, age))
            i = j
        else:
            i += 1
    return swimmers


def _format_swimmers(swimmers: list[tuple[str, str]]) -> str:
    """Pipe-delimited 'Name (Age)|Name (Age)|…' for storage in relay_swimmers field."""
    return "|".join(f"{name} ({age})" for name, age in swimmers)


# ---------------------------------------------------------------------------
# Relay split extraction
# ---------------------------------------------------------------------------

def _splits_from_row(row: list[dict]) -> tuple[list[str], list[str]]:
    """
    Split a split row into (bare_cumulatives, parenthesised_deltas).

    Bare cumulatives are time-like tokens not wrapped in parens.
    Parenthesised deltas are tokens of the form (value).
    """
    bare: list[str] = []
    parens: list[str] = []
    for w in row:
        t = w["text"]
        if t.startswith("(") and t.endswith(")"):
            parens.append(t[1:-1])
        elif _TIME_RE.match(t):
            bare.append(t)
    return bare, parens


def _extract_leg_splits(bare: list[str], parens: list[str], relay_dist: int) -> list[str]:
    """
    Return [leg1_time, leg2_time, leg3_time, leg4_time] from the split data.

    Hy-Tek relay split layout
    -------------------------
    The very first 50-yard cumulative has NO paren (it equals the bare split).
    Every subsequent 50-yard increment shows a paren with the delta from the
    previous 50.

    stride = leg_dist // 50  (leg_dist = relay_dist // 4)

    stride == 1  (4×50 relays: 200 free, 200 medley)
        Leg 1 ends at the very first bare cumulative — there is no paren for it.
        Legs 2-4 each contribute exactly 1 paren.
        →  leg1 = bare[0];  leg2 = parens[0];  leg3 = parens[1];  leg4 = parens[2]

    stride >= 2  (4×100, 4×200 … relays)
        Leg 1's first 50 has no paren, so leg 1 contributes (stride-1) parens;
        its end time is at paren index (stride-2).
        Legs 2-4 each contribute stride parens; leg k's end is at:
            index = (stride-2) + (k-1)*stride
        →  base = stride - 2;  leg k end = parens[base + (k-1)*stride]

    Examples
    --------
    200 relay  (4×50,  stride=1): leg1=bare[0], legs2-4=parens[0..2]
    400 relay  (4×100, stride=2): base=0, parens indices 0, 2, 4, 6
    800 relay  (4×200, stride=4): base=2, parens indices 2, 6, 10, 14
    """
    if relay_dist == 0 or not (bare or parens):
        return []
    leg_dist = relay_dist // 4
    stride = max(1, leg_dist // 50)

    if stride == 1:
        # Leg 1 = first bare cumulative; legs 2-4 = parens[0], [1], [2]
        splits: list[str] = []
        if bare:
            splits.append(bare[0])
        splits.extend(parens[:3])
        return splits

    # stride >= 2: all leg-end times are in parens
    base = stride - 2
    splits = []
    for k in range(4):
        idx = base + k * stride
        if idx < len(parens):
            splits.append(parens[idx])
        else:
            break
    return splits


# ---------------------------------------------------------------------------
# Relay state finalisation
# ---------------------------------------------------------------------------

def _finalize_relay(state: dict, results: list[SwimResult]) -> None:
    """
    Called when we have finished accumulating relay split rows.
    Fills in relay_swimmers on the pending team result and appends individual
    split records to `results`.
    """
    swimmers: list[tuple[str, str]] = state.get("relay_swimmers_list", [])
    parens: list[str] = state.get("relay_split_parens", [])
    pending: SwimResult | None = state.get("pending_relay_result")

    if pending and swimmers:
        pending.relay_swimmers = _format_swimmers(swimmers)

    bare: list[str] = state.get("relay_split_bare", [])

    if pending and swimmers and (bare or parens):
        try:
            relay_dist = int(state["distance"])
        except (ValueError, KeyError):
            relay_dist = 0

        leg_splits = _extract_leg_splits(bare, parens, relay_dist)

        for i, (sw_name, sw_age) in enumerate(swimmers):
            leg = i + 1
            if i >= len(leg_splits):
                continue
            split_time = leg_splits[i]
            leg_stroke = _leg_stroke(state["stroke"], leg)
            evt_name = _split_event_name(state["stroke"], relay_dist, state["unit"], leg)

            results.append(SwimResult(
                pdf_file       = pending.pdf_file,
                event_num      = pending.event_num,
                event_name     = evt_name,
                gender         = state["gender"],
                distance       = str(relay_dist // 4),
                unit           = state["unit"],
                stroke         = leg_stroke,
                is_relay       = True,
                relay_leg      = leg,
                place          = pending.place,
                name           = sw_name,
                age            = sw_age,
                school         = pending.school,
                relay_swimmers = "",
                seed           = "",
                finals         = split_time,
                points         = "",
            ))

    # Clear relay state
    state["relay_mode"] = None
    state["pending_relay_result"] = None
    state["relay_swimmers_list"] = []
    state["relay_split_parens"] = []
    state["relay_split_bare"] = []


# ---------------------------------------------------------------------------
# Per-page parsing
# ---------------------------------------------------------------------------

def _parse_page(page, pdf_name: str, state: dict, results: list[SwimResult]) -> None:
    words = _normalize_words(page.extract_words(x_tolerance=3, y_tolerance=3))
    rows = _group_rows(words)

    for row in rows:
        if not row:
            continue

        rt = _row_text(row)

        # ── Event header ──────────────────────────────────────────────────
        if rt.strip().lower().startswith("event "):
            parsed = _parse_event_header(rt.strip())
            if parsed:
                # Finalise any open relay before switching events
                if state["relay_mode"]:
                    _finalize_relay(state, results)
                num, gender, distance, unit, stroke = parsed
                state.update(
                    event_num  = num,
                    gender     = gender,
                    distance   = distance,
                    unit       = unit,
                    stroke     = stroke,
                    event_name = f"{gender} {distance} {unit} {stroke}".strip(),
                    is_relay   = "relay" in stroke.lower(),
                )
            continue

        if state["event_num"] == 0:
            continue  # Haven't seen an event header yet

        # ── Relay swimmer-name row ─────────────────────────────────────────
        if _is_swimmer_row(row):
            if state["relay_mode"] == "awaiting_swimmers":
                state["relay_swimmers_list"] = _parse_relay_swimmers(row)
                state["relay_mode"] = "awaiting_splits"
                state["relay_split_parens"] = []
            continue

        # ── Relay split rows ───────────────────────────────────────────────
        if state["relay_mode"] == "awaiting_splits" and _is_split_row(row):
            bare, parens = _splits_from_row(row)
            state["relay_split_parens"].extend(parens)
            state["relay_split_bare"].extend(bare)
            continue

        # ── Finalise relay if we hit something that is not a split row ─────
        if state["relay_mode"] in ("awaiting_splits", "awaiting_swimmers"):
            _finalize_relay(state, results)
            # Fall through to parse the current row as a normal result

        # ── Standard skip check ────────────────────────────────────────────
        if _is_skip_row(row):
            continue

        # ── Place column ───────────────────────────────────────────────────
        place_words = [w for w in row if w["x0"] < X_PLACE_MAX]
        if not place_words:
            continue
        place_text = " ".join(w["text"] for w in place_words).strip()
        if not _PLACE_RE.match(place_text):
            continue

        is_relay = state["is_relay"]

        if is_relay:
            # Team name occupies the name+age columns; relay letter sits
            # somewhere in that range too — lump it all into `name`.
            team_words = [w for w in row if X_PLACE_MAX <= w["x0"] < X_AGE_MAX]
            name   = " ".join(w["text"] for w in team_words).strip()
            # Some dual-meet PDFs prepend a bare entry counter (e.g. "0 Caltech A").
            # Strip any leading bare integer so only the school name remains.
            name   = re.sub(r"^\d+\s+", "", name)
            age    = ""
            school = name  # school == team for relay results
        else:
            name_words   = [w for w in row if X_PLACE_MAX <= w["x0"] < X_NAME_MAX]
            age_words    = [w for w in row if X_AGE_MIN   <= w["x0"] < X_AGE_MAX]
            school_words = [w for w in row if X_AGE_MAX   <= w["x0"] < X_SCHOOL_MAX]
            name   = " ".join(w["text"] for w in name_words).strip()
            age    = " ".join(w["text"] for w in age_words).strip()
            school = " ".join(w["text"] for w in school_words).strip()
            # Some PDFs prepend an athlete ID number to the name (e.g. "24 Headley, Tyler")
            name   = re.sub(r"^\d+\s+", "", name)
            # Some PDFs prepend a gender letter and/or grad year to the school (e.g. "W 18 CMS-CA")
            school = re.sub(r"^[WM]\s+\d+\s+", "", school)
            school = re.sub(r"^\d+\s+", "", school)

        seed   = _words_in(row, X_SCHOOL_MAX, X_SEED_MAX)
        finals = _words_in(row, X_SEED_MAX,   X_FINALS_MAX)
        points = _words_in(row, X_FINALS_MAX, 9999)

        # Some PDFs (e.g. SCIAC Championships) have a narrower seed column that
        # starts before X_SCHOOL_MAX, causing the seed time to land in `school`.
        # Detect a trailing time token in school and shift it to seed.
        if not is_relay and school:
            m_trail = re.search(r"\s+(\d[\d:\.]+)$", school)
            if m_trail:
                trailing = m_trail.group(1)
                school = school[: m_trail.start()].strip()
                if not seed:
                    seed = trailing

        # Fallback when columnar alignment differs slightly.
        # If a time landed just left of the finals boundary (e.g. x0=438 < 440)
        # it ends up in the seed slot while finals is empty.  In that case the
        # seed IS the finals — promote it rather than triggering the word-list
        # fallback (which would pick up the points value as "finals").
        if not finals:
            if seed:
                finals, seed = seed, ""
            else:
                remaining = [w["text"] for w in row if w["x0"] >= X_SCHOOL_MAX]
                if len(remaining) >= 2:
                    seed, finals = remaining[0], remaining[1]
                    points = remaining[2] if len(remaining) > 2 else ""
                elif remaining:
                    finals = remaining[0]

        # Strip exhibition prefix ('x' or 'X') so times are treated numerically
        seed   = re.sub(r"^[xX]\s*", "", seed)
        finals = re.sub(r"^[xX]\s*", "", finals)

        if not name or not finals:
            continue

        result = SwimResult(
            pdf_file       = pdf_name,
            event_num      = state["event_num"],
            event_name     = state["event_name"],
            gender         = state["gender"],
            distance       = state["distance"],
            unit           = state["unit"],
            stroke         = state["stroke"],
            is_relay       = is_relay,
            relay_leg      = 0,
            place          = place_text,
            name           = name,
            age            = age,
            school         = school,
            relay_swimmers = "",   # filled in after swimmer-name row
            seed           = seed,
            finals         = finals,
            points         = points,
        )
        results.append(result)

        # Enter relay mode so the next rows are parsed for swimmers/splits
        if is_relay:
            state["relay_mode"]           = "awaiting_swimmers"
            state["pending_relay_result"] = result
            state["relay_swimmers_list"]  = []
            state["relay_split_parens"]   = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _fresh_state() -> dict:
    return dict(
        event_num            = 0,
        gender               = "",
        distance             = "",
        unit                 = "",
        stroke               = "",
        event_name           = "",
        is_relay             = False,
        relay_mode           = None,      # None | "awaiting_swimmers" | "awaiting_splits"
        pending_relay_result = None,
        relay_swimmers_list  = [],
        relay_split_parens   = [],
        relay_split_bare     = [],
    )


def parse_pdf(pdf_path: Path) -> list[SwimResult]:
    """Parse a single Hy-Tek results PDF and return SwimResult records."""
    logger.info("Parsing: %s", pdf_path.name)
    results: list[SwimResult] = []
    state = _fresh_state()
    try:
        with pdfplumber.open(pdf_path) as pdf:
            meet_name, meet_date = _parse_meet_header(pdf)
            for page in pdf.pages:
                _parse_page(page, pdf_path.name, state, results)
        # Finalise any relay still open at end of last page
        if state["relay_mode"]:
            _finalize_relay(state, results)
    except Exception as exc:
        logger.error("Could not parse %s: %s", pdf_path, exc)
        return []
    # Stamp every result with the meet name and date
    for r in results:
        r.meet_name = meet_name
        r.meet_date = meet_date
    logger.info("  Extracted %d results from %s", len(results), pdf_path.name)
    return results


def parse_all_pdfs(pdf_dir: Path | None = None) -> list[SwimResult]:
    """Parse every PDF in pdf_dir and return all results."""
    if pdf_dir is None:
        pdf_dir = Path(__file__).parent.parent / "data" / "pdfs"
    all_results: list[SwimResult] = []
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("No PDFs found in %s", pdf_dir)
        return []
    for pdf_path in pdfs:
        all_results.extend(parse_pdf(pdf_path))
    logger.info("Total results parsed: %d", len(all_results))
    return all_results
