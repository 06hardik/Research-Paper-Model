"""
api.py
======
FastAPI HTTP service wrapper for the Reference Section Quality Pipeline.

Exposes the full pipeline as a REST API so it can be deployed independently
and called by any project over HTTP.

Endpoints
---------
  POST /analyze          Run the full pipeline; returns JSON quality report
  GET  /health           Liveness + extraction-engine reachability check
  GET  /docs             Auto-generated Swagger UI (OpenAPI)
  GET  /redoc            ReDoc UI

Request  → POST /analyze
  {
    "entries": [
      {
        "id":       "ref_001",              // optional — auto-assigned if omitted
        "raw_text": "Smith J. Title. ...",
        "metadata": {}                      // optional pass-through
      }
    ],
    "dry_run":        false,  // skip field extraction (no extraction engine needed)
    "deep_doi":       false,  // query CrossRef to confirm missing DOIs
    "crossref_email": null    // your email for CrossRef polite-pool header
  }

Response → same JSON schema as pipeline.run()
  {
    "generated_at": "...",
    "summary": { "total": 5, "style": "APA", "style_confidence": "HIGH", ... },
    "list_level_issues": [...],
    "entries": [...]
  }

Environment variables
---------------------
  PARSER_URL   URL of the field extraction service
               default: http://localhost:8070/api/processCitation
  API_PORT     Port for uvicorn to bind
               default: 8000  (can also be set via uvicorn --port flag)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pipeline import run, PARSER_ENDPOINT
from reference_parser import check_parser_alive

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Reference Section Quality API",
    description=(
        "Accepts a JSON array of citation strings and runs five quality checks:\n\n"
        "1. **Ordering** — numeric (IEEE/Vancouver) or alphabetical (APA/MLA/Harvard)\n"
        "2. **DOI presence** — text-based, optionally confirmed via CrossRef\n"
        "3. **Journal title casing** — per-style convention + cross-list consistency\n"
        "4. **Field completeness & formatting** — required/recommended fields per style and reference type\n"
        "5. **Style conformity** — each entry vs. the dominant list style"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ReferenceEntry(BaseModel):
    """A single citation entry."""
    id:       Optional[str]              = Field(
        default=None,
        description="Unique identifier. Auto-assigned as ref_001, ref_002 … if omitted."
    )
    raw_text: str = Field(
        description="The raw citation string exactly as extracted from the document."
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Arbitrary pass-through metadata (e.g. OCR confidence score)."
    )


class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""
    entries: List[ReferenceEntry] = Field(
        description="Ordered list of citation entries to analyse."
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "If true, skip field extraction and run the classifier and checks "
            "against the raw text only. Useful when the extraction engine is not "
            "running or for quick tests."
        )
    )
    deep_doi: bool = Field(
        default=False,
        description=(
            "If true, query the CrossRef REST API for each entry that has no DOI "
            "in order to confirm whether one exists. Adds latency."
        )
    )
    crossref_email: Optional[str] = Field(
        default=None,
        description=(
            "Your email address. Passed as a mailto: header to CrossRef so your "
            "requests are served from the polite pool (higher rate limit). "
            "Only used when deep_doi is true."
        )
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "entries": [
                    {
                        "id":       "ref_001",
                        "raw_text": (
                            "J. Smith, \"Deep learning for NLP,\" "
                            "IEEE Trans. Neural Netw., vol. 31, no. 2, pp. 45–52, 2020."
                        ),
                        "metadata": {"ocr_confidence": 0.97}
                    },
                    {
                        "id":       "ref_002",
                        "raw_text": (
                            "A. Jones, \"Attention mechanisms,\" "
                            "IEEE Trans. Pattern Anal., vol. 42, no. 1, pp. 10–22, 2019."
                        ),
                        "metadata": {}
                    }
                ],
                "dry_run":        False,
                "deep_doi":       False,
                "crossref_email": None
            }
        }
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    summary="Liveness check",
    tags=["status"],
)
def health() -> Dict[str, Any]:
    """
    Returns `{"status": "ok"}` if the API is running.
    Also reports whether the extraction engine (GROBID) is reachable,
    so callers can decide whether to use `dry_run` mode.
    """
    parser_url = os.environ.get("PARSER_URL", PARSER_ENDPOINT)
    reachable  = check_parser_alive(parser_url)
    return {
        "status":           "ok",
        "parser_reachable": reachable,
        "parser_url":       parser_url,
    }


@app.post(
    "/analyze",
    summary="Run the full quality pipeline",
    tags=["pipeline"],
    response_description="Full quality report for the submitted reference list",
)
def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    """
    Submit a reference list for quality analysis.

    The pipeline runs five checks and returns a structured report that includes:
    - Detected citation style (with confidence)
    - Per-entry issues (missing fields, wrong formatting, style mismatches)
    - List-level issues (ordering violations)
    - A pass/fail summary per check

    Set `dry_run: true` if the extraction engine is not running — the pipeline
    will still classify entries and run all checks using the raw text.
    
    NOTE: On Render (and other cloud deployments), the extraction engine may not 
    be available. In this case, the API will automatically use dry_run mode, which:
    - Skips field extraction (parsing titles, authors, etc.)
    - Still performs style classification and quality checks on raw text
    - Is faster but provides less detailed information
    """
    if not req.entries:
        raise HTTPException(status_code=422, detail="entries list must not be empty")

    # Convert Pydantic models → plain dicts for pipeline.run()
    entries_dicts: List[Dict[str, Any]] = [e.model_dump() for e in req.entries]

    parser_url = os.environ.get("PARSER_URL", PARSER_ENDPOINT)
    
    # Check if extraction engine is available
    parser_available = check_parser_alive(parser_url)
    
    # If user didn't request dry_run but parser is not available, auto-enable it
    use_dry_run = req.dry_run or not parser_available

    log.info(
        "analyze() called: %d entries, dry_run=%s (user requested=%s, parser available=%s), deep_doi=%s",
        len(entries_dicts), use_dry_run, req.dry_run, parser_available, req.deep_doi,
    )

    try:
        result = run(
            entries        = entries_dicts,
            parser_url     = parser_url,
            dry_run        = use_dry_run,
            deep_doi       = req.deep_doi,
            crossref_email = req.crossref_email,
        )
        
        # Add a note in the response if dry_run was auto-enabled
        if use_dry_run and not parser_available:
            if "summary" not in result:
                result["summary"] = {}
            result["summary"]["_note"] = (
                "Extraction engine not available. Running in dry_run mode: "
                "style classification and checks performed on raw text only (no field parsing)."
            )
        
    except ValueError as exc:
        # e.g. empty entries list (double-checked above, but kept for safety)
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        # Extraction engine not reachable and dry_run is False
        raise HTTPException(
            status_code=503, 
            detail=f"Field extraction not available: {str(exc)}. "
                   "Try setting dry_run=true to continue without field extraction."
        )

    return result


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("API_PORT", 8000))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
