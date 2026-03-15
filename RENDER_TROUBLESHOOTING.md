# Render Troubleshooting

## 1) `/health` shows `parser_reachable: false`

Cause:
- `PARSER_URL` points to `localhost` or an unreachable URL from Render.

Fix:
1. Start extraction engine locally on port 8070.
2. Expose with ngrok: `ngrok http 8070`
3. Set Render env var:
   `PARSER_URL=https://<ngrok-url>/api/processCitation`
4. Redeploy API.

## 2) `/analyze` still works but output is less detailed

Cause:
- API is in auto `dry_run` fallback.

Behavior:
- style and checks run on raw text
- no parsed field extraction

## 3) ngrok URL changed and parser stopped working

Cause:
- free ngrok URLs rotate on restart.

Fix:
- update `PARSER_URL` in Render with the new URL
- redeploy service

## 4) Render service is healthy but parsing times out

Checks:
- local extraction container is running
- local endpoint `http://localhost:8070/api/isalive` returns true
- ngrok forwarding is active
- `PARSER_URL` uses `https://.../api/processCitation`

## 5) Need stable production parser

Current setup is for demo.
For production, deploy extraction engine on a host with enough RAM and stable public/internal URL, then point `PARSER_URL` there.
