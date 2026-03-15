# Render Quick Start

## Goal
Use the public API quickly, with optional parser support from local machine.

## Public endpoints
- Base: `https://reference-quality-api.onrender.com`
- Health: `https://reference-quality-api.onrender.com/health`
- Docs: `https://reference-quality-api.onrender.com/docs`
- Analyze: `POST https://reference-quality-api.onrender.com/analyze`

## Fast test

```bash
curl -X POST https://reference-quality-api.onrender.com/analyze \
  -H "Content-Type: application/json" \
  -d '{"entries":[{"raw_text":"Smith J. Title. Nature. 2020;5(3):45-52."}]}'
```

## Enable parsing for demo (optional)
1. Run local extraction engine on `localhost:8070`
2. Expose via `ngrok http 8070`
3. Set Render env var:
`PARSER_URL=https://<ngrok-url>/api/processCitation`
4. Redeploy API service

## If parser is not connected
No blocker. API falls back to `dry_run` automatically.
