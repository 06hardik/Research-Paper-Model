# Deployment Guide (Render + Local Extraction Engine)

This guide is for the current production setup:
- API deployed on Render (public)
- Extraction engine running locally for demo parsing

## 1. Public API on Render

Live URL:
`https://reference-quality-api.onrender.com`

Verify:
- `GET /health`
- `GET /docs`

## 2. Start extraction engine locally

```bash
docker run --rm -p 8070:8070 ghcr.io/06hardik/extraction-engine:1.0
```

Check liveness:
`http://localhost:8070/api/isalive`

## 3. Expose local parser with ngrok

```bash
ngrok http 8070
```

Copy HTTPS forwarding URL, for example:
`https://abc123.ngrok-free.app`

## 4. Update Render environment variable

In Render service `reference-quality-api` set:

`PARSER_URL=https://abc123.ngrok-free.app/api/processCitation`

Save and redeploy.

## 5. Validate

Call:
`https://reference-quality-api.onrender.com/health`

Expected:

```json
{
  "status": "ok",
  "parser_reachable": true
}
```

## 6. API call example

```bash
curl -X POST https://reference-quality-api.onrender.com/analyze \
  -H "Content-Type: application/json" \
  -d '{"entries":[{"raw_text":"Smith J. Title. Nature. 2020;5(3):45-52."}]}'
```

## 7. Fallback behavior

If parser is unreachable, API auto-runs in `dry_run` mode and still returns analysis.
