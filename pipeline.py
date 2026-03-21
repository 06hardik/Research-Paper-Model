"""
pipeline.py
===========
Reference List Quality Pipeline
================================
Accepts OCR-extracted reference section text as a JSON array of entries,
runs them through:
  1. Grobid field parsing (HTTP to local Grobid docker instance)
  2. Citation style classification
  3. Check 1  — ordering (numeric or alphabetical)
  4. Check 3  — journal title casing consistency + correctness
  5. Check 4  — field completeness + formatting errors

Input JSON schema:
  [
    {
      "id":       "ref_001",
      "raw_text": "Smith, J. A. (2020). Deep learning. Nature, 5(3), 45.",
      "metadata": { "ocr_confidence": 0.95 }
    },
    ...
  ]

Output JSON schema (written to output file and returned from run()):
  {
    "summary": {
      "total": 10,
      "style": "APA",
      "style_confidence": "HIGH",
      "checks_passed": ["ordering", "journal_casing"],
      "checks_failed": ["completeness"],
      "parsed_ok": 9,
      "parsed_failed": 1
    },
    "entries": [...],
    "list_level_issues": [...]
  }

Usage:
  python pipeline.py input.json
  python pipeline.py input.json --output results.json
  python pipeline.py input.json --parser-url http://localhost:8070 --workers 4
  python pipeline.py input.json --dry-run       # skip field extraction, use raw_text only
  python pipeline.py --help
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ── sibling imports ──────────────────────────────────────────────────────────
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from citation_classifier import classify
from reference_parser import (
    call_parser,
    parse_reference,
    check_parser_alive,
    ParsedReference,
)
from checks.check_ordering        import check_ordering
from checks.check_journal_casing  import check_journal_casing
from checks.check_completeness    import check_completeness
from checks.check_doi             import check_doi
from checks.check_style_conformity import check_style_conformity


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

# PARSER_URL is expected in hosted/API deployments. Keep localhost only as a
# CLI/dev fallback reference; run() resolves env explicitly at runtime.
PARSER_ENDPOINT  = os.environ.get(
    "PARSER_URL", "http://localhost:8070/api/processCitation"
)
NUM_WORKERS     = int(os.environ.get("PARSER_WORKERS", "4"))
REQUEST_TIMEOUT = int(os.environ.get("PARSER_TIMEOUT", "25"))
MAX_RETRIES     = int(os.environ.get("PARSER_RETRIES", "5"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1 — Grobid parsing
# ---------------------------------------------------------------------------

def _parse_one(
    entry:   Dict[str, Any],
    session: requests.Session,
    url:     str,
    timeout: int,
) -> Dict[str, Any]:
    """
    Parse a single entry through the field extraction model.
    Attaches a 'parsed' key to the entry dict.
    Never raises — failures are recorded in parser_status.
    """
    raw = (entry.get("raw_text") or "").strip()

    if not raw:
        entry["parsed"] = ParsedReference(
            raw_text=raw, parser_status="no_text"
        ).to_dict()
        return entry

    xml_bytes = call_parser(session, raw, url=url, timeout=timeout, retries=MAX_RETRIES)

    if xml_bytes is None:
        entry["parsed"] = ParsedReference(
            raw_text=raw, parser_status="failed"
        ).to_dict()
        return entry

    entry["parsed"] = parse_reference(xml_bytes, raw_text=raw).to_dict()
    return entry


def run_parser_batch(
    entries: List[Dict[str, Any]],
    url:     str,
    timeout: int,
    workers: int,
) -> List[Dict[str, Any]]:
    """Parse all entries through the field extraction model concurrently. Preserves ordering."""
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=workers,
        pool_maxsize=workers * 2,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    results: List[Optional[Dict]] = [None] * len(entries)

    def _worker(idx_entry):
        idx, entry = idx_entry
        return idx, _parse_one(entry, session, url, timeout)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_worker, (i, e)): i
            for i, e in enumerate(entries)
        }
        ok = fail = 0
        for future in as_completed(futures):
            idx, enriched = future.result()
            results[idx] = enriched
            status = (enriched.get("parsed") or {}).get("parser_status", "?")
            if status == "ok":
                ok += 1
            else:
                fail += 1

    session.close()
    log.info("Parser: %d ok, %d failed/empty", ok, fail)
    return results  # type: ignore[return-value]


def run_parser_dry(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dry-run: attach an empty parsed stub so downstream checks still run.
    Useful for testing the checks without a running extraction service.
    """
    for entry in entries:
        entry.setdefault("parsed", ParsedReference(
            raw_text=entry.get("raw_text") or entry.get("text") or "",
            parser_status="dry_run",
        ).to_dict())
    return entries


# ---------------------------------------------------------------------------
# Step 2 — Style classification
# ---------------------------------------------------------------------------

def _detect_dominant_style(entries: List[Dict[str, Any]]) -> tuple:
    """
    Classify every entry and return (dominant_style, confidence).
    Dominant style = highest weighted vote across all entries.
    Confidence weights: HIGH=3, MEDIUM=2, LOW=1.
    """
    from collections import Counter
    style_votes: Counter = Counter()
    conf_weight = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    for entry in entries:
        raw = (entry.get("raw_text") or entry.get("text") or "").strip()
        if not raw:
            continue
        result = classify(raw)
        entry["style"] = {
            "predicted":  result.predicted_style,
            "confidence": result.confidence,
            "scores":     result.scores,
        }
        weight = conf_weight.get(result.confidence, 1)
        style_votes[result.predicted_style] += weight

    if not style_votes:
        return "Unknown", "LOW"

    dominant = style_votes.most_common(1)[0][0]
    total    = sum(style_votes.values())
    frac     = style_votes[dominant] / max(total, 1)
    conf     = "HIGH" if frac >= 0.6 else "MEDIUM" if frac >= 0.4 else "LOW"
    return dominant, conf


# ---------------------------------------------------------------------------
# Steps 3–5 — Checks
# ---------------------------------------------------------------------------

def _run_checks(
    entries:        List[Dict[str, Any]],
    dominant_style: str,
    deep_doi:       bool = False,
    crossref_email: Optional[str] = None,
) -> tuple:
    """
    Run all quality checks.

    Returns
    -------
    (per_entry_issues, list_level_issues, checks_passed, checks_failed)
      per_entry_issues  : dict[ref_id -> list of issue dicts]
      list_level_issues : list of issue dicts (whole-list scope)
      checks_passed     : list of check name strings
      checks_failed     : list of check name strings
    """
    per_entry:  Dict[str, List[Dict]] = {e["id"]: [] for e in entries}
    list_level: List[Dict] = []

    # ── Check 1: Ordering ────────────────────────────────────────────
    ordering_result = check_ordering(entries, dominant_style)
    for iss in ordering_result.issues:
        list_level.append({
            "check":    "ordering",
            "ref_id":   iss.ref_id,
            "position": iss.position,
            "detail":   iss.issue,
            "expected": iss.expected,
            "found":    iss.found,
        })

    # ── Check 2: DOI presence ────────────────────────────────────────
    doi_result = check_doi(
        entries,
        deep_check     = deep_doi,
        crossref_email = crossref_email,
    )
    for iss in doi_result.issues:
        per_entry.setdefault(iss.ref_id, []).append({
            "check":      "doi",
            "field":      "doi",
            "issue_type": iss.issue_type,
            "detail":     iss.detail,
            "found":      iss.doi_found,
            "suggestion": iss.suggestion,
        })

    # ── Check 3: Journal casing ──────────────────────────────────────
    casing_result = check_journal_casing(entries, dominant_style)
    for iss in casing_result.issues:
        per_entry.setdefault(iss.ref_id, []).append({
            "check":      "journal_casing",
            "field":      "container_title",
            "issue_type": iss.issue_type,
            "detail":     iss.detail,
            "found":      iss.journal,
            "suggestion": iss.suggestion,
        })

    # ── Check 4: Completeness + formatting ──────────────────────────
    completeness_result = check_completeness(entries, dominant_style)
    for iss in completeness_result.issues:
        per_entry.setdefault(iss.ref_id, []).append({
            "check":      "completeness",
            "field":      iss.field_name,
            "issue_type": iss.issue_type,
            "detail":     iss.detail,
            "found":      iss.found,
            "suggestion": iss.suggestion,
        })

    # ── Check 5: Style conformity ────────────────────────────────────
    conformity_result = check_style_conformity(entries, dominant_style)
    for iss in conformity_result.issues:
        per_entry.setdefault(iss.ref_id, []).append({
            "check":      "style_conformity",
            "field":      "style",
            "issue_type": "style_mismatch",
            "detail":     iss.detail,
            "found":      iss.entry_style,
            "suggestion": iss.suggestion,
        })

    # ── Determine pass/fail ──────────────────────────────────────────
    checks_passed, checks_failed = [], []
    for check_id, result_obj in [
        ("ordering",        ordering_result),
        ("doi",             doi_result),
        ("journal_casing",  casing_result),
        ("completeness",    completeness_result),
        ("style_conformity",conformity_result),
    ]:
        (checks_passed if result_obj.passed else checks_failed).append(check_id)

    return per_entry, list_level, checks_passed, checks_failed


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def _assemble_output(
    entries:           List[Dict[str, Any]],
    per_entry_issues:  Dict[str, List[Dict]],
    list_level_issues: List[Dict],
    dominant_style:    str,
    style_confidence:  str,
    checks_passed:     List[str],
    checks_failed:     List[str],
) -> Dict[str, Any]:
    """Assemble the final output document."""
    total = len(entries)
    parsed_ok   = sum(1 for e in entries
                      if (e.get("parsed") or {}).get("parser_status") == "ok")
    parsed_fail = total - parsed_ok

    if parsed_ok == total:
        processing_status = "ok"
        suggested_http_status = 200
    elif parsed_ok == 0:
        processing_status = "failed"
        suggested_http_status = 503
    else:
        processing_status = "partial"
        suggested_http_status = 207

    output_entries = []
    for entry in entries:
        eid = entry.get("id", "")
        output_entries.append({
            "id":       eid,
            "raw_text": entry.get("raw_text", ""),
            "metadata": entry.get("metadata", {}),
            "parsed":   entry.get("parsed", {}),
            "style":    entry.get("style", {}),
            "issues":   per_entry_issues.get(eid, []),
        })

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "processing_status": processing_status,
        "parser_summary": {
            "total": total,
            "parsed_ok": parsed_ok,
            "parsed_failed": parsed_fail,
            "success_rate": round(parsed_ok / max(total, 1), 4),
            "suggested_http_status": suggested_http_status,
        },
        "summary": {
            "total":            total,
            "style":            dominant_style,
            "style_confidence": style_confidence,
            "checks_passed":    checks_passed,
            "checks_failed":    checks_failed,
            "total_issues":     (
                sum(len(v) for v in per_entry_issues.values())
                + len(list_level_issues)
            ),
            "parsed_ok":        parsed_ok,
            "parsed_failed":    parsed_fail,
        },
        "list_level_issues": list_level_issues,
        "entries":           output_entries,
    }


# ---------------------------------------------------------------------------
# Text report renderer
# ---------------------------------------------------------------------------

def _text_report(output: Dict[str, Any]) -> str:
    """Generate a clean, human-readable plain-text report."""
    W = 72
    lns: List[str] = []
    def add(s: str = "") -> None:
        lns.append(s)
    def rule(ch: str = "─") -> None:
        add(ch * W)
    def section(title: str) -> None:
        add()
        rule("─")
        add(f"  {title}")
        rule("─")

    # ── Header ────────────────────────────────────────────────────────
    rule("═")
    add("  REFERENCE LIST QUALITY REPORT")
    rule("═")
    s = output["summary"]
    add(f"  Generated  : {output['generated_at'].replace('T',' ').replace('Z','')}")
    add(f"  Entries    : {s['total']}  (parsed: {s['parsed_ok']}"
        + (f", failed: {s['parsed_failed']}" if s['parsed_failed'] else "") + ")")
    add(f"  Style      : {s['style']}  [{s['style_confidence']} confidence]")
    add(f"  Issues     : {s['total_issues']} total")

    # ── Check summary table ───────────────────────────────────────────
    section("CHECK SUMMARY")
    checks_info = [
        ("ordering",         "1",  "Reference ordering"),
        ("doi",              "2",  "DOI presence"),
        ("journal_casing",   "3",  "Journal title casing"),
        ("completeness",     "4",  "Field completeness & formatting"),
        ("style_conformity", "5",  "Citation style conformity"),
    ]
    for check_id, num, label in checks_info:
        if check_id in s.get("checks_passed", []):
            mark = "✓  PASS"
        elif check_id in s.get("checks_failed", []):
            mark = "✗  FAIL"
        else:
            mark = "–  SKIP"
        # Count issues for this check
        all_issues = [
            i
            for e in output["entries"]
            for i in (e.get("issues") or [])
            if i.get("check") == check_id
        ] + [
            i for i in (output.get("list_level_issues") or [])
            if i.get("check") == check_id
        ]
        if check_id == "doi":
            n_confirmed = sum(1 for i in all_issues if i.get("issue_type") == "crossref_found")
            n_advisory  = len(all_issues) - n_confirmed
            if n_confirmed:
                count_str = f"  ({n_confirmed} confirmed missing, {n_advisory} advisory)"
            elif n_advisory:
                count_str = f"  ({n_advisory} advisory — run --deep-doi to confirm)"
            else:
                count_str = ""
        else:
            n = len(all_issues)
            count_str = f"  ({n} issue{'s' if n != 1 else ''})" if n else ""
        add(f"  {mark}   {num}. {label}{count_str}")

    # ── List-level issues (ordering) ─────────────────────────────────
    list_issues = [i for i in (output.get("list_level_issues") or [])
                   if i.get("check") == "ordering"]
    if list_issues:
        section("ORDERING ISSUES")
        for iss in list_issues:
            pos = iss.get("position", "?")
            rid = iss.get("ref_id", "")
            add(f"  ✗  [{rid}]  (position {pos})")
            add(f"     {iss['detail']}")
            if iss.get("expected") and iss.get("found"):
                add(f"     Expected  : {iss['expected']}")
                add(f"     Found     : {iss['found']}")
            add()

    # ── Style-conformity mismatches ───────────────────────────────────
    conformity_issues = [
        (e, i)
        for e in output["entries"]
        for i in (e.get("issues") or [])
        if i.get("check") == "style_conformity"
    ]
    if conformity_issues:
        section(f"STYLE CONFORMITY  —  expected: {s['style']}")
        for entry, iss in conformity_issues:
            raw = (entry.get("raw_text") or "")
            raw_short = raw[:95] + ("…" if len(raw) > 95 else "")
            add(f"  ✗  [{entry['id']}]")
            add(f"     {raw_short}")
            add(f"     {iss['detail']}")
            if iss.get("suggestion"):
                add(f"     Fix: {iss['suggestion']}")
            add()

    # ── DOI issues ────────────────────────────────────────────────────
    doi_errors = [
        (e, i)
        for e in output["entries"]
        for i in (e.get("issues") or [])
        if i.get("check") == "doi" and i.get("issue_type") == "crossref_found"
    ]
    doi_advisory = [
        (e, i)
        for e in output["entries"]
        for i in (e.get("issues") or [])
        if i.get("check") == "doi" and i.get("issue_type") != "crossref_found"
    ]

    if doi_errors:
        section("DOI  —  CONFIRMED MISSING  (CrossRef found a DOI)")
        for entry, iss in doi_errors:
            add(f"  ✗  [{entry['id']}]  →  {iss.get('detail','')}")
            if iss.get("suggestion"):
                add(f"     {iss['suggestion']}")
            add()

    if doi_advisory:
        section(f"DOI  —  ADVISORY  ({len(doi_advisory)} entries have no DOI in text)")
        add("  These entries have no DOI in the text. Add one if the work")
        add("  has been registered (run with --deep-doi to query CrossRef).")
        add()
        for entry, iss in doi_advisory:
            raw = (entry.get("raw_text") or "")[:80]
            add(f"  ·  [{entry['id']}]  {raw}{'…' if len(entry.get('raw_text','')) > 80 else ''}")

    # ── Per-entry issues (casing + completeness) ──────────────────────
    _SEV = {
        "missing":       ("✗", "MISSING"),
        "formatting":    ("⚠", "FORMAT "),
        "suspicious":    ("·", "ADVISORY"),
        "inconsistent":  ("⚠", "INCONSISTENT"),
        "wrong_case":    ("⚠", "WRONG CASE"),
        "all_caps":      ("⚠", "ALL CAPS"),
        "style_mismatch":("✗", "STYLE  "),
    }

    quality_checks = {"completeness", "journal_casing"}
    entries_with_quality = [
        e for e in output["entries"]
        if any(i.get("check") in quality_checks for i in (e.get("issues") or []))
    ]

    if entries_with_quality:
        section("FIELD & FORMATTING ISSUES")

        # Split into errors/warnings and advisories
        for entry in entries_with_quality:
            issues_here = [
                i for i in (entry.get("issues") or [])
                if i.get("check") in quality_checks
            ]
            errors   = [i for i in issues_here if i.get("issue_type") in ("missing", "formatting", "inconsistent", "wrong_case", "all_caps")]
            advisory = [i for i in issues_here if i.get("issue_type") == "suspicious"]

            if not errors and not advisory:
                continue

            raw      = (entry.get("raw_text") or "")
            raw_trunc = raw[:90] + ("…" if len(raw) > 90 else "")
            sty      = entry.get("style") or {}
            pred_sty = sty.get("predicted", "?")
            pred_con = sty.get("confidence", "?")

            add(f"  ┌─ [{entry['id']}]  (classified: {pred_sty} / {pred_con})")
            add(f"  │  {raw_trunc}")

            for iss in errors:
                itype = iss.get("issue_type", "")
                sym, label = _SEV.get(itype, ("·", itype.upper()))
                field = iss.get("field", "")
                add(f"  │  {sym} {label:<12}  [{field}]  {iss['detail']}")
                if iss.get("suggestion"):
                    add(f"  │              Fix: {iss['suggestion']}")

            if advisory:
                add(f"  │  ─ advisories ({len(advisory)}):")
                for iss in advisory:
                    field = iss.get("field", "")
                    add(f"  │  · ADVISORY       [{field}]  {iss['detail']}")

            add("  └" + "─" * (W - 3))
            add()

    # ── Clean finish ──────────────────────────────────────────────────
    if s["total_issues"] == 0:
        add()
        add("  ✓  All checks passed — reference list looks clean!")

    add()
    rule("═")
    return "\n".join(lns) + "\n"


# ---------------------------------------------------------------------------
# Public run() entry point (importable API)
# ---------------------------------------------------------------------------

def run(
    entries:        List[Dict[str, Any]],
    parser_url:     Optional[str] = None,
    workers:        int           = NUM_WORKERS,
    timeout:        int           = REQUEST_TIMEOUT,
    dry_run:        bool          = False,
    deep_doi:       bool          = False,
    crossref_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full pipeline on a list of reference entry dicts.

    Parameters
    ----------
    entries        : list of {"id": ..., "raw_text": ..., "metadata": {...}}
    parser_url     : field extraction model endpoint (falls back to PARSER_URL env var)
    workers        : concurrent worker threads
    timeout        : per-request timeout in seconds
    dry_run        : if True, skip field extraction
    deep_doi       : if True, run CrossRef API lookups for missing DOIs
    crossref_email : mailto email for CrossRef polite-pool header

    Returns
    -------
    Output dict (see module docstring for schema).
    """
    if not entries:
        raise ValueError("entries list is empty")

    # Ensure every entry has an id
    for i, e in enumerate(entries):
        if not e.get("id"):
            e["id"] = f"ref_{i+1:03d}"

    # Resolve parser endpoint from arg/env once per request.
    resolved_parser_url = (parser_url or os.environ.get("PARSER_URL") or "").strip()

    # Step 1: Grobid
    if dry_run:
        entries = run_parser_dry(entries)
    else:
        if not resolved_parser_url:
            raise RuntimeError(
                "PARSER_URL is not configured for extraction. "
                "Set PARSER_URL to a reachable /api/processCitation endpoint."
            )

        if not check_parser_alive(resolved_parser_url):
            raise RuntimeError(
                f"Field extraction model not reachable at {resolved_parser_url}\n"
                "  Ensure the extraction service is running and accessible."
            )
        entries = run_parser_batch(entries, resolved_parser_url, timeout, workers)

        parsed_ok = sum(
            1 for e in entries if (e.get("parsed") or {}).get("parser_status") == "ok"
        )
        if parsed_ok == 0:
            raise RuntimeError(
                "Extraction backend responded but no entries were parsed successfully. "
                "Please retry; if this persists, check parser service capacity/logs."
            )

    # Step 2: Classify
    dominant_style, style_confidence = _detect_dominant_style(entries)

    # Steps 3-7: Checks
    per_entry_issues, list_level_issues, checks_passed, checks_failed = \
        _run_checks(
            entries,
            dominant_style,
            deep_doi       = deep_doi,
            crossref_email = crossref_email,
        )

    return _assemble_output(
        entries           = entries,
        per_entry_issues  = per_entry_issues,
        list_level_issues = list_level_issues,
        dominant_style    = dominant_style,
        style_confidence  = style_confidence,
        checks_passed     = checks_passed,
        checks_failed     = checks_failed,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reference List Quality Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input",
                   help="Path to input JSON file")
    p.add_argument("--output", "-o", default=None,
                   help="JSON output path  (default: <input>_results.json)")
    p.add_argument("--report", "-r", default=None,
                   help="Text report path  (default: <input>_report.txt)")
    p.add_argument("--parser-url", default=PARSER_ENDPOINT,
                   help="Field extraction model endpoint URL")
    p.add_argument("--workers", type=int, default=NUM_WORKERS,
                   help="Concurrent worker threads")
    p.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT,
                   help="Per-request timeout (seconds)")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip field extraction — run classifier and checks only")
    p.add_argument("--deep-doi", action="store_true",
                   help="Enable CrossRef API lookups for missing DOIs (Strategy A)")
    p.add_argument("--crossref-email", default=None,
                   help="Email for CrossRef polite-pool header (used with --deep-doi)")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress progress output")
    return p.parse_args()


def _main() -> None:
    args    = _parse_args()
    in_path = Path(args.input)

    if not in_path.exists():
        sys.exit(f"[ERROR] Input file not found: {in_path}")

    try:
        with open(in_path, encoding="utf-8") as f:
            entries = json.load(f)
    except json.JSONDecodeError as exc:
        sys.exit(f"[ERROR] JSON parse failed: {exc}")

    if not isinstance(entries, list):
        sys.exit("[ERROR] Input must be a JSON array")

    if not args.quiet:
        print(f"\n  Pipeline starting — {len(entries)} entries")
        if args.dry_run:
            print("  [DRY-RUN] Field extraction step skipped")

    t0 = time.perf_counter()

    if not args.quiet and args.deep_doi:
        print("  [DEEP-DOI] CrossRef API lookups enabled")
        if not args.crossref_email:
            print("  [WARN] --crossref-email not set; CrossRef may throttle requests")

    try:
        output = run(
            entries        = entries,
            parser_url     = args.parser_url,
            workers        = args.workers,
            timeout        = args.timeout,
            dry_run        = args.dry_run,
            deep_doi       = args.deep_doi,
            crossref_email = args.crossref_email,
        )
    except RuntimeError as exc:
        sys.exit(f"\n[ERROR] {exc}")

    elapsed = time.perf_counter() - t0

    # Write JSON output
    out_path = Path(args.output) if args.output else \
        in_path.with_name(in_path.stem + "_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Write text report
    rpt_path = Path(args.report) if args.report else \
        in_path.with_name(in_path.stem + "_report.txt")
    report_text = _text_report(output)
    with open(rpt_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    if not args.quiet:
        s = output["summary"]
        print(f"\n  Done in {elapsed:.1f}s")
        print(f"  Style detected : {s['style']}  ({s['style_confidence']} confidence)")
        print(f"  Checks passed  : {', '.join(s['checks_passed']) or 'none'}")
        print(f"  Checks failed  : {', '.join(s['checks_failed']) or 'none'}")
        print(f"  Total issues   : {s['total_issues']}")
        print(f"\n  JSON  → {out_path}")
        print(f"  Report → {rpt_path}\n")
        print(report_text)


if __name__ == "__main__":
    _main()