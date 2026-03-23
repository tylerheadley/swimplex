"""
SCIAC swimming and diving conference configuration.
Each team entry maps to its schedule/results pages for both men's and women's programs.
"""

import re
from datetime import date

# ---------------------------------------------------------------------------
# Events relevant for coaching decisions
# ---------------------------------------------------------------------------

# Individual events (exact names as they appear after normalisation)
_RELEVANT_INDIV: frozenset[str] = frozenset({
    "50 Yard Freestyle", "100 Yard Freestyle", "200 Yard Freestyle",
    "500 Yard Freestyle", "1000 Yard Freestyle", "1650 Yard Freestyle",
    "100 Yard Butterfly", "200 Yard Butterfly",
    "50 Yard Backstroke", "100 Yard Backstroke", "200 Yard Backstroke",
    "100 Yard Breaststroke", "200 Yard Breaststroke",
    "200 Yard IM", "400 Yard IM",
    "1 mtr Diving", "3 mtr Diving",
})

# Base event names for relay splits (gender prefix and "(Relay Split)" stripped)
_RELEVANT_RELAY_SPLIT_BASES: frozenset[str] = frozenset({
    "50 Yard Freestyle", "100 Yard Freestyle", "200 Yard Freestyle",
    "50 Yard Butterfly", "100 Yard Butterfly",
    "50 Yard Backstroke", "100 Yard Backstroke",
    "50 Yard Breaststroke", "100 Yard Breaststroke",
})

_GENDER_PREFIX_RE = re.compile(r"^(Men|Women|Mixed)\s+", re.IGNORECASE)


def is_relevant_event(event_name: str) -> bool:
    """Return True if the event is in the coaching-relevant whitelist.

    Works for both gender-prefixed names (results.json: 'Men 50 Yard Freestyle')
    and unprefixed names (athlete_profiles / best_performances: '50 Yard Freestyle').
    """
    bare = _GENDER_PREFIX_RE.sub("", event_name).strip()
    if bare in _RELEVANT_INDIV:
        return True
    if "(Relay Split)" in bare:
        base = bare.replace(" (Relay Split)", "").strip()
        return base in _RELEVANT_RELAY_SPLIT_BASES
    return False

# Current season date range (update each year)
SEASON_START = date(2025, 9, 1)
SEASON_END   = date(2026, 4, 30)

# All 9 SCIAC schools with swim & dive programs.
# schedule_urls: pages that list meet results (with links to Hy-Tek PDF exports).
# Some schools share a combined page; others split by gender.
TEAMS: list[dict] = [
    {
        "name": "Caltech",
        "abbrev": "CALT",
        "base_url": "https://gocaltech.com",
        "schedule_urls": [
            "https://gocaltech.com/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://gocaltech.com/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Cal Lutheran",
        "abbrev": "CLU",
        "base_url": "https://clusports.com",
        "schedule_urls": [
            "https://clusports.com/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://clusports.com/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Chapman",
        "abbrev": "CHAP",
        "base_url": "https://athletics.chapman.edu",
        "schedule_urls": [
            "https://athletics.chapman.edu/sports/swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Claremont-Mudd-Scripps",
        "abbrev": "CMS",
        "base_url": "https://cmsathletics.org",
        "schedule_urls": [
            "https://cmsathletics.org/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://cmsathletics.org/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Occidental",
        "abbrev": "OXY",
        "base_url": "https://oxyathletics.com",
        "schedule_urls": [
            "https://oxyathletics.com/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://oxyathletics.com/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Pomona-Pitzer",
        "abbrev": "PP",
        "base_url": "https://sagehens.com",
        "schedule_urls": [
            "https://sagehens.com/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://sagehens.com/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "La Verne",
        "abbrev": "LAV",
        "base_url": "https://leopardathletics.com",
        "schedule_urls": [
            "https://leopardathletics.com/sports/swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Redlands",
        "abbrev": "RED",
        "base_url": "https://goredlands.com",
        "schedule_urls": [
            "https://goredlands.com/sports/swimming-and-diving/schedule/2025-26",
        ],
    },
    {
        "name": "Whittier",
        "abbrev": "WHIT",
        "base_url": "https://wcpoets.com",
        "schedule_urls": [
            "https://wcpoets.com/sports/mens-swimming-and-diving/schedule/2025-26",
            "https://wcpoets.com/sports/womens-swimming-and-diving/schedule/2025-26",
        ],
    },
]

# Lowercase substrings used to identify SCIAC schools in Hy-Tek PDF output.
# Any school whose name contains at least one of these (case-insensitive) is kept.
SCIAC_SCHOOL_SUBSTRINGS: list[str] = [
    "caltech",
    "california inst",      # "California Institute of Technology"
    "cal lutheran",
    "california lutheran",
    "chapman",
    "claremont",
    "cms",
    "occidental",
    "pomona",
    "pitzer",
    "la verne",
    "redlands",
    "whittier",
]


def is_sciac_school(school: str) -> bool:
    """Return True if *school* matches any known SCIAC institution."""
    s = school.lower()
    return any(sub in s for sub in SCIAC_SCHOOL_SUBSTRINGS)


# HTTP request headers — mimic a normal browser to avoid simple bot blocks
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 20  # seconds
