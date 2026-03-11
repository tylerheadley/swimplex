"""
Scraper module for Swimplex.

Visits each SCIAC team's schedule page(s), finds links to Hy-Tek result PDFs,
and downloads any that fall within the configured season date range.

Sidearm Sports (the platform used by all SCIAC schools) renders schedule items
as server-side HTML, so plain requests + BeautifulSoup is sufficient. Each meet
result typically contains an <a> tag pointing to a .pdf file.
"""

import logging
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_HEADERS, REQUEST_TIMEOUT, SEASON_END, SEASON_START, TEAMS

logger = logging.getLogger(__name__)

# Delay between requests to be a polite scraper
REQUEST_DELAY = 1.5  # seconds


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(REQUEST_HEADERS)
    return s


def _is_pdf_link(href: str) -> bool:
    return href.lower().endswith(".pdf")


def _parse_meet_date(text: str) -> date | None:
    """
    Try to extract a date from a schedule row's text.
    Sidearm Sports typically renders dates as 'Month DD, YYYY' or 'MM/DD/YYYY'.
    Returns None if no date can be parsed.
    """
    # e.g. "January 18, 2026"
    m = re.search(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if m:
        try:
            return date.fromisoformat(
                f"{m.group(3)}-{_month_num(m.group(1)):02d}-{int(m.group(2)):02d}"
            )
        except ValueError:
            pass

    # e.g. "01/18/2026"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    return None


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_num(name: str) -> int:
    return _MONTHS.get(name.lower(), 0)


def _safe_filename(url: str, team_abbrev: str) -> str:
    """
    Derive a local filename from the PDF URL and team abbreviation.
    Keeps the original filename but prefixes with the team abbreviation.
    """
    parsed = urlparse(url)
    base = Path(parsed.path).name  # e.g. "results_20260118.pdf"
    return f"{team_abbrev}_{base}"


def _resolve_sidearm_pdf_url(html: str, page_url: str) -> str | None:
    """
    Sidearm Sports wraps PDFs in an HTML viewer page. The real file lives on
    CloudFront at:  <s3_bucket_path> + <path portion of og:url>
    e.g. s3_bucket_path = 'https://dbukjj6eu5tsf.cloudfront.net/gocaltech.com'
         og:url         = 'https://gocaltech.com/documents/.../file.pdf'
    → direct URL       = 'https://dbukjj6eu5tsf.cloudfront.net/gocaltech.com/documents/.../file.pdf'
    """
    m_bucket = re.search(r"s3_bucket_path\s*=\s*'([^']+)'", html)
    m_ogurl  = re.search(r'og:url[^>]*content="([^"]+)"', html)
    if not (m_bucket and m_ogurl):
        return None
    path = urlparse(m_ogurl.group(1)).path  # e.g. /documents/2025/10/27/file.pdf
    return m_bucket.group(1).rstrip("/") + path


def _download_pdf(session: requests.Session, url: str, dest: Path) -> bool:
    """
    Download a single PDF. Returns True on success.
    Handles Sidearm Sports HTML wrapper pages transparently by resolving the
    real CloudFront URL when an HTML response is received.
    """
    if dest.exists():
        logger.info("  Already downloaded: %s", dest.name)
        return True
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        # If Sidearm served an HTML wrapper instead of the actual PDF, resolve it
        if "html" in content_type or resp.content[:4] != b"%PDF":
            direct_url = _resolve_sidearm_pdf_url(resp.text, url)
            if not direct_url:
                logger.warning("  Could not resolve PDF URL from wrapper for %s", url)
                return False
            logger.debug("  Resolved to CDN URL: %s", direct_url)
            time.sleep(REQUEST_DELAY)
            resp = session.get(direct_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            if resp.content[:4] != b"%PDF":
                logger.warning("  CDN response is not a PDF for %s", direct_url)
                return False

        dest.write_bytes(resp.content)
        logger.info("  Saved: %s (%d KB)", dest.name, len(resp.content) // 1024)
        return True
    except requests.RequestException as exc:
        logger.error("  Failed to download %s: %s", url, exc)
        return False


def _scrape_schedule_page(
    session: requests.Session,
    schedule_url: str,
    base_url: str,
    team_abbrev: str,
    start: date,
    end: date,
    pdf_dir: Path,
) -> list[Path]:
    """
    Fetch a single schedule page and return paths to all PDFs downloaded.
    """
    logger.info("Scraping: %s", schedule_url)
    try:
        resp = session.get(schedule_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Could not fetch schedule page %s: %s", schedule_url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    downloaded: list[Path] = []

    # Sidearm Sports wraps each event in an <li class="sidearm-schedule-game ..."> or
    # a <tr> in a table. We look for all <a> tags that link to PDFs anywhere on the page.
    # Additionally, we try to respect the date range by checking nearby text for a date.
    for anchor in soup.find_all("a", href=True):
        href: str = anchor["href"]
        if not _is_pdf_link(href):
            continue

        full_url = urljoin(base_url, href)

        # Try to find a date near this link to filter by season
        # Walk up the DOM looking for date text
        meet_date = None
        for parent in anchor.parents:
            text = parent.get_text(" ", strip=True)
            meet_date = _parse_meet_date(text)
            if meet_date:
                break

        if meet_date and not (start <= meet_date <= end):
            logger.debug("  Skipping out-of-range meet (%s): %s", meet_date, full_url)
            continue

        filename = _safe_filename(full_url, team_abbrev)
        dest = pdf_dir / filename
        time.sleep(REQUEST_DELAY)
        if _download_pdf(session, full_url, dest):
            downloaded.append(dest)

    return downloaded


_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")


def _substitute_season(url: str, season: str) -> str:
    """
    Replace the season segment (e.g. '2025-26') in a Sidearm Sports schedule URL.
    The season is always the last path component.
    """
    # Replace the trailing season segment, e.g. /schedule/2025-26 → /schedule/2024-25
    return re.sub(r"\d{4}-\d{2}$", season, url)


def scrape_all_teams(
    start: date = SEASON_START,
    end: date = SEASON_END,
    season: str | None = None,
    pdf_dir: Path | None = None,
) -> list[Path]:
    """
    Scrape every SCIAC team's schedule pages and download all in-season result PDFs.
    Returns a list of paths to the downloaded PDFs.

    Parameters
    ----------
    start, end : date
        Season date range used to filter meets.
    season : str, optional
        Season string in 'YYYY-YY' format (e.g. '2025-26'). When provided, the
        season segment in each team's schedule URL is replaced with this value,
        allowing historical seasons to be scraped without editing config.py.
    pdf_dir : Path, optional
        Directory to save downloaded PDFs. Defaults to data/<season>/ if season
        is provided, otherwise data/pdfs/.
    """
    if pdf_dir is None:
        base = Path(__file__).parent / "data"
        pdf_dir = (base / season / "pdfs") if season else (base / "pdfs")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    session = _session()
    all_pdfs: list[Path] = []

    for team in TEAMS:
        logger.info("=== %s ===", team["name"])
        for url in team["schedule_urls"]:
            if season and _SEASON_RE.match(season):
                url = _substitute_season(url, season)
            pdfs = _scrape_schedule_page(
                session,
                url,
                team["base_url"],
                team["abbrev"],
                start,
                end,
                pdf_dir,
            )
            all_pdfs.extend(pdfs)
            time.sleep(REQUEST_DELAY)

    logger.info("Total PDFs downloaded: %d", len(all_pdfs))
    return all_pdfs
