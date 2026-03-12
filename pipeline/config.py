"""
SCIAC swimming and diving conference configuration.
Each team entry maps to its schedule/results pages for both men's and women's programs.
"""

from datetime import date

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
