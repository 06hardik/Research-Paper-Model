# Local Demo Integration Guide (Extraction Engine + API)

This guide is for another developer who needs to run the extraction engine locally and then call the Reference Quality API.

## Goal

- Start extraction engine locally on port `8070`
- Verify it is healthy
- Connect it to the API via `PARSER_URL`
- Call `POST /analyze` from your integration project

Public API base URL:
`https://reference-quality-api.onrender.com`

## Prerequisites

- Docker Desktop installed and running
- GitHub account with access to `ghcr.io/06hardik/extraction-engine:1.0`
- Terminal (PowerShell / bash)
- Optional: ngrok (needed only when API is on Render and parser runs on your local machine)

## 1) Authenticate to GitHub Container Registry (GHCR)

Generate a GitHub token with `read:packages` scope, then login:

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

When prompted for password, paste the token.

## 2) Pull and run extraction engine locally

```bash
docker pull ghcr.io/06hardik/extraction-engine:1.0
docker run --rm -p 8070:8070 --name extraction-engine ghcr.io/06hardik/extraction-engine:1.0
```

Keep this terminal open while using the demo.

## 3) Verify extraction engine health

Open in browser or call with curl:

- `http://localhost:8070/api/isalive`

Expected response contains `true`.

## 4) Connect local parser to API

Choose one of the following setups.

### Option A: API running locally (recommended for full local demo)

From this repository root:

```bash
docker compose up -d api
```

Local API URL:
- `http://localhost:8000`

Health check:
- `http://localhost:8000/health`

Expected:

```json
{
  "status": "ok",
  "parser_reachable": true
}
```

### Option B: API on Render + parser on your machine

Render cannot reach your localhost directly. Expose local parser using ngrok:

```bash
ngrok http 8070
```

Copy HTTPS forwarding URL, for example:
- `https://abc123.ngrok-free.app`

In Render service (`reference-quality-api`) set environment variable:

`PARSER_URL=https://abc123.ngrok-free.app/api/processCitation`

Redeploy service, then verify:
- `https://reference-quality-api.onrender.com/health`

Expected:

```json
{
  "status": "ok",
  "parser_reachable": true
}
```

## 5) Call the API

### cURL example

Local API:

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"entries":[{"id":"ref_001","raw_text":"J. Smith, \"Deep learning\", IEEE Trans. Neural Netw., vol. 31, no. 2, pp. 45-52, 2020."}]}'
```

Render API:

```bash
curl -X POST https://reference-quality-api.onrender.com/analyze \
  -H "Content-Type: application/json" \
  -d '{"entries":[{"id":"ref_001","raw_text":"J. Smith, \"Deep learning\", IEEE Trans. Neural Netw., vol. 31, no. 2, pp. 45-52, 2020."}]}'
```

### JavaScript example (integration project)

```javascript
const payload = {
  entries: [
    {
      id: "ref_001",
      raw_text: "J. Smith, \"Deep learning\", IEEE Trans. Neural Netw., vol. 31, no. 2, pp. 45-52, 2020.",
      metadata: { source: "demo" }
    }
  ],
  dry_run: false,
  deep_doi: false,
  crossref_email: null
};

const res = await fetch("https://reference-quality-api.onrender.com/analyze", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});

const data = await res.json();
console.log(data.summary, data.entries?.[0]?.issues);
```

## Request schema used by integrators

```json
{
  "entries": [
    {
      "id": "string (optional)",
      "raw_text": "string (required)",
      "metadata": {}
    }
  ],
  "dry_run": false,
  "deep_doi": false,
  "crossref_email": null
}
```

## Troubleshooting

- `parser_reachable: false`
  - Check extraction container is running
  - Check `http://localhost:8070/api/isalive`
  - If using Render, verify `PARSER_URL` uses ngrok HTTPS URL with `/api/processCitation`

- `502/503` from API
  - API is restarting or parser URL is invalid
  - Recheck Render env vars and redeploy

- ngrok URL changed
  - Update `PARSER_URL` on Render and redeploy again

## Demo teardown

Stop local API and parser:

```bash
docker compose down
```

Or stop only parser container started with `docker run`:

```bash
docker stop extraction-engine
```
