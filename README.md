# Reference Section Quality API

This project provides citation-quality analysis as an API service.

Public API (Render): `https://reference-quality-api.onrender.com`

The service analyzes academic references and returns structured quality issues across 5 checks:
1. Ordering
2. DOI presence
3. Journal casing
4. Field completeness and formatting
5. Style conformity

## Current architecture

- `api.py` (FastAPI) is deployed publicly on Render.
- Extraction engine (GROBID parser) is optional at runtime.
- If parser is unavailable, API auto-falls back to `dry_run` mode.

Flow:

`caller -> /analyze -> (parser if available) -> checks -> JSON report`

## API endpoints

- `GET /health`
- `POST /analyze`
- `GET /docs`
- `GET /redoc`

Example health response:

```json
{
  "status": "ok",
  "parser_reachable": false,
  "parser_url": "http://localhost:8070/api/processCitation"
}
```

## Request format (`POST /analyze`)

```json
{
  "entries": [
    {
      "id": "ref_001",
      "raw_text": "Smith J. Title. Nature. 2020;5(3):45-52.",
      "metadata": {}
    }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": null
}
```

## Local development

### Run full stack locally (API + extraction engine)

```bash
docker compose up -d
```

Then open:
- `http://localhost:8000/docs`
- `http://localhost:8000/health`

### Run API without parser

If parser is down, `POST /analyze` still works in `dry_run` mode.

## Render deployment notes

- Public API is hosted on Render.
- Extraction engine is currently not deployed on Render.
- For demos requiring parsing, expose local extraction engine with ngrok and set `PARSER_URL` in Render.

See:
- `README_DEPLOYMENT.md`
- `README_LOCAL_DEMO_INTEGRATION.md`
- `RENDER_QUICK_START.md`
- `RENDER_TROUBLESHOOTING.md`

## Project structure

- `api.py` - FastAPI service
- `pipeline.py` - core pipeline orchestration
- `reference_parser.py` - extraction parser client + parsing logic
- `citation_classifier.py` - style classifier
- `checks/` - quality checks
- `documents/QUALITY_CHECKS_REPORT.md` - technical report

## Status

- API is live on Render
- Parser fallback is implemented and working
- Endpoints are stable for integration by external projects
