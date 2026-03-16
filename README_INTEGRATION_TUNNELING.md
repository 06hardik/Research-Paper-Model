# Reference API Integration Guide (Render API + Local Extraction Engine via Tunnel)

This guide is for engineers integrating with:

- API base URL: `https://reference-api.onrender.com`
- Local extraction engine: Docker container running on developer machine
- Public bridge: Cloudflare Tunnel (or ngrok) so Render can reach local extraction engine

Use this when the API is hosted remotely (Render) but extraction runs locally.

## 1. Architecture

Runtime flow:

1. Client sends `POST /analyze` to Render API.
2. Render API calls extraction endpoint from `PARSER_URL`.
3. `PARSER_URL` points to public tunnel URL.
4. Tunnel forwards request to local Docker extraction engine (`localhost:8070`).
5. Extraction returns parsed data back to Render API.

Important: `localhost` in Render means the Render container itself, not your laptop.

## 2. One-Time Local Setup

### 2.1 Start extraction engine

From `REFRENCE-SECTION`:

```powershell
cd D:\RESEARCH-PROJECT\REFRENCE-SECTION
docker compose up -d extraction-engine
```

Verify container and port:

```powershell
docker compose ps
```

Expected: extraction service shows `0.0.0.0:8070->8070/tcp` and healthy.

Verify local endpoint:

```powershell
curl.exe http://localhost:8070/api/isalive
```

Expected response: `true`

### 2.2 Start tunnel (Cloudflare recommended)

Install once (Windows):

```powershell
winget install Cloudflare.cloudflared
```

Run tunnel:

```powershell
cloudflared tunnel --url http://localhost:8070
```

Copy generated public URL, for example:

`https://situations-single-suitable-acquisition.trycloudflare.com`

Keep this terminal running.

## 3. Render Configuration

In Render service settings for `reference-api`:

- Add/update env var:
  - `PARSER_URL=https://<your-tunnel-domain>/api/processCitation`

Example:

- `PARSER_URL=https://situations-single-suitable-acquisition.trycloudflare.com/api/processCitation`

Then redeploy the Render API service.

## 4. Verify End-to-End Health

### 4.1 Health endpoint

```bash
curl https://reference-api.onrender.com/health
```

Expected shape:

```json
{
  "status": "ok",
  "parser_reachable": true,
  "parser_url": "https://<your-tunnel-domain>/api/processCitation"
}
```

`parser_reachable` must be `true`.

## 5. API Contract

## 5.1 Endpoint

- Method: `POST`
- URL: `https://reference-api.onrender.com/analyze`
- Content-Type: `application/json`

## 5.2 Request JSON

```json
{
  "entries": [
    {
      "id": "ref_001",
      "raw_text": "J. Smith, \"Deep learning for NLP,\" IEEE Trans. Neural Netw., vol. 31, no. 2, pp. 45-52, 2020.",
      "metadata": {
        "ocr_confidence": 0.97,
        "source": "paper_123"
      }
    },
    {
      "id": "ref_002",
      "raw_text": "A. Jones. Attention mechanisms. 2019.",
      "metadata": {}
    }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": null
}
```

Field notes:

- `entries` required, non-empty array.
- `id` optional, auto-generated if omitted.
- `raw_text` required citation string.
- `metadata` optional pass-through object.
- `dry_run=true` skips extraction engine call.
- `deep_doi=true` enables CrossRef DOI lookups.
- `crossref_email` recommended when `deep_doi=true`.

## 5.3 Success response JSON (shape)

```json
{
  "generated_at": "2026-03-16T12:00:00.000000Z",
  "summary": {
    "total": 2,
    "style": "IEEE",
    "style_confidence": "HIGH",
    "checks_passed": ["ordering"],
    "checks_failed": ["doi", "completeness"],
    "total_issues": 3,
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
          "IEEE": 0.98
        }
      },
      "issues": []
    }
  ]
}
```

## 5.4 Error responses

- `422`: invalid request, usually empty or malformed `entries`.
- `503`: extraction engine not reachable from Render API.

## 5.5 cURL example

```bash
curl -X POST "https://reference-api.onrender.com/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [
      {
        "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52."
      }
    ],
    "dry_run": false,
    "deep_doi": false,
    "crossref_email": null
  }'
```

## 6. Troubleshooting

## 6.1 `/health` shows old localhost URL

Cause: `PARSER_URL` not set or not picked up in Render runtime.

Fix:

1. Confirm env key is exactly `PARSER_URL`.
2. Confirm value includes `/api/processCitation`.
3. Save and redeploy the correct Render service.
4. Re-check `/health`.

## 6.2 `parser_reachable=false`

Likely causes:

- Tunnel process stopped.
- Local Docker extractor stopped/unhealthy.
- Tunnel URL changed after restart.
- Firewall/network blocked.

Fix:

1. Check local extractor:
   - `docker compose ps`
   - `curl.exe http://localhost:8070/api/isalive`
2. Restart tunnel and use new URL in Render env var.
3. Redeploy Render API.

## 6.3 PowerShell `curl` confusion

On Windows PowerShell, `curl` may map to `Invoke-WebRequest`.
Use `curl.exe` for native curl behavior.

## 7. Operational Notes

- This tunnel setup is intended for development/testing.
- Public tunnel URL may rotate after restart.
- For stable production, deploy extraction engine as its own managed service and point `PARSER_URL` to that fixed internal/public endpoint.

## 8. Quick Handoff Checklist

1. Local extractor running and healthy.
2. Tunnel running and URL copied.
3. Render `PARSER_URL` updated to `<tunnel>/api/processCitation`.
4. Render API redeployed.
5. `GET /health` shows `parser_reachable=true` and correct `parser_url`.
6. `POST /analyze` tested with sample payload.
