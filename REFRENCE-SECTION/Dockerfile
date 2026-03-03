FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY citation_classifier.py  .
COPY reference_parser.py     .
COPY pipeline.py             .
COPY checks/                 ./checks/

# Create a directory for user-mounted input/output data
RUN mkdir /data

# PYTHONUTF8=1 avoids cp1252 UnicodeEncodeError on Windows report symbols
ENV PYTHONUTF8=1

ENTRYPOINT ["python", "pipeline.py"]
CMD ["--help"]
