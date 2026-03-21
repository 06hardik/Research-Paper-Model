# Reference Section Quality API

Production-ready HTTP API for validating academic reference lists.

This service is already hosted and reachable from the main codebase, so integration requires only HTTP calls.

- API base URL: `https://reference-api.onrender.com`
- Extraction engine is hosted remotely (Hugging Face)
- No local Docker, ngrok, or cloudflared is required for consumers

The API is stateless in hosted mode:

- It does not write request outputs to local files/directories
- It only returns the final JSON response to the caller

## What This API Does

Given a list of raw reference strings, the API runs a full pipeline and returns:

1. Style detection (IEEE, APA, MLA, Harvard, Vancouver)
2. Ordering check
3. DOI check
4. Journal casing check
5. Completeness and formatting checks
6. Style conformity check

## Integration Quick Start

### 1. Health Check

```bash
curl https://reference-api.onrender.com/health
```

Expected response shape:

```json
{
  "status": "ok",
  "parser_configured": true,
  "parser_reachable": true,
  "parser_url": "https://.../api/processCitation"
}
```

### 2. Analyze Endpoint

- Method: `POST`
- URL: `https://reference-api.onrender.com/analyze`
- Content-Type: `application/json`

Minimal request:

```json
{
  "entries": [
    { "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52." }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": null
}
```

## Request Contract

```json
{
  "entries": [
    {
      "id": "ref_001",
      "raw_text": "...reference string...",
      "metadata": {
        "source": "paper_123",
        "ocr_confidence": 0.97
      }
    }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": "optional@example.com"
}
```

Field rules:

- `entries` required, non-empty array.
- `raw_text` required per entry.
- `id` optional. Auto-assigned if omitted.
- `metadata` optional pass-through object.
- `dry_run=true` skips extraction step.
- `deep_doi=true` enables CrossRef confirmation (slower).
- `crossref_email` recommended when `deep_doi=true`.

## Response Contract

Top-level response:

```json
{
  "generated_at": "2026-03-21T10:00:00.000000Z",
  "processing_status": "ok",
  "parser_summary": {
    "total": 2,
    "parsed_ok": 2,
    "parsed_failed": 0,
    "success_rate": 1.0,
    "suggested_http_status": 200
  },
  "summary": {
    "total": 2,
    "style": "IEEE",
    "style_confidence": "HIGH",
    "checks_passed": ["ordering", "journal_casing"],
    "checks_failed": ["doi", "completeness", "style_conformity"],
    "total_issues": 4,
    "parsed_ok": 2,
    "parsed_failed": 0
  },
  "list_level_issues": [],
  "entries": [
    {
      "id": "ref_001",
      "raw_text": "...",
      "metadata": {},
      "parsed": {
        "parser_status": "ok"
      },
      "style": {
        "predicted": "IEEE",
        "confidence": "HIGH",
        "scores": {
          "IEEE": 0.98,
          "APA": 0.01
        }
      },
      "issues": [
        {
          "check": "doi",
          "field": "doi",
          "issue_type": "missing",
          "detail": "DOI not found in reference text.",
          "found": null,
          "suggestion": "Add DOI if available."
        }
      ]
    }
  ]
}
```

`processing_status` meanings:

- `ok`: all entries parsed successfully
- `partial`: some entries parsed, some failed (207-style metadata)
- `failed`: no entries parsed successfully

Response headers:

- `X-Processing-Status`: `ok|partial|failed`
- `X-Parser-Success-Rate`: `0.0` to `1.0`

## Error Codes

- `200`: Success
- `422`: Invalid input (for example empty `entries`)
- `503`: Parser/extraction backend unreachable

Note: partial parser outcomes are returned as HTTP `200` with `processing_status="partial"`
and `parser_summary.suggested_http_status=207` for compatibility with existing clients.

## Copy-Paste Client Examples

### JavaScript (Node / Next.js / Express)

```javascript
export async function analyzeReferences(referenceStrings) {
  const payload = {
    entries: referenceStrings.map((text, i) => ({
      id: `ref_${String(i + 1).padStart(3, "0")}`,
      raw_text: text,
      metadata: {}
    })),
    dry_run: false,
    deep_doi: false,
    crossref_email: null
  };

  const res = await fetch("https://reference-api.onrender.com/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const errBody = await res.text();
    throw new Error(`Reference API error ${res.status}: ${errBody}`);
  }

  return res.json();
}
```

### Python

```python
import requests


def analyze_references(reference_strings):
    payload = {
        "entries": [
            {
                "id": f"ref_{i+1:03d}",
                "raw_text": text,
                "metadata": {}
            }
            for i, text in enumerate(reference_strings)
        ],
        "dry_run": False,
        "deep_doi": False,
        "crossref_email": None,
    }

    r = requests.post(
        "https://reference-api.onrender.com/analyze",
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()
```

## Suggested Integration Pattern in Main Codebase

1. Collect extracted reference strings from manuscript pipeline.
2. Send them as `entries[].raw_text` to `/analyze`.
3. Persist API response as-is for auditability.
4. Use `summary` for top-level UI badges and pass/fail indicators.
5. Use each entry's `issues` for row-level error rendering.
6. Use `list_level_issues` for global ordering-level warnings.

## Optional Modes

- `dry_run=true`: Use when extraction backend is down but style/check logic is still needed.
- `deep_doi=true`: Higher accuracy DOI validation with extra latency.

## Performance Notes

- Keep batch size practical (for example 25 to 200 references/request depending latency budget).
- Use client timeout >= 120 seconds for large batches.
- Retry transient `503`/`5xx` with exponential backoff.

## Data Handling Notes

- Do not send secrets in `metadata`.
- Prefer sending only citation text and non-sensitive identifiers.

## API Documentation

- Swagger UI: `https://reference-api.onrender.com/docs`
- ReDoc: `https://reference-api.onrender.com/redoc`

## Repository Structure (for maintainers)

```text
REFRENCE-SECTION/
  api.py                        # FastAPI service (/health, /analyze)
  pipeline.py                   # End-to-end orchestration
  reference_parser.py           # Extraction engine calls + parsing
  citation_classifier.py        # Citation style classifier
  checks/
    check_ordering.py
    check_doi.py
    check_journal_casing.py
    check_completeness.py
    check_style_conformity.py
```

## Maintainer Notes

- Public integration contract is the HTTP API above.
- Internal implementation may evolve without requiring caller changes as long as endpoint contract remains stable.
- If base URL changes, update only the integration constant in the consumer app.
