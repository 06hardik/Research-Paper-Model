FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PYTHONUTF8=1 \
	API_PORT=8000 \
	UVICORN_WORKERS=1

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
	&& pip install --no-cache-dir -r requirements.txt

# Copy source code needed by the API entrypoint.
COPY api.py .
COPY pipeline.py .
COPY citation_classifier.py .
COPY reference_parser.py .
COPY env_loader.py .
COPY checks ./checks

# Run container as non-root user for safer deployment.
RUN adduser --disabled-password --gecos "" appuser \
	&& chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
	CMD python -c "import os,urllib.request; port=os.getenv('API_PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=4)" || exit 1

# Default startup used by docker compose.
# You can override this command in compose.yml for one-off tasks.
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${API_PORT:-8000} --workers ${UVICORN_WORKERS:-1}"]
