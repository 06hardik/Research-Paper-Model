# Reference Section Quality API (Docker Compose)

This service validates reference lists using five checks and exposes the pipeline through FastAPI.
It is configured to run directly with:

```bash
docker compose up -d --build
```

## What the service does

Given citation entries, it runs:

1. Ordering check
2. DOI check
3. Journal casing check
4. Completeness and formatting check
5. Style conformity check

Main endpoints:

- GET /health
- POST /analyze
- GET /docs
- GET /redoc

## Required files

Make sure these exist in REFRENCE-SECTION:

- compose.yml
- Dockerfile
- .env

## 1. Create .env

You said you will create it yourself. Use this minimum template:

```env
PARSER_URL=https://tmkc-100bar-extraction-engine.hf.space/api/processCitation
API_PORT=8000
UVICORN_WORKERS=1
PYTHONUTF8=1
```

Notes:

- PARSER_URL is required for normal /analyze requests.
- API_PORT defaults to 8000 if not set.
- UVICORN_WORKERS defaults to 1 if not set.

## 2. Start service

From REFRENCE-SECTION directory:

```bash
docker compose up -d --build
```

## 3. Verify service

```bash
curl "http://localhost:${API_PORT:-8000}/health"
```

Expected shape:

```json
{
  "status": "ok",
  "parser_configured": true,
  "parser_reachable": true,
  "parser_url": "https://.../api/processCitation"
}
```

Docs:

- <http://localhost:8000/docs> (replace 8000 with your API_PORT if changed)
- <http://localhost:8000/redoc> (replace 8000 with your API_PORT if changed)

## 4. Test analyze API

```bash
curl -X POST "http://localhost:${API_PORT:-8000}/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [
      {
        "id": "ref_001",
        "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52.",
        "metadata": {}
      }
    ],
    "dry_run": false,
    "deep_doi": false,
    "crossref_email": null
  }'
```

## Request format

```json
{
  "entries": [
    {
      "id": "ref_001",
      "raw_text": "...reference string...",
      "metadata": {}
    }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": "optional@example.com"
}
```

Rules:

- entries must be a non-empty array
- raw_text is required for each entry
- id is optional (auto-generated if omitted)
- set dry_run=true if parser backend is temporarily unavailable

## Compose operations

Start or rebuild:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

Restart:

```bash
docker compose restart
```

Stop services:

```bash
docker compose stop
```

Remove services and network:

```bash
docker compose down
```

## Troubleshooting

1. Health shows parser_configured false
   PARSER_URL is missing in .env. Add it, then run docker compose up -d.

2. Analyze returns parser unreachable
   Server cannot reach PARSER_URL. Check firewall, DNS, and outbound network access.

3. Port conflict on startup
   Change API_PORT in .env, then run docker compose up -d.

4. Need quick check without parser backend
   Send requests with dry_run=true.

## Notes

- Container runs as non-root user.
- Healthcheck is built into the image and hits /health.
