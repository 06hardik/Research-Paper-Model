FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY citation_classifier.py  .
COPY reference_parser.py     .
COPY pipeline.py             .
COPY api.py                  .
COPY checks/                 ./checks/

# Create a directory for user-mounted input/output data
RUN mkdir /data

# PYTHONUTF8=1 avoids cp1252 UnicodeEncodeError on Windows report symbols
ENV PYTHONUTF8=1

# Expose the API port
EXPOSE 8000

# Start the FastAPI service via uvicorn
# Override CMD to run pipeline.py directly for one-off CLI use:
#   docker run --rm <image> python pipeline.py --help
ENTRYPOINT ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
