# Reference Section Quality Pipeline

A pipeline for validating and analysing academic reference lists. Given a JSON array of raw citation strings, it extracts structured bibliographic fields, auto-detects the citation style, and runs five quality checks — returning both a machine-readable JSON report and a human-readable text report.

**Supported citation styles:** IEEE · APA · MLA · Harvard · Vancouver

---

## Table of Contents

1. [How It Works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start — Docker (Recommended)](#3-quick-start--docker-recommended)
4. [Input Format](#4-input-format)
5. [Running the Pipeline](#5-running-the-pipeline)
6. [All CLI Options](#6-all-cli-options)
7. [Output Format](#7-output-format)
8. [Quality Checks](#8-quality-checks)
9. [Supported Citation Styles](#9-supported-citation-styles)
10. [Python API Integration](#10-python-api-integration)
11. [Project Structure](#11-project-structure)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. How It Works

```
  Your input.json
       |
       v
  +-------------------------------------------------------------+
  |  Step 1 - Field Extraction                                  |
  |  Each raw citation string is sent to the extraction service |
  |  which returns structured XML (authors, title, year, DOI)   |
  +------------------------+------------------------------------+
                           |
                           v
  +-------------------------------------------------------------+
  |  Step 2 - Style Classification                              |
  |  The rule-based classifier assigns each entry a style       |
  |  (IEEE / APA / MLA / Harvard / Vancouver) with a confidence |
  |  score. The dominant style for the whole list is determined.|
  +------------------------+------------------------------------+
                           |
                           v
  +-------------------------------------------------------------+
  |  Step 3 - Quality Checks (x5)                               |
  |  1. Reference ordering     4. Field completeness            |
  |  2. DOI presence           5. Style conformity              |
  |  3. Journal title casing                                    |
  +------------------------+------------------------------------+
                           |
                           v
              results.json  +  report.txt
```

---

## 2. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| [Docker Desktop](https://docs.docker.com/get-docker/) | any recent | Required for the extraction service |
| Python | >= 3.9 | Only needed if running outside Docker |
| `requests` | >= 2.31 | Auto-installed via `requirements.txt` |
| `tqdm` | >= 4.66 | Auto-installed via `requirements.txt` |
| `lxml` | >= 5.1 | Auto-installed via `requirements.txt` |

> **Windows users:** Python commands require `$env:PYTHONUTF8=1` prefix to avoid encoding errors. See [Troubleshooting](#12-troubleshooting). This is not needed when using Docker.

---

## 3. Quick Start — Docker (Recommended)

This is the easiest way to get started. Everything runs inside Docker — no Python setup required.

### Step 1 — Log in to the container registry and create your `.env` file

The extraction service image is hosted on a private GitHub Container Registry.
You need a GitHub account and a Personal Access Token with `read:packages` scope.

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
# Enter your GitHub Personal Access Token when prompted for a password
```

Then copy `.env.example` to `.env` — the correct image name is already filled in:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Your `.env` file should look like this:

```env
EXTRACTOR_IMAGE=ghcr.io/unknown-flame/extraction-engine:1.0
```

> Do not change the image name.

### Step 2 — Pull and build

Open a terminal in the `REFRENCE-SECTION` folder and run:

```bash
docker compose pull
docker compose build
```

This downloads the extraction service image and builds the pipeline container. Only needs to be done once.

### Step 3 — Start the extraction service

```bash
docker compose up -d extraction-engine
```

The service takes approximately 30–45 seconds to become ready on first start. Verify it is healthy:

```bash
docker compose ps
# extraction-engine should show:  Status = running, Health = healthy
```

### Step 4 — Place your input file

Copy your references JSON into the `data/` folder inside the project:

```
REFRENCE-SECTION/
└── data/
    └── your_references.json    <-- place it here
```

### Step 5 — Run the pipeline

```bash
docker compose run --rm pipeline \
  /data/your_references.json \
  --output /data/results.json \
  --report /data/report.txt
```

Results are written back to `data/` on your local machine immediately after the command finishes.

```
data/
├── results.json    <-- full structured JSON report
└── report.txt      <-- human-readable quality report
```

### Step 6 — Stop everything when done

```bash
docker compose down
```

---

## 4. Input Format

The pipeline accepts a JSON file containing an array of citation objects.

### Minimal — raw text only

Both `"raw_text"` and `"text"` are accepted as the key name.

```json
[
  {
    "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52. https://doi.org/10.1038/s00001"
  },
  {
    "raw_text": "Halpern SD, Ubel PA, Caplan AL. Solid-organ transplantation in HIV-infected patients. N Engl J Med. 2002;347(4):284-7."
  }
]
```

### Full — with optional fields

```json
[
  {
    "id":       "ref_001",
    "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52.",
    "metadata": {
      "ocr_confidence": 0.95,
      "source_page": 12
    }
  }
]
```

| Field | Required | Description |
|---|---|---|
| `raw_text` or `text` | **Yes** | The raw citation string |
| `id` | No | Unique identifier. Auto-assigned (`ref_001`, `ref_002`, ...) if omitted |
| `metadata` | No | Any extra key-value data. Passed through unchanged to the output |

---

## 5. Running the Pipeline

### Via Docker Compose (recommended)

The `.env` file and `docker-compose.yml` are pre-configured — no `--parser-url` flag needed.

**Standard run:**

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --output /data/results.json \
  --report /data/report.txt
```

**With CrossRef DOI verification:**

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --output /data/results.json \
  --report /data/report.txt \
  --deep-doi \
  --crossref-email your@email.com
```

**Limit to first N entries (for testing):**

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --limit 10 \
  --output /data/results.json \
  --report /data/report.txt
```

**Dry-run — skip extraction entirely:**

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --dry-run \
  --output /data/results.json \
  --report /data/report.txt
```

---

### Via Python Directly

Use this if you prefer to run outside Docker. A running extraction service must be reachable.

**One-time setup:**

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

**Run:**

```bash
# Windows — set UTF-8 first
$env:PYTHONUTF8=1; python pipeline.py input.json --output results.json --report report.txt

# macOS / Linux
python pipeline.py input.json --output results.json --report report.txt
```

Point at a remote extraction service with `--parser-url`:

```bash
python pipeline.py input.json \
  --parser-url http://YOUR-SERVER:8070 \
  --output results.json \
  --report report.txt
```

---

### Dry-Run Mode

Skips field extraction. Classifies and checks using raw text only. No extraction service needed.

```bash
python pipeline.py input.json --dry-run --output results.json --report report.txt
```

Useful when:
- Testing a new input file format
- Docker is not available
- Only style classification and ordering checks are needed

---

## 6. All CLI Options

| Option | Default | Description |
|---|---|---|
| `input` | *(required)* | Path to the input JSON file |
| `--output FILE` | *(none)* | Write full JSON report to this file |
| `--report FILE` | *(none)* | Write human-readable text report to this file |
| `--parser-url URL` | `http://localhost:8070` | Extraction service URL (auto-set in Docker) |
| `--workers N` | `8` | Concurrent extraction threads |
| `--timeout N` | `15` | Per-request timeout in seconds |
| `--dry-run` | off | Skip field extraction; classify from raw text only |
| `--deep-doi` | off | Query CrossRef API to confirm missing DOIs |
| `--crossref-email EMAIL` | *(none)* | Email for CrossRef polite-pool (higher rate limit) |
| `--quiet` | off | Suppress progress output; print errors only |
| `--verbose` | off | Enable debug-level logging |
| `--limit N` | *(none)* | Process only the first N entries |

---

## 7. Output Format

### JSON Output (`--output`)

```json
{
  "generated_at": "2026-03-04T10:22:05Z",
  "summary": {
    "total": 10,
    "style": "APA",
    "style_confidence": "HIGH",
    "checks_passed": ["ordering", "doi", "journal_casing", "style_conformity"],
    "checks_failed": ["completeness"],
    "total_issues": 3,
    "parsed_ok": 10,
    "parsed_failed": 0
  },
  "list_level_issues": [
    {
      "check":    "ordering",
      "ref_id":   "ref_007",
      "position": 7,
      "detail":   "Entry out of alphabetical order",
      "expected": "Taylor",
      "found":    "Adams"
    }
  ],
  "entries": [
    {
      "id":       "ref_001",
      "raw_text": "Smith, J. A. (2020). Deep learning fundamentals. Nature, 5(3), 45-52.",
      "metadata": {},
      "parsed": {
        "title":           "Deep learning fundamentals",
        "authors":         ["J. A. Smith"],
        "container_title": "Nature",
        "pub_date":        "2020",
        "volume":          "5",
        "issue":           "3",
        "pages":           "45-52",
        "doi":             null,
        "url":             null,
        "parser_status":   "ok",
        "fixes_applied":   []
      },
      "style": {
        "predicted":  "APA",
        "confidence": "HIGH",
        "scores": { "APA": 13.0, "Harvard": 2.0, "MLA": 0.0, "IEEE": 0.0, "Vancouver": 0.0 }
      },
      "issues": [
        {
          "check":      "completeness",
          "field":      "doi",
          "issue_type": "missing",
          "detail":     "DOI not present in citation",
          "found":      null,
          "suggestion": "Add a DOI if the work has been registered"
        }
      ]
    }
  ]
}
```

#### Summary fields

| Field | Description |
|---|---|
| `style` | Dominant citation style detected across the whole list |
| `style_confidence` | `HIGH` / `MEDIUM` / `LOW` |
| `checks_passed` | Checks that found no issues |
| `checks_failed` | Checks that found at least one issue |
| `list_level_issues` | Issues scoped to the whole list (e.g. ordering violations) |
| `entries[].parsed` | Structured fields extracted by the extraction service |
| `entries[].style` | Per-entry classification with scores |
| `entries[].issues` | Per-entry issues with field, type, detail, and fix suggestion |

#### Issue types

| `issue_type` | Meaning |
|---|---|
| `missing` | A required field is absent |
| `formatting` | A field is present but incorrectly formatted |
| `suspicious` | A field value looks unusual — advisory, not necessarily wrong |
| `inconsistent` | Casing or format differs from the rest of the list |
| `style_mismatch` | Entry appears to use a different style than the dominant one |

---

### Text Report (`--report`)

Human-readable, suitable for direct review or sharing.

```
========================================================================
  REFERENCE LIST QUALITY REPORT
========================================================================
  Generated  : 2026-03-04 10:22:05
  Entries    : 10  (parsed: 10)
  Style      : APA  [HIGH confidence]
  Issues     : 3 total
------------------------------------------------------------------------
  CHECK SUMMARY
------------------------------------------------------------------------
  v  PASS   1. Reference ordering
  v  PASS   2. DOI presence
  v  PASS   3. Journal title casing
  x  FAIL   4. Field completeness & formatting  (3 issues)
  v  PASS   5. Citation style conformity
------------------------------------------------------------------------
  FIELD & FORMATTING ISSUES
------------------------------------------------------------------------
  +- [ref_001]  (classified: APA / HIGH)
  |  Smith, J. A. (2020). Deep learning fundamentals. Nature...
  |  x MISSING       [doi]  DOI not present in citation
  |              Fix: Add a DOI if the work has been registered
  +------------------------------------------------------------------
```

---

## 8. Quality Checks

### Check 1 — Reference Ordering

Verifies entries are in the correct sequence for the detected style.

| Style | Expected order |
|---|---|
| IEEE | Numeric ascending: 1, 2, 3, ... |
| Vancouver | Numeric ascending: 1, 2, 3, ... |
| APA | Alphabetical by first author surname |
| MLA | Alphabetical by first author surname |
| Harvard | Alphabetical by first author surname |

Ordering violations are reported in `list_level_issues` with the position, what was expected, and what was found.

### Check 2 — DOI Presence

Flags entries with no DOI in the citation text.

- **Default (no flag):** Advisory only. Entries without a DOI are flagged but no external call is made.
- **`--deep-doi`:** Queries CrossRef. If a DOI is found for the work, the issue is confirmed (`crossref_found`).
- **`--crossref-email`:** Provides a `mailto:` header for CrossRef's polite pool — higher request rate.

### Check 3 — Journal Title Casing

Enforces the casing convention for the detected style.

| Style | Convention | Example |
|---|---|---|
| APA | Title Case | *Journal of Applied Science* |
| MLA | Title Case | *Journal of Applied Science* |
| Harvard | Title Case | *Journal of Applied Science* |
| IEEE | Standard abbreviations | *IEEE Trans. Neural Netw.* |
| Vancouver | NLM abbreviations | *N Engl J Med* |

### Check 4 — Field Completeness & Formatting

Checks each parsed entry against required and recommended fields for its style. Reports:

- **Missing** fields — authors, year, title, journal, volume, issue, pages (per style requirements)
- **Formatting errors** — incorrect date format, malformed page range, wrong DOI format
- **Suspicious values** — title shorter than three words, year outside 1800–2030, empty author list

### Check 5 — Style Conformity

After the dominant style is determined, each individual entry is re-examined. Entries not matching the dominant style are flagged as `style_mismatch` with the detail of which style was detected and what was expected.

---

## 9. Supported Citation Styles

| Style | Author format | Year placement | Key signals |
|---|---|---|---|
| **IEEE** | `J. A. Smith` | Near end | `[1]` label at start; `doi: 10.xxxx` |
| **APA** | `Smith, J. A.` | `(2020).` immediately after author | `https://doi.org/10.xxxx`; `(pp. X–Y)` |
| **MLA** | `Smith, John` | Near end, after publisher | `vol. 5, no. 3`; `Accessed` date |
| **Harvard** | `Smith, J.` | `(2020)` after author, no trailing period | `Available at:`; `(Accessed DD Mon YYYY)` |
| **Vancouver** | `Smith JA` | `Year;vol(issue):pages` | `[Internet]`; `[cited 2020 May 3]`; NLM journal abbreviations |

---

## 10. Python API Integration

Import `run()` directly into your own application — no CLI required.

```python
from pipeline import run

entries = [
    {
        "id":       "ref_001",
        "raw_text": "Halpern SD, Ubel PA, Caplan AL. Solid-organ transplantation "
                    "in HIV-infected patients. N Engl J Med. 2002;347(4):284-7."
    },
    {
        "id":       "ref_002",
        "raw_text": "Rose ME, Huerbin MB, Melick J. Regulation of interstitial "
                    "excitatory amino acid concentrations. Brain Res. 2002;935(1-2):40-6."
    }
]

result = run(
    entries,
    parser_url = "http://localhost:8070",
    workers    = 4,
    dry_run    = False,
    deep_doi   = False,
)

# Top-level summary
print(result["summary"]["style"])            # "Vancouver"
print(result["summary"]["style_confidence"]) # "HIGH"
print(result["summary"]["checks_passed"])    # ["ordering", "doi", ...]
print(result["summary"]["total_issues"])     # 0

# Per-entry issues
for entry in result["entries"]:
    for issue in entry["issues"]:
        print(f"[{entry['id']}] [{issue['field']}] {issue['detail']}")
        if issue.get("suggestion"):
            print(f"  Fix: {issue['suggestion']}")
```

### `run()` parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entries` | `list[dict]` | *(required)* | List of entry dicts with `id`, `raw_text`, optional `metadata` |
| `parser_url` | `str` | env `PARSER_URL` or `http://localhost:8070/api/processCitation` | Extraction service endpoint |
| `workers` | `int` | `8` | Concurrent extraction threads |
| `timeout` | `int` | `15` | Per-request timeout in seconds |
| `dry_run` | `bool` | `False` | Skip extraction; classify from raw text only |
| `deep_doi` | `bool` | `False` | Query CrossRef for missing DOIs |
| `crossref_email` | `str` | `None` | Email for CrossRef polite-pool |

### Configuring the extraction endpoint via environment variable

```python
import os
os.environ["PARSER_URL"] = "http://your-extraction-service:8070/api/processCitation"

from pipeline import run   # PARSER_ENDPOINT picks up the env var automatically
```

This is the same mechanism Docker Compose uses internally to wire the two containers together.

---

## 11. Project Structure

```
REFRENCE-SECTION/
|
+-- pipeline.py                     Main entry point — orchestrates all steps
+-- citation_classifier.py          Rule-based 5-style classifier (runs standalone too)
+-- reference_parser.py             HTTP client, XML parser, and post-processing fixes
|
+-- Dockerfile                      Builds the pipeline Python container
+-- docker-compose.yml              Orchestrates extraction service + pipeline container
+-- .env                            Sets EXTRACTOR_IMAGE (provided by pipeline owner)
+-- .env.example                    Template — copy to .env and fill in the image name
+-- requirements.txt                Python dependencies
+-- README.md                       This file
|
+-- checks/
|   +-- __init__.py
|   +-- check_ordering.py           Check 1 — numeric / alphabetical ordering
|   +-- check_doi.py                Check 2 — DOI presence + optional CrossRef lookup
|   +-- check_journal_casing.py     Check 3 — journal title casing per style
|   +-- check_completeness.py       Check 4 — required fields + formatting validation
|   +-- check_style_conformity.py   Check 5 — per-entry style mismatch detection
|
+-- data/
|   +-- README.txt                  Put input files here; output is written here
|
+-- test/
    +-- input_test.json             Mixed multi-style test set
    +-- input.json                  Additional test entries
```

---

## 12. Troubleshooting

**Extraction service never becomes healthy**

```bash
docker compose logs extraction-engine
```

The JVM inside the container takes 30–45 seconds to start. If it keeps restarting, ensure
Docker Desktop has at least 4 GB of memory allocated (Settings → Resources → Memory).

---

**`RuntimeError: Field extraction model not reachable`**

The extraction service is not running or has not finished starting up.

```bash
docker compose up -d extraction-engine
docker compose ps   # wait until Health = healthy
```

Alternatively, use `--dry-run` to skip extraction entirely.

---

**`UnicodeEncodeError: charmap codec can't encode character`** (Windows only)

Your terminal is using cp1252 encoding. Prefix all Python commands with:

```powershell
$env:PYTHONUTF8=1; python pipeline.py input.json ...
```

To set this permanently, add `PYTHONUTF8=1` to your Windows system environment variables
(Control Panel → System → Advanced → Environment Variables).

This does not affect Docker — the container sets UTF-8 automatically.

---

**`ModuleNotFoundError: No module named 'lxml'`** (or `requests`, `tqdm`)

```bash
pip install -r requirements.txt
```

---

**All entries show `Unknown` style with zero scores**

The `raw_text` field is empty or uses the wrong key name. Verify your input JSON uses
`"raw_text"` or `"text"` as the key. Both are accepted.

---

**DOI check shows every entry as advisory**

This is expected without `--deep-doi`. The default check is purely text-based — it does not
call CrossRef. Run with `--deep-doi --crossref-email your@institution.edu` for confirmed results.

---

**`EXTRACTOR_IMAGE variable is not set`**

The `.env` file is missing. Copy the example and it will be pre-filled:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

---

**`docker compose pull` fails with `unauthorized` or `denied`**

You are not logged in to the GitHub Container Registry. Run:

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

Use a GitHub Personal Access Token (not your password) with `read:packages` scope as the password.
Request access from the repository owner if you do not have it.
