#!/bin/bash
# render-entrypoint.sh
# Entry point for Render deployment
# Starts the FastAPI app with proper environment configuration

set -e

# On Render, we don't have the extraction engine, so we:
# 1. Set PARSER_URL to a dummy value (won't be used in dry-run mode)
# 2. Modify api.py to default dry_run to true

echo "🚀 Starting Reference Section Quality API..."
echo "Environment:"
echo "  PARSER_URL: ${PARSER_URL:-http://localhost:8070/api/processCitation}"
echo "  API_PORT: ${API_PORT:-8000}"

# Start the API with uvicorn
exec uvicorn api:app --host 0.0.0.0 --port ${API_PORT:-8000}
