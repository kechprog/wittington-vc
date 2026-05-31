from __future__ import annotations

import re
from typing import List

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

_MANIFEST_ATTENDEES_URL = "https://manife.st/who-attends/"
_START_MARKER = "Companies Who Attend Include:"
_END_MARKERS = ("\nVENUE\n", "\nCONTACT\n", "\nOur cookies\n")
_SECTION_HEADER_PATTERN = re.compile(r"^[A-Z'&]+(?:-[A-Z]+)?$")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def scrape_attendees() -> List[str]:
    """Scrape Manifest attendee company names.

    Returns:
        A deduplicated list of attendee company names in page order.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(_MANIFEST_ATTENDEES_URL, wait_until="networkidle", timeout=60_000)
            body_text = page.locator("body").inner_text(timeout=15_000)
        except PlaywrightTimeoutError:
            page.goto(
                _MANIFEST_ATTENDEES_URL, wait_until="domcontentloaded", timeout=60_000
            )
            body_text = page.locator("body").inner_text(timeout=15_000)
        finally:
            browser.close()

    attendee_block = _extract_attendee_block(body_text)
    return _parse_company_names(attendee_block)


def _extract_attendee_block(page_text: str) -> str:
    try:
        start_index = page_text.index(_START_MARKER) + len(_START_MARKER)
    except ValueError as error:
        raise RuntimeError(
            "Could not find Manifest attendee list start marker."
        ) from error

    end_indices = [
        marker_index
        for marker in _END_MARKERS
        if (marker_index := page_text.find(marker, start_index)) != -1
    ]
    end_index = min(end_indices, default=len(page_text))

    return page_text[start_index:end_index]


def _parse_company_names(attendee_block: str) -> List[str]:
    attendees: list[str] = []
    seen: set[str] = set()

    for line in attendee_block.splitlines():
        company_name = _normalize_company_name(line)
        if not company_name or _is_section_header(company_name):
            continue

        dedupe_key = company_name.casefold()
        if dedupe_key in seen:
            continue

        attendees.append(company_name)
        seen.add(dedupe_key)

    return attendees


def _normalize_company_name(value: str) -> str:
    return _WHITESPACE_PATTERN.sub(" ", value).strip()


def _is_section_header(value: str) -> bool:
    return bool(_SECTION_HEADER_PATTERN.fullmatch(value))
