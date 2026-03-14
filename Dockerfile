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

# Copy entrypoint script
COPY render-entrypoint.sh    .
RUN chmod +x render-entrypoint.sh

# Create a directory for user-mounted input/output data
RUN mkdir /data

# PYTHONUTF8=1 avoids cp1252 UnicodeEncodeError on Windows report symbols
ENV PYTHONUTF8=1

# Set default values for Render environment
ENV PARSER_URL=http://localhost:8070/api/processCitation
ENV API_PORT=8000

# Expose the API port
EXPOSE 8000

# Use the entrypoint script to start the API
ENTRYPOINT ["./render-entrypoint.sh"]
