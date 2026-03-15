# Reference Section Quality Pipeline

This pipeline validates and analyses academic reference lists. Give it a JSON file containing raw citation strings and it returns a structured report of every quality issue found — wrong ordering, missing DOIs, incorrect casing, incomplete fields, and style inconsistencies.

**Supported citation styles:** IEEE · APA · MLA · Harvard · Vancouver

---

## Table of Contents

1. [How It Works](#1-how-it-works)
2. [What You Need](#2-what-you-need)
3. [Setup and First Run](#3-setup-and-first-run)
4. [Input Format](#4-input-format)
5. [Running the Pipeline](#5-running-the-pipeline)
6. [All CLI Options](#6-all-cli-options)
7. [Output Format](#7-output-format)
8. [Quality Checks](#8-quality-checks)
9. [Supported Citation Styles](#9-supported-citation-styles)
10. [Using the Pipeline as a Python Module](#10-using-the-pipeline-as-a-python-module)
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
  |  Each raw citation string is parsed into structured fields  |
  |  (authors, title, journal, year, DOI, pages, ...)           |
  +------------------------+------------------------------------+
                           |
                           v
  +-------------------------------------------------------------+
  |  Step 2 - Style Classification                              |
  |  Each entry is classified as IEEE / APA / MLA /             |
  |  Harvard / Vancouver with a confidence score.               |
  |  The dominant style for the whole list is determined.       |
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

## 2. What You Need

| Requirement | Version | Notes |
|---|---|---|
| [Docker Desktop](https://docs.docker.com/get-docker/) | any recent | Required — install and start it before anything else |
| A GitHub account | — | Required to pull the extraction service image |
| Python | >= 3.9 | Only needed if running outside Docker |

> **Windows users:** If you run the pipeline with Python directly (not Docker), prefix every command with `$env:PYTHONUTF8=1;` to avoid encoding errors. Docker handles this automatically — no action needed.

---

## 3. Setup and First Run

Everything runs inside Docker. No Python installation is needed for this path.

### Step 1 — Generate a GitHub Personal Access Token

The extraction service image is hosted on a private GitHub Container Registry. You need to authenticate with your own GitHub account before you can pull it. Access to the image has already been granted to your account.

1. Go to: https://github.com/settings/tokens/new
2. Give it any name (e.g. `ghcr-read`)
3. Set expiration to your preference
4. Under **Scopes**, tick only `read:packages`
5. Click **Generate token** and copy it — you will not see it again

### Step 2 — Log in to the GitHub Container Registry

Open a terminal and run:

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

When prompted for a password, paste the token you just generated — **not** your GitHub password.

### Step 3 — Clone the repository and create the `.env` file

```bash
git clone https://github.com/06hardik/Research-Paper-Model.git
cd Research-Paper-Model/REFRENCE-SECTION
```

Copy the provided example file — the correct image name is already filled in:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### Step 4 — Pull the image and build the pipeline container

```bash
docker compose pull
docker compose build
```

This only needs to be done once. `pull` downloads the extraction service image; `build` assembles the pipeline container from the source code.

### Step 5 — Start the extraction service

```bash
docker compose up -d extraction-engine
```

Wait about 30–45 seconds for it to become ready, then verify:

```bash
docker compose ps
```

The `extraction-engine` row should show **Health: healthy**. If it still shows `starting`, wait a few more seconds and run the command again.

### Step 6 — Place your input file

Copy your references JSON into the `data/` folder:

```
REFRENCE-SECTION/
└── data/
    └── your_references.json    <-- place it here
```

See [Section 4](#4-input-format) for the exact format the file must follow.

### Step 7 — Run the pipeline

```bash
docker compose run --rm pipeline   /data/your_references.json   --output /data/results.json   --report /data/report.txt
```

Once the command finishes, the results appear in the same `data/` folder on your machine:

```
data/
├── results.json    <-- full structured JSON report
└── report.txt      <-- human-readable quality report
```

### Step 8 — Stop everything when done

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
| `metadata` | No | Any extra key-value pairs. Passed through unchanged to the output |

---

## 5. Running the Pipeline

### Standard run (Docker)

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --output /data/results.json \
  --report /data/report.txt
```

### With CrossRef DOI verification

Queries CrossRef to confirm whether missing DOIs actually exist for those works.

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --output /data/results.json \
  --report /data/report.txt \
  --deep-doi \
  --crossref-email your@email.com
```

### Limit to first N entries (useful for testing)

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --limit 10 \
  --output /data/results.json \
  --report /data/report.txt
```

### Dry-run — classify without field extraction

Runs the classifier and quality checks using the raw text alone. The extraction service does not need to be running.

```bash
docker compose run --rm pipeline \
  /data/input.json \
  --dry-run \
  --output /data/results.json \
  --report /data/report.txt
```

### Without Docker (Python directly)

If you prefer not to use Docker, set up a virtual environment and run the pipeline with Python. The extraction service must still be running separately.

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

```bash
# Windows
$env:PYTHONUTF8=1; python pipeline.py input.json --output results.json --report report.txt

# macOS / Linux
python pipeline.py input.json --output results.json --report report.txt
```

---

## 6. All CLI Options

| Option | Default | Description |
|---|---|---|
| `input` | *(required)* | Path to the input JSON file |
| `--output FILE` | *(none)* | Write full JSON report to this file |
| `--report FILE` | *(none)* | Write human-readable text report to this file |
| `--parser-url URL` | auto | Extraction service URL — set automatically when using Docker |
| `--workers N` | `8` | Number of concurrent extraction threads |
| `--timeout N` | `15` | Per-request timeout in seconds |
| `--dry-run` | off | Skip field extraction; classify from raw text only |
| `--deep-doi` | off | Query CrossRef API to confirm missing DOIs |
| `--crossref-email EMAIL` | *(none)* | Your email for CrossRef's polite pool (faster rate limit) |
| `--quiet` | off | Suppress progress output; print errors only |
| `--verbose` | off | Enable detailed debug logging |
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
| `checks_passed` | Checks with no issues found |
| `checks_failed` | Checks that found at least one issue |
| `list_level_issues` | Issues that affect the whole list (e.g. ordering violations) |
| `entries[].parsed` | Structured fields extracted from the raw citation string |
| `entries[].style` | Per-entry style classification with individual scores |
| `entries[].issues` | Per-entry list of issues with field name, type, detail, and fix suggestion |

#### Issue types

| `issue_type` | Meaning |
|---|---|
| `missing` | A required field is absent from the citation |
| `formatting` | A field is present but does not follow the correct format |
| `suspicious` | A field value looks unusual — advisory, not necessarily wrong |
| `inconsistent` | Casing or format differs from the rest of the list |
| `style_mismatch` | This entry appears to use a different style than the rest of the list |

---

### Text Report (`--report`)

A plain-text summary suitable for reading directly or sharing with reviewers.

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
| IEEE | Numeric ascending: [1], [2], [3], ... |
| Vancouver | Numeric ascending: 1, 2, 3, ... |
| APA | Alphabetical by first author surname |
| MLA | Alphabetical by first author surname |
| Harvard | Alphabetical by first author surname |

Violations are reported in `list_level_issues` with the position, what was expected, and what was found.

### Check 2 — DOI Presence

Flags entries with no DOI in the citation string.

- Without `--deep-doi`: advisory only — no external requests are made
- With `--deep-doi`: queries CrossRef to confirm whether a DOI exists for the work
- With `--crossref-email`: provides a `mailto:` header for CrossRef's polite pool, which allows a higher request rate

### Check 3 — Journal Title Casing

Enforces the casing convention required by the detected style.

| Style | Convention | Example |
|---|---|---|
| APA | Title Case | *Journal of Applied Science* |
| MLA | Title Case | *Journal of Applied Science* |
| Harvard | Title Case | *Journal of Applied Science* |
| IEEE | Standard abbreviations | *IEEE Trans. Neural Netw.* |
| Vancouver | NLM abbreviations | *N Engl J Med* |

### Check 4 — Field Completeness & Formatting

Checks every parsed entry against the required and recommended fields for its style. Reports:

- **Missing fields** — authors, year, title, journal, volume, issue, pages (varies by style)
- **Formatting errors** — wrong date format, malformed page range, incorrect DOI format
- **Suspicious values** — title under three words, year outside 1800–2030, empty author list

### Check 5 — Style Conformity

After the dominant style across the list is determined, each individual entry is checked against it. Entries that do not match are flagged as `style_mismatch`, specifying which style was detected and what was expected.

---

## 9. Supported Citation Styles

| Style | Author format | Year position | Key identifiers |
|---|---|---|---|
| **IEEE** | `J. A. Smith` | Near end | `[1]` label at start; `doi: 10.xxxx` |
| **APA** | `Smith, J. A.` | `(2020).` after author | `https://doi.org/10.xxxx`; `(pp. X–Y)` |
| **MLA** | `Smith, John` | Near end, after publisher | `vol. 5, no. 3`; `Accessed` date |
| **Harvard** | `Smith, J.` | `(2020)` after author | `Available at:`; `(Accessed DD Mon YYYY)` |
| **Vancouver** | `Smith JA` | `Year;vol(issue):pages` | `[Internet]`; `[cited 2020 May 3]`; NLM abbreviations |

---

## 10. Using the Pipeline as a Python Module

You can import `run()` directly and call it from your own Python code instead of using the CLI.

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

print(result["summary"]["style"])            # "Vancouver"
print(result["summary"]["total_issues"])     # 0

for entry in result["entries"]:
    for issue in entry["issues"]:
        print(f"[{entry['id']}] {issue['field']}: {issue['detail']}")
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entries` | `list[dict]` | *(required)* | List of dicts with `id`, `raw_text`, optional `metadata` |
| `parser_url` | `str` | `http://localhost:8070/api/processCitation` | URL of the extraction service |
| `workers` | `int` | `8` | Concurrent extraction threads |
| `timeout` | `int` | `15` | Per-request timeout in seconds |
| `dry_run` | `bool` | `False` | Skip extraction; classify from raw text only |
| `deep_doi` | `bool` | `False` | Query CrossRef for missing DOIs |
| `crossref_email` | `str` | `None` | Your email for CrossRef polite-pool |

The `parser_url` can also be set via the `PARSER_URL` environment variable — the function reads it automatically if the parameter is not passed.

---

## 11. Project Structure

```
REFRENCE-SECTION/
|
+-- pipeline.py                     Main entry point — orchestrates all steps
+-- citation_classifier.py          Rule-based 5-style classifier
+-- reference_parser.py             Extraction service client and XML parser
|
+-- Dockerfile                      Builds the pipeline container
+-- docker-compose.yml              Starts the extraction service and pipeline together
+-- .env.example                    Copy this to .env before running
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
|   +-- README.txt                  Instructions for this folder
|
+-- test/
    +-- input_test.json             Mixed multi-style test set
    +-- input.json                  Additional test entries
```

---

## 12. Troubleshooting

**`docker compose pull` fails with `unauthorized` or `denied`**

You are not authenticated. Run the login command first:

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

Use the Personal Access Token you generated in Step 1 as the password — not your GitHub account password.

---

**`EXTRACTOR_IMAGE variable is not set`**

The `.env` file is missing. Create it by copying the example:

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

---

**Extraction service never becomes healthy**

```bash
docker compose logs extraction-engine
```

The service needs 30–45 seconds to start. If it keeps restarting, check that Docker Desktop
has at least 4 GB of memory allocated (Settings → Resources → Memory).

---

**`RuntimeError: Field extraction model not reachable`**

The extraction service has not started yet or has stopped.

```bash
docker compose up -d extraction-engine
docker compose ps   # wait until Health = healthy
```

Alternatively, add `--dry-run` to your command to skip extraction entirely.

---

**`UnicodeEncodeError: charmap codec can't encode character`** (Windows only)

Your terminal is using cp1252 encoding. Prefix every Python command with:

```powershell
$env:PYTHONUTF8=1; python pipeline.py ...
```

This is not needed when running via Docker — the container sets UTF-8 automatically.

---

**`ModuleNotFoundError: No module named 'lxml'`** (or `requests`, `tqdm`)

```bash
pip install -r requirements.txt
```

---

**All entries show `Unknown` style with zero scores**

The input file is using the wrong key name. The pipeline expects `"raw_text"` or `"text"`.
Check your JSON and rename the field if necessary.

---

**DOI check shows every entry as advisory**

Without `--deep-doi`, the check is text-based only and does not call CrossRef.
Add `--deep-doi --crossref-email your@email.com` to get confirmed results.
