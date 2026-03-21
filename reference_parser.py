"""
reference_parser.py  —  Production-Grade Edition
Batch-parse bibliographic references via the trained field-extraction
model with post-processing.

Input  : test.json  — JSON array of {text, style, source}
Output : parsed_references.json

Post-processing fixes applied after raw field extraction:
  Fix 1  MLA/Harvard "Accessed Date" bug
  Fix 2  IEEE Patent number splitting
  Fix 3  Inverted author name correction
  Fix 4  Video timestamp hallucinations (YouTube / TED)
  Fix 5  Corporate author vs. publisher fallback
  Fix 6  Vancouver / web missing title fallback from URL

Usage:
  python reference_parser.py
  python reference_parser.py --workers 16 --timeout 15
  python reference_parser.py --limit 100 --dry-run
  python reference_parser.py --verbose

Install:
  pip install requests tqdm lxml
"""

from __future__ import annotations

# ══════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════
INPUT_FILE      = "test.json"
OUTPUT_FILE     = "parsed_references.json"
PARSER_ENDPOINT  = "http://localhost:8070/api/processCitation"
NUM_WORKERS     = 4
REQUEST_TIMEOUT = 25
MAX_RETRIES     = 5
RETRY_DELAY     = 1.5
# ══════════════════════════════════════════════════════════════════════

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from tqdm import tqdm

try:
    from lxml import etree
except ImportError:
    sys.exit("[ERROR] lxml not installed.\nRun: pip install lxml")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 1.  PARSED RESULT SCHEMA
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ParsedReference:
    """
    All structured fields extracted from one reference entry
    after field extraction and post-processing by clean_metadata().

    New fields vs. original:
      patent_number — populated by Fix 2 when citation is a patent
      fixes_applied — list of fix IDs that fired on this record
    """
    title:           Optional[str] = None
    authors:         List[str]     = field(default_factory=list)
    container_title: Optional[str] = None
    pub_date:        Optional[str] = None
    volume:          Optional[str] = None
    issue:           Optional[str] = None
    pages:           Optional[str] = None
    doi:             Optional[str] = None
    url:             Optional[str] = None
    publisher:       Optional[str] = None
    patent_number:   Optional[str] = None   # Fix 2
    raw_text:        Optional[str] = None
    parser_status:   str           = "ok"
    fixes_applied:   List[str]     = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":           self.title,
            "authors":         self.authors,
            "container_title": self.container_title,
            "pub_date":        self.pub_date,
            "volume":          self.volume,
            "issue":           self.issue,
            "pages":           self.pages,
            "doi":             self.doi,
            "url":             self.url,
            "publisher":       self.publisher,
            "patent_number":   self.patent_number,
            "raw_text":        self.raw_text,
            "parser_status":   self.parser_status,
            "fixes_applied":   self.fixes_applied,
        }


# ──────────────────────────────────────────────────────────────────────
# 2.  HTTP CALL  (with retry)
# ──────────────────────────────────────────────────────────────────────

def call_parser(
    session:  requests.Session,
    text:     str,
    url:      str   = PARSER_ENDPOINT,
    timeout:  int   = REQUEST_TIMEOUT,
    retries:  int   = MAX_RETRIES,
    delay:    float = RETRY_DELAY,
) -> Optional[bytes]:
    """
    POST one citation string to the extraction model endpoint.
    Returns raw XML bytes on success, None on any failure after retries.
    consolidateCitations=0 skips CrossRef/PubMed lookups for speed.
    """
    payload = {
        "citations":            text,
        "consolidateCitations": "0",
    }
    retryable_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, retries + 1):
        try:
            resp = session.post(url, data=payload, timeout=timeout)
            if resp.status_code == 200:
                body = resp.content.strip()
                return body if body else None

            if resp.status_code in retryable_statuses:
                if attempt < retries:
                    wait = delay * (2 ** (attempt - 1))
                    time.sleep(wait)
                continue

            log.debug("HTTP %d for: %.60s", resp.status_code, text)
            return None
        except requests.exceptions.ConnectionError as exc:
            log.debug("Connection error attempt %d/%d: %s", attempt, retries, exc)
            if attempt < retries:
                wait = delay * (2 ** (attempt - 1))
                time.sleep(wait)
        except requests.exceptions.Timeout:
            log.debug("Timeout attempt %d/%d", attempt, retries)
            if attempt < retries:
                wait = delay * (2 ** (attempt - 1))
                time.sleep(wait)
    return None


# ──────────────────────────────────────────────────────────────────────
# 3.  XML NAMESPACE STRIPPER
# ──────────────────────────────────────────────────────────────────────

_NS_RE = re.compile(r"\{[^}]+\}")


def strip_namespaces(xml_bytes: bytes) -> Optional[etree._Element]:
    """
    Parse the TEI-XML response and strip Clark-notation namespace prefixes
    from every tag and attribute so XPath works with plain tag names.
    Returns root element or None on parse failure.
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        log.debug("XML parse error: %s", exc)
        return None
    for elem in root.iter():
        if isinstance(elem.tag, str):
            elem.tag = _NS_RE.sub("", elem.tag)
        clean = {_NS_RE.sub("", k): v for k, v in elem.attrib.items()}
        elem.attrib.clear()
        elem.attrib.update(clean)
    return root


# ──────────────────────────────────────────────────────────────────────
# 4.  XML FIELD EXTRACTORS
# ──────────────────────────────────────────────────────────────────────

def _text(element: Optional[etree._Element]) -> Optional[str]:
    """Recursively collect and strip all inner text of an element."""
    if element is None:
        return None
    parts = []
    if element.text:
        parts.append(element.text.strip())
    for child in element:
        t = _text(child)
        if t:
            parts.append(t)
        if child.tail:
            parts.append(child.tail.strip())
    result = " ".join(p for p in parts if p)
    return result if result else None


def extract_title(root: etree._Element) -> Optional[str]:
    """
    Title priority:
      1. <analytic><title level="a">   (article title)
      2. <analytic><title>             (any analytic title)
      3. <monogr><title level="m">     (monograph title)
      4. <monogr><title>               (any monograph title)
    """
    analytic = root.find(".//analytic")
    if analytic is not None:
        for t in analytic.findall("title"):
            if t.get("level") == "a":
                v = _text(t)
                if v:
                    return v
        v = _text(analytic.find("title"))
        if v:
            return v

    monogr = root.find(".//monogr")
    if monogr is not None:
        for t in monogr.findall("title"):
            if t.get("level") == "m":
                v = _text(t)
                if v:
                    return v
        return _text(monogr.find("title"))

    return None


def extract_container_title(root: etree._Element) -> Optional[str]:
    """
    Journal / container title from <monogr>.
    Prefers level="j" (journal) then level="s" (series).
    Only falls back to bare <monogr><title> when <analytic> also exists,
    meaning it is truly a container and not the main work title.
    """
    monogr = root.find(".//monogr")
    if monogr is None:
        return None
    for level in ("j", "s"):
        for t in monogr.findall("title"):
            if t.get("level") == level:
                v = _text(t)
                if v:
                    return v
    if root.find(".//analytic") is not None:
        return _text(monogr.find("title"))
    return None


def extract_authors(root: etree._Element) -> List[str]:
    """
    Build "Forename Surname" strings from <author><persName>.
    Falls back to raw <author> inner text when persName is absent.
    Note: Inverted author name correction is applied later in clean_metadata().
    """
    authors: List[str] = []
    for author_elem in root.findall(".//author"):
        persname = author_elem.find(".//persName")
        if persname is not None:
            forenames = [_text(f) for f in persname.findall("forename") if _text(f)]
            surname   = _text(persname.find("surname"))
            parts     = forenames + ([surname] if surname else [])
            name      = " ".join(parts).strip()
            if name:
                authors.append(name)
        else:
            name = _text(author_elem)
            if name:
                authors.append(name)
    return authors


def extract_pub_date(root: etree._Element) -> Optional[str]:
    """
    Extract 4-digit year from <date type="published" when="YYYY...">.
    Falls back to inner text or any <date> element.
    """
    for date_elem in root.findall(".//date"):
        if date_elem.get("type") == "published":
            when = date_elem.get("when", "")
            if when:
                m = re.match(r"(\d{4})", when)
                if m:
                    return m.group(1)
            v = _text(date_elem)
            if v:
                return v
    date_elem = root.find(".//date")
    if date_elem is not None:
        when = date_elem.get("when", "")
        if when:
            m = re.match(r"(\d{4})", when)
            if m:
                return m.group(1)
        return _text(date_elem)
    return None


def extract_biblscope(root: etree._Element, unit: str) -> Optional[str]:
    """
    Extract <biblScope unit="volume|issue|page">.
    Builds "from–to" strings for page ranges using from/to attributes.
    """
    for elem in root.findall(".//biblScope"):
        if elem.get("unit", "").lower() == unit:
            if unit == "page":
                from_p = elem.get("from", "")
                to_p   = elem.get("to",   "")
                if from_p and to_p and from_p != to_p:
                    return f"{from_p}\u2013{to_p}"
                if from_p:
                    return from_p
            v = _text(elem)
            if v:
                return v
    return None


def extract_doi(root: etree._Element) -> Optional[str]:
    """
    DOI lookup:
      1. <idno type="DOI"> (case-insensitive)
      2. <ptr target="..."> containing doi.org
    """
    for idno in root.findall(".//idno"):
        if idno.get("type", "").lower() == "doi":
            v = _text(idno)
            if v:
                return v.strip()
    for ptr in root.findall(".//ptr"):
        target = ptr.get("target", "")
        if "doi.org" in target.lower():
            m = re.search(r"doi\.org/(.+)$", target, re.IGNORECASE)
            return m.group(1).strip() if m else target.strip()
    return None


def extract_url(root: etree._Element) -> Optional[str]:
    """
    URL lookup:
      1. <ptr target="..."> that is not a DOI URL
      2. <idno type="url">
    """
    for ptr in root.findall(".//ptr"):
        target = ptr.get("target", "")
        if target and "doi.org" not in target.lower():
            return target.strip()
    for idno in root.findall(".//idno"):
        if idno.get("type", "").lower() == "url":
            v = _text(idno)
            if v:
                return v.strip()
    return None


def extract_publisher(root: etree._Element) -> Optional[str]:
    """<publisher> inside <monogr><imprint>."""
    return _text(root.find(".//publisher"))


# ──────────────────────────────────────────────────────────────────────
# 5.  POST-PROCESSING — clean_metadata()
#
#     Six targeted fixes applied after raw XML extraction.
#     Each fix is isolated in its own helper function so they can be
#     tested, toggled, or extended independently.
# ──────────────────────────────────────────────────────────────────────

# ── Compiled regex patterns (module-level for performance) ────────────

# Fix 1: keywords that signal an access/retrieval date immediately follows
_ACCESSED_RE = re.compile(
    r"\b(accessed|cited|retrieved|available)\b",
    re.IGNORECASE,
)
# Fix 1: a number that appears right after an access keyword and
#         a month name — matches "Accessed 12 May" → captures "12"
_ACCESSED_DAY_RE = re.compile(
    r"\b(?:accessed|cited|retrieved|available)\s+(\d{1,2})\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)",
    re.IGNORECASE,
)
# Fix 1: year that follows an access keyword
_ACCESSED_YEAR_RE = re.compile(
    r"\b(?:accessed|cited|retrieved|available)\s+\d{1,2}\s+\w+\s+(\d{4})\b",
    re.IGNORECASE,
)

# Fix 2: patent detection
_PATENT_RE = re.compile(r"\bpatent\b", re.IGNORECASE)

# Fix 3: Inverted author name correction
# Matches "Surname, Forename" patterns where the comma signals inversion
_COMMA_NAME_RE = re.compile(r"^([A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+)*),\s+(.+)$")

# Fix 4: video source keywords
_VIDEO_SOURCE_RE = re.compile(
    r"\b(youtube|ted\.com|vimeo|video)\b",
    re.IGNORECASE,
)
# Fix 4: timestamp pattern  HH:MM or M:SS
_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# Fix 5: organisation keywords that suggest a corporate author
_ORG_KEYWORDS_RE = re.compile(
    r"\b(association|organization|organisation|department|dept|"
    r"ministry|institute|bureau|committee|commission|agency|"
    r"council|society|foundation|centre|center|"
    r"bbc|who|cdc|nhs|un\b|unicef|"
    r"news|press|media|publishing|publishers)\b",
    re.IGNORECASE,
)

# Fix 6: URL path component cleaner — strips file extension and symbols
_URL_SLUG_RE = re.compile(r"[-_/]")


# ── Individual fix helpers ────────────────────────────────────────────

def _fix1_accessed_date(ref: ParsedReference) -> bool:
    """
    MLA / Harvard "Accessed Date" bug.

    The field extractor frequently mistakes "Accessed 12 May 2024" for:
      volume = "12"    (the day)
      pages  = "2024"  (the access year)

    Strategy:
      1. Check raw_text for access-date keyword patterns.
      2. Extract the day number and year that follow those keywords.
      3. If volume matches the day, discard it.
      4. If pages matches the access year, discard it.

    Returns True if any field was modified.
    """
    raw = ref.raw_text or ""
    modified = False

    # Only act if the text contains an access-date keyword
    if not _ACCESSED_RE.search(raw):
        return False

    # Extract day number that follows "Accessed NN Month"
    day_match = _ACCESSED_DAY_RE.search(raw)
    if day_match and ref.volume is not None:
        day_str = day_match.group(1)
        # Compare numerically (field extractor may strip leading zero)
        if ref.volume.strip().lstrip("0") == day_str.lstrip("0"):
            log.debug("Fix1: discarding volume=%r (accessed day)", ref.volume)
            ref.volume = None
            modified = True

    # Extract year that follows "Accessed NN Month YYYY"
    year_match = _ACCESSED_YEAR_RE.search(raw)
    if year_match and ref.pages is not None:
        year_str = year_match.group(1)
        # Pages value may be just the year, or a range containing it
        if ref.pages.strip() == year_str:
            log.debug("Fix1: discarding pages=%r (accessed year)", ref.pages)
            ref.pages = None
            modified = True

    return modified


def _fix2_patent_number(ref: ParsedReference) -> bool:
    """
    IEEE Patent number splitting.

    The field extractor may split "U.S. Patent 3 624 125" into:
      container_title = "U.S. Patent 3"
      volume          = "624"
      pages           = "125"

    Strategy:
      If the word "Patent" appears in container_title or raw_text:
        - Concatenate container_title + volume + pages into patent_number.
        - Clear volume, issue, pages (they are part of the patent ID).
        - Promote patent_number into title if title is still empty.

    Returns True if any field was modified.
    """
    raw       = ref.raw_text or ""
    ct        = ref.container_title or ""
    is_patent = bool(_PATENT_RE.search(ct) or _PATENT_RE.search(raw))
    if not is_patent:
        return False

    parts = [p for p in [ct, ref.volume, ref.pages] if p]
    patent_number = " ".join(parts).strip() if parts else None

    if patent_number:
        ref.patent_number   = patent_number
        ref.container_title = None
        ref.volume          = None
        ref.issue           = None
        ref.pages           = None
        # If title is still empty, use the reconstructed patent number
        if not ref.title:
            ref.title = patent_number
        log.debug("Fix2: patent_number=%r", ref.patent_number)
        return True

    return False


def _fix3_author_inversion(ref: ParsedReference) -> bool:
    """
    Inverted author name correction.

    Some styles write the first author as "Smith, John" but subsequent
    authors as "David Jones". The field extractor sometimes returns ["Smith", "John",
    "David Jones"] instead of ["Smith John", "David Jones"].

    Strategy:
      For each author string containing a comma, check if it matches
      "Surname, Forename" and normalise it to "Forename Surname".
      This is safe to apply globally — multiple styles occasionally
      produce comma-inverted names.

    Returns True if any author was modified.
    """
    if not ref.authors:
        return False

    modified = False
    cleaned: List[str] = []

    for name in ref.authors:
        m = _COMMA_NAME_RE.match(name.strip())
        if m:
            surname, forenames = m.group(1), m.group(2)
            normalised = f"{forenames} {surname}".strip()
            cleaned.append(normalised)
            log.debug("Fix3: '%s' -> '%s'", name, normalised)
            modified = True
        else:
            cleaned.append(name)

    if modified:
        ref.authors = cleaned
    return modified


def _fix4_video_timestamp(ref: ParsedReference) -> bool:
    """
    Video timestamp hallucinations (MLA / Vancouver).

    For YouTube / TED citations, "12:51" is parsed as Volume=12, Page=51.

    Strategy:
      1. Check if container_title or publisher signals a video source.
      2. Search raw_text for HH:MM timestamp patterns.
      3. If volume matches the hour part and pages matches the minute part
         of any timestamp, discard both as hallucinations.

    Returns True if any field was modified.
    """
    raw        = ref.raw_text or ""
    ct         = ref.container_title or ""
    pub        = ref.publisher or ""
    is_video   = bool(
        _VIDEO_SOURCE_RE.search(ct)
        or _VIDEO_SOURCE_RE.search(pub)
        or _VIDEO_SOURCE_RE.search(raw)
    )
    if not is_video:
        return False

    modified = False
    for ts_match in _TIMESTAMP_RE.finditer(raw):
        hours   = ts_match.group(1)   # e.g. "12"
        minutes = ts_match.group(2)   # e.g. "51"

        if ref.volume is not None:
            vol_stripped = ref.volume.strip().lstrip("0") or "0"
            if vol_stripped == hours.lstrip("0") or vol_stripped == hours:
                log.debug("Fix4: discarding volume=%r (video timestamp)", ref.volume)
                ref.volume = None
                modified = True

        if ref.pages is not None:
            page_stripped = ref.pages.strip().lstrip("0") or "0"
            if page_stripped == minutes.lstrip("0") or page_stripped == minutes:
                log.debug("Fix4: discarding pages=%r (video timestamp)", ref.pages)
                ref.pages = None
                modified = True

    return modified


def _fix5_corporate_author_fallback(ref: ParsedReference) -> bool:
    """
    Corporate author vs. publisher.

    For WHO/BBC reports, the organisation goes into publisher and
    authors is left empty.

    Strategy:
      If authors is empty AND publisher is present AND publisher text
      matches known organisation keywords, copy publisher into authors.

    Returns True if authors was populated.
    """
    if ref.authors or not ref.publisher:
        return False

    if _ORG_KEYWORDS_RE.search(ref.publisher):
        ref.authors = [ref.publisher]
        log.debug("Fix5: copied publisher '%s' into authors", ref.publisher)
        return True

    return False


def _fix6_url_title_fallback(ref: ParsedReference) -> bool:
    """
    Vancouver / web missing title fallback.

    When title is missing but a URL is present, synthesise a human-
    readable title from the domain name or URL path.

    Strategy:
      1. Parse the URL hostname:  www.cancer-pain.org → "Cancer-Pain.org"
      2. If path has meaningful slug, use that:
         /articles/gut-microbiome → "Gut Microbiome"
      3. If URL is missing too, fall back to publisher name.

    Returns True if title was populated.
    """
    if ref.title:
        return False

    # Attempt URL-derived title
    if ref.url:
        try:
            parsed = urlparse(ref.url if "://" in ref.url else "https://" + ref.url)
            hostname = parsed.hostname or ""

            # Prefer meaningful path slug over hostname
            path_parts = [p for p in parsed.path.split("/") if p]
            # Strip file extensions from last segment
            slug_candidate = ""
            if path_parts:
                last = re.sub(r"\.\w+$", "", path_parts[-1])
                # A meaningful slug has letters (not just IDs/numbers)
                if re.search(r"[a-zA-Z]{3,}", last):
                    slug_candidate = last

            if slug_candidate:
                # Convert slug to title case: "gut-microbiome" → "Gut Microbiome"
                title = re.sub(_URL_SLUG_RE, " ", slug_candidate).title().strip()
            else:
                # Fall back to domain name, strip www. prefix
                domain = re.sub(r"^www\.", "", hostname)
                title  = domain.title() if domain else ""

            if title:
                ref.title = title
                log.debug("Fix6: synthesised title '%s' from URL", ref.title)
                return True

        except Exception as exc:
            log.debug("Fix6: URL parse failed: %s", exc)

    # Final fallback: publisher as title
    if ref.publisher and not ref.title:
        ref.title = ref.publisher
        log.debug("Fix6: using publisher '%s' as title", ref.title)
        return True

    return False


# ── Master post-processor ─────────────────────────────────────────────

def clean_metadata(ref: ParsedReference) -> ParsedReference:
    """
    Apply all six post-processing fixes to a ParsedReference in sequence.

    Fix order is deliberate:
      2 (patent)  must run before 1/4 so that volume/pages are already
                  cleared if this is a patent before the date checks run.
      1 (accessed date) and 4 (video timestamp) both clear volume/pages
                  so they run after patent detection.
      3 (author)  is independent — safe at any point.
      5 (corporate author) must run after 3 so the author list is clean.
      6 (URL title) runs last as a catch-all fallback.

    Each fix that fires appends its ID to ref.fixes_applied for
    transparency in the output JSON.
    """
    fix_map = [
        ("fix2_patent",           _fix2_patent_number),
        ("fix1_accessed_date",    _fix1_accessed_date),
        ("fix4_video_timestamp",  _fix4_video_timestamp),
        ("fix3_author_inversion", _fix3_author_inversion),
        ("fix5_corporate_author", _fix5_corporate_author_fallback),
        ("fix6_url_title",        _fix6_url_title_fallback),
    ]
    for fix_id, fix_fn in fix_map:
        try:
            if fix_fn(ref):
                ref.fixes_applied.append(fix_id)
        except Exception as exc:
            # Never let a post-processing bug corrupt an otherwise good record
            log.warning("Post-processing error in %s: %s", fix_id, exc)

    return ref


# ──────────────────────────────────────────────────────────────────────
# 6.  FULL RECORD PARSER  (XML → ParsedReference → clean_metadata)
# ──────────────────────────────────────────────────────────────────────

def parse_reference(xml_bytes: bytes, raw_text: str) -> ParsedReference:
    """
    Parse the TEI-XML output into a ParsedReference, then apply
    clean_metadata() post-processing to fix known field extraction errors.

    This is the single authoritative entry point for XML → structured data.
    """
    root = strip_namespaces(xml_bytes)
    if root is None:
        return ParsedReference(raw_text=raw_text, parser_status="parse_error")

    ref = ParsedReference(
        title           = extract_title(root),
        authors         = extract_authors(root),
        container_title = extract_container_title(root),
        pub_date        = extract_pub_date(root),
        volume          = extract_biblscope(root, "volume"),
        issue           = extract_biblscope(root, "issue"),
        pages           = extract_biblscope(root, "page"),
        doi             = extract_doi(root),
        url             = extract_url(root),
        publisher       = extract_publisher(root),
        raw_text        = raw_text,
        parser_status   = "ok",
    )

    # Apply post-processing fixes
    ref = clean_metadata(ref)

    # Mark as empty when nothing useful was found after post-processing
    if not any([ref.title, ref.authors, ref.container_title,
                ref.pub_date, ref.doi, ref.patent_number]):
        ref.parser_status = "empty"

    return ref


# ──────────────────────────────────────────────────────────────────────
# 7.  PROCESS ONE RECORD
# ──────────────────────────────────────────────────────────────────────

def process_record(
    record:  Dict[str, Any],
    session: requests.Session,
    url:     str,
    timeout: int,
) -> Dict[str, Any]:
    """
    Run one input record through the full pipeline:
      raw text → field extraction → XML → parse_reference → clean_metadata → dict

    Returns the original record with a "parsed" key added.
    Never raises — all errors captured in parser_status.
    """
    text = record.get("text", "").strip()

    if not text:
        return {**record, "parsed": ParsedReference(
            raw_text=text, parser_status="no_text"
        ).to_dict()}

    xml_bytes = call_parser(session, text, url=url, timeout=timeout)

    if xml_bytes is None:
        return {**record, "parsed": ParsedReference(
            raw_text=text, parser_status="failed"
        ).to_dict()}

    return {**record, "parsed": parse_reference(xml_bytes, raw_text=text).to_dict()}


# ──────────────────────────────────────────────────────────────────────
# 8.  PARSER HEALTH CHECK
# ──────────────────────────────────────────────────────────────────────

def check_parser_alive(endpoint_url: str, timeout: int = 5) -> bool:
    base   = endpoint_url.replace("/api/processCitation", "").rstrip("/")
    health = f"{base}/api/isalive"
    try:
        return requests.get(health, timeout=timeout).status_code == 200
    except requests.exceptions.RequestException:
        return False


# ──────────────────────────────────────────────────────────────────────
# 9.  DEBUG / VERBOSE MODE
# ──────────────────────────────────────────────────────────────────────

def debug_record(record: Dict[str, Any], url: str, timeout: int) -> None:
    """Full pipeline trace for a single record — useful for diagnosis."""
    text = record.get("text", "")
    print("\n" + "─" * 64)
    print("  DEBUG — first record")
    print("─" * 64)
    print(f"  text   : {text[:120]}")
    print(f"  style  : {record.get('style')}")
    print(f"  source : {record.get('source')}")

    session   = requests.Session()
    xml_bytes = call_parser(session, text, url=url, timeout=timeout)
    session.close()

    if xml_bytes is None:
        print("\n  Parser model returned no output — check that the service is reachable.")
        return

    print(f"\n  Raw XML ({len(xml_bytes)} bytes):")
    root = strip_namespaces(xml_bytes)
    if root is not None:
        try:
            pretty = etree.tostring(root, pretty_print=True).decode()
            for line in pretty.splitlines()[:60]:
                print(f"    {line}")
        except Exception:
            print(f"    {xml_bytes[:400]}")

    parsed = parse_reference(xml_bytes, raw_text=text)
    d = parsed.to_dict()

    print("\n  Extracted fields (after post-processing):")
    for k, v in d.items():
        if k != "raw_text":
            print(f"    {k:<20}: {v}")

    if d.get("fixes_applied"):
        print(f"\n  Post-processing fixes fired: {d['fixes_applied']}")
    else:
        print("\n  No post-processing fixes were needed.")
    print()


# ──────────────────────────────────────────────────────────────────────
# 10.  MAIN PIPELINE
# ──────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        sys.exit(f"[ERROR] Input file not found: {input_path}")

    print(f"  Loading {input_path} ...", end=" ", flush=True)
    try:
        with open(input_path, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"[ERROR] JSON parse failed: {exc}")

    if not isinstance(raw, list):
        sys.exit(f"[ERROR] Expected a JSON array, got {type(raw).__name__}")

    records: List[Dict] = raw[: args.limit] if args.limit else raw
    print(f"{len(records):,} records")

    print(f"  Checking extraction model at {args.url} ...", end=" ", flush=True)
    if check_parser_alive(args.url):
        print("ok")
    else:
        print()
        sys.exit(
            f"[ERROR] Field extraction model not responding at {args.url}\n"
            "  Ensure the extraction service is running and reachable.\n"
        )

    if args.dry_run:
        print("\n  [DRY-RUN] No output will be written.\n")

    print(f"\n  Workers  : {args.workers}")
    print(f"  Timeout  : {args.timeout}s")
    print(f"  Output   : {output_path}\n")

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections = args.workers,
        pool_maxsize     = args.workers * 2,
    )
    session.mount("http://", adapter)

    results: List[Optional[Dict]] = [None] * len(records)
    status_ok    = 0
    status_fail  = 0
    status_empty = 0
    fixes_total  = 0

    def _worker(idx_record):
        idx, rec = idx_record
        return idx, process_record(rec, session, args.url, args.timeout)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_worker, (i, rec)): i
            for i, rec in enumerate(records)
        }

        pbar = tqdm(
            total=len(records), desc="Parsing", unit="ref", dynamic_ncols=True
        )

        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            pbar.update(1)

            p      = result.get("parsed", {})
            status = p.get("parser_status", "?")
            n_fixes = len(p.get("fixes_applied", []))

            if status == "ok":
                status_ok += 1
            elif status in ("failed", "parse_error", "no_text"):
                status_fail += 1
            else:
                status_empty += 1

            fixes_total += n_fixes
            pbar.set_postfix(ok=status_ok, fail=status_fail, fixes=fixes_total)

        pbar.close()

    session.close()

    if not args.dry_run:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n  Saved {len(results):,} records -> {output_path}")

    total = len(records)
    print("\n" + "=" * 62)
    print("  COMPLETE")
    print("=" * 62)
    print(f"  Total records    : {total:>8,}")
    print(f"  Parsed ok        : {status_ok:>8,}  ({status_ok/max(total,1)*100:.1f}%)")
    print(f"  Empty results    : {status_empty:>8,}  ({status_empty/max(total,1)*100:.1f}%)")
    print(f"  Failed           : {status_fail:>8,}  ({status_fail/max(total,1)*100:.1f}%)")
    print(f"  Post-fixes fired : {fixes_total:>8,}  across all records")
    print("=" * 62)


# ──────────────────────────────────────────────────────────────────────
# 11.  CLI
# ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description     = "Production-grade reference field extraction model with post-processing.",
        formatter_class = argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input",   default=INPUT_FILE)
    p.add_argument("--output",  default=OUTPUT_FILE)
    p.add_argument("--url",     default=PARSER_ENDPOINT)
    p.add_argument("--workers", type=int, default=NUM_WORKERS)
    p.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT)
    p.add_argument("--limit",   type=int, default=None,
                   help="Process only first N records")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--verbose", action="store_true",
                   help="Debug-trace first record and exit")
    return p.parse_args()


# ──────────────────────────────────────────────────────────────────────
# 12.  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    missing = []
    for pkg, mod in [("requests","requests"),("tqdm","tqdm"),("lxml","lxml")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit(
            f"[ERROR] Missing: {', '.join(missing)}\n"
            f"Run: pip install {' '.join(missing)}"
        )

    args = _parse_args()

    if args.verbose:
        p = Path(args.input)
        if not p.exists():
            sys.exit(f"[ERROR] Not found: {p}")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        first = data[0] if isinstance(data, list) and data else data
        debug_record(first, args.url, args.timeout)
        sys.exit(0)

    run(args)