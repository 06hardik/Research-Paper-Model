# Reference Section Quality Pipeline — Technical Report

**Project:** Reference Section Quality Analysis Tool  
**Module:** Automated Quality Check System  
**Date:** March 2026  
**Supported Styles:** IEEE · APA · MLA · Harvard · Vancouver  

---

## Overview

The pipeline processes a list of raw academic citation strings and runs five independent quality checks against them. Before any check runs, each citation is:

1. **Parsed** by a field extraction service into structured fields (authors, title, container title, year, volume, issue, pages, DOI, URL, publisher)
2. **Classified** by a rule-based classifier into one of the five supported citation styles, with a confidence score
3. **Passed** to all five checks along with the dominant style detected across the whole list

The five checks are:

| # | Check | Scope |
|---|---|---|
| 1 | Reference Ordering | Whole list |
| 2 | DOI Presence | Per entry |
| 3 | Journal Title Casing | Per entry + cross-list consistency |
| 4 | Field Completeness & Formatting | Per entry |
| 5 | Citation Style Conformity | Per entry vs. dominant list style |

---

## Check 1 — Reference Ordering

**File:** `checks/check_ordering.py`

Verifies that the entries in the reference list appear in the correct sequence for the detected citation style.

### Ordering rules by style

| Style | Required order | How it works |
|---|---|---|
| IEEE | Numeric ascending: [1], [2], [3], … | Extracts the `[N]` or `N.` label from the start of each entry and verifies it increments by exactly 1 |
| Vancouver | Numeric ascending: 1, 2, 3, … | Same approach as IEEE, using bare number prefix |
| APA | Alphabetical by first-author surname | Extracts the surname of the first author and checks alphabetic sort order |
| MLA | Alphabetical by first-author surname | Same as APA |
| Harvard | Alphabetical by first-author surname | Same as APA |

### Surname extraction logic (APA / MLA / Harvard)

The check tries three sources in this priority order:

1. **Parsed authors field** — the extraction service returns authors in `Forename Surname` order; the last token is taken as the surname
2. **Raw text pattern `Surname, First …`** — matched by regex for inverted-name formats
3. **Raw text pattern `Firstname Surname.`** — fallback for uninverted name formats

Accent-insensitive comparison is applied (e.g. `García` sorts as `garcia`). Surname prefixes such as `van`, `de`, `von`, `le`, `el`, `mac`, `du` are stripped before comparison so that `van Gogh` sorts under `G`.

### What is reported

Every entry that breaks the expected order generates an `OrderIssue` containing:
- The entry ID and its 1-based position
- What was expected at that position
- What was actually found

---

## Check 2 — DOI Presence

**File:** `checks/check_doi.py`

Scans each entry for the presence of a DOI (Digital Object Identifier). A DOI provides a persistent link to the cited work and is strongly recommended in all modern citation styles.

### Detection method

- Looks for `doi:`, `DOI:`, or `https://doi.org/` prefix in the raw text
- Also inspects the `doi` field returned by the extraction service

### Two operating modes

| Mode | Flag | Behaviour |
|---|---|---|
| Text-based (default) | _(none)_ | Checks raw text and parsed field only. No network call. Missing DOI is flagged as advisory (`missing`) |
| CrossRef verification | `--deep-doi` | Queries the CrossRef REST API for the title + author combination. If a DOI is found, the issue is upgraded to `crossref_found`, confirming the DOI exists and was missing from the citation |

When `--crossref-email` is provided, the CrossRef request includes a `mailto:` header which grants access to CrossRef's polite pool (higher rate limit).

---

## Check 3 — Journal Title Casing

**File:** `checks/check_journal_casing.py`

Verifies that journal and container titles use casing consistent with both the detected style's convention and with all other occurrences of the same journal elsewhere in the list.

### Casing conventions by style

| Style | Convention | Description | Example |
|---|---|---|---|
| APA | Title Case | All major words capitalised; minor words (a, an, the, of, in, …) lowercase unless first/last | *Journal of Applied Science* |
| MLA | Title Case | Same rule set as APA | *Journal of Applied Science* |
| Harvard | Title Case | Same rule set as APA | *Journal of Applied Science* |
| IEEE | Title Case (abbreviated) | Title case is expected; standard abbreviations are advisory | *IEEE Trans. Neural Netw.* |
| Vancouver | NLM abbreviated format | Words are abbreviated; only first letter of each abbreviation capitalised | *N Engl J Med* |

**Minor words excluded from capitalisation requirement in Title Case:**  
`a, an, the, and, but, for, nor, or, so, yet, at, by, in, of, off, on, out, to, up, as, if, into, onto, upon, with, from, over, between, through`

### Two-layer checking

**Layer A — Cross-list consistency:**  
All entries are scanned for every unique journal title. After normalisation (lowercase, strip punctuation, strip accents), if the same journal appears with different casing in different entries, every variant that differs from the most common form is flagged as `inconsistent`.

**Layer B — Per-style correctness:**  
Each entry's journal title is individually checked against the convention for its style. Issues are typed as `wrong_case` when the casing pattern does not match the style convention.

---

## Check 4 — Field Completeness & Formatting

**File:** `checks/check_completeness.py`

This is the most detailed check. It operates in two independent layers.

---

### Reference type inference

Before checking fields, each entry is classified into one of four reference types. This determines which fields are required.

| Type | Condition |
|---|---|
| `article` | Has `container_title` (journal name), no `publisher` |
| `book` | Has `publisher`, no `container_title` |
| `chapter` | Has both `container_title` and `publisher` |
| `web` | Has `url` but no `container_title` |
| `other` | None of the above |

---

### Layer A — Required fields per style and reference type

The tables below show which fields are **required (R)** and which are **recommended (rec)** for each combination of style and reference type. A missing required field raises a `missing` issue. A missing recommended field raises a `suspicious` (advisory) issue.

#### IEEE

| Field | article | book | chapter | web | other |
|---|---|---|---|---|---|
| `authors` | R | R | R | R | R |
| `title` | R | R | R | R | R |
| `container_title` | R | — | R | — | — |
| `pub_date` | R | R | R | R | R |
| `volume` | R | — | — | — | — |
| `pages` | R | — | R | — | — |
| `issue` | rec | — | — | — | — |
| `doi` | rec | rec | — | — | — |
| `publisher` | — | R | R | — | — |
| `url` | — | — | — | rec | — |

#### APA

| Field | article | book | chapter | web | other |
|---|---|---|---|---|---|
| `authors` | R | R | R | R | R |
| `title` | R | R | R | R | R |
| `container_title` | R | — | R | — | — |
| `pub_date` | R | R | R | R | R |
| `volume` | R | — | — | — | — |
| `pages` | rec | — | R | — | — |
| `issue` | rec | — | — | — | — |
| `doi` | rec | rec | — | — | — |
| `publisher` | — | R | rec | — | — |
| `url` | — | — | — | rec | — |

#### MLA

| Field | article | book | chapter | web | other |
|---|---|---|---|---|---|
| `authors` | R | R | R | R | R |
| `title` | R | R | R | R | R |
| `container_title` | R | — | R | — | — |
| `pub_date` | R | R | R | R | R |
| `volume` | R | — | — | — | — |
| `pages` | R | — | R | — | — |
| `issue` | rec | — | — | — | — |
| `doi` | rec | — | — | — | — |
| `publisher` | — | R | R | — | — |
| `url` | — | — | — | rec | — |

#### Harvard

| Field | article | book | chapter | web | other |
|---|---|---|---|---|---|
| `authors` | R | R | R | R | R |
| `title` | R | R | R | R | R |
| `container_title` | R | — | R | — | — |
| `pub_date` | R | R | R | R | R |
| `volume` | R | — | — | — | — |
| `pages` | rec | — | R | — | — |
| `issue` | rec | — | — | — | — |
| `publisher` | — | R | rec | — | — |
| `url` | — | — | — | rec | — |

#### Vancouver

| Field | article | book | chapter | web | other |
|---|---|---|---|---|---|
| `authors` | R | R | R | R | R |
| `title` | R | R | R | R | R |
| `container_title` | R | — | R | — | — |
| `pub_date` | R | R | R | — | — |
| `volume` | R | — | — | — | — |
| `pages` | R | — | R | — | — |
| `issue` | rec | — | — | — | — |
| `doi` | rec | — | — | — | — |
| `publisher` | — | R | R | — | — |
| `pub_date` (rec) | — | — | — | rec | rec |
| `url` | — | — | — | rec | — |

> **Key difference:** Vancouver is the strictest style for journal articles — it requires `volume` and `pages` in addition to all the core fields that other styles also require.

---

### Layer B — Formatting checks per style

Beyond checking that fields are present, Layer B checks that field values are correctly formatted according to each style's rules.

#### APA formatting rules

| Field | Rule | Issue raised if violated |
|---|---|---|
| `pub_date` | Year must appear in parentheses in the raw text: `(2020)` | `formatting` — "APA requires the year in parentheses" |
| `authors` | When multiple authors, the last two must be joined with `&`, not `and` | `formatting` — "APA uses '&' to join the last two authors, not 'and'" |

#### MLA formatting rules

| Field | Rule | Issue raised if violated |
|---|---|---|
| `pages` | Page ranges for articles and chapters must be prefixed with `pp.` | `formatting` — "MLA requires 'pp.' before page ranges" |
| `volume` | Volume must be written as `vol. N`, not a bare number | `formatting` — "MLA writes volume as 'vol. N' not a bare number" |
| `pub_date` | Year must appear in the last third of the entry (after title/publisher), not directly after the author | `formatting` — "MLA places the year at the end of the entry" |

#### Harvard formatting rules

| Field | Rule | Issue raised if violated |
|---|---|---|
| `pub_date` | Year must appear in parentheses in the raw text: `(2020)` | `formatting` — "Harvard requires the year in parentheses" |

#### Vancouver formatting rules

| Field | Rule | Issue raised if violated |
|---|---|---|
| `authors` | Initials must not include periods. Correct: `Smith AB`. Wrong: `Smith, A.B.` | `formatting` — "Vancouver authors use initials without periods" |
| `pub_date` + `volume` + `pages` | Must follow the compound format `Year;Volume(Issue):Pages` e.g. `2002;347(4):284-7` | `formatting` — "Vancouver uses the format 'Year;Volume(Issue):Pages'" |

#### Cross-style suspicious value checks (all styles)

These run regardless of style and flag plausible parsing errors:

| Condition | Issue type | Detail |
|---|---|---|
| `pages` value matches `^(19\|20)\d{2}$` (looks like a year) | `suspicious` | "Pages field contains what looks like a year — possible parsing error" |
| `volume` is a number between 1–31 AND raw text contains "accessed/retrieved/cited" | `suspicious` | "Volume field contains a small number that looks like an access day" |
| `pub_date` after cleaning does not match `YYYY` and is not `n.d.` / `forthcoming` | `suspicious` | "Publication date does not look like a valid year" |

---

### Issue severity levels

| `issue_type` | Severity | Trigger |
|---|---|---|
| `missing` | High — required field absent | A field listed as R in the schema is empty or null |
| `formatting` | Medium — field present but incorrectly formatted | A style-specific format rule is violated |
| `suspicious` | Low — advisory | A recommended field is absent, or a value looks like a parsing artefact |

---

## Check 5 — Citation Style Conformity

**File:** `checks/check_style_conformity.py`

After the dominant style for the whole list is determined (by majority vote across individual entry classifications), each entry is individually re-examined. Entries whose per-entry classification disagrees with the dominant style are flagged as `style_mismatch`.

### What is reported

Each mismatch produces an issue containing:
- The entry ID and position
- The style the entry appears to use (its individual classification)
- The dominant style expected for the list
- The confidence score of the individual classification

This check identifies entries that may have been copied from a different source, formatted under a different style guide, or accidentally included from a different reference list.

---

## Classification System

The style classifier (`citation_classifier.py`) assigns each entry a style using a two-stage process.

### Stage 1 — Hard filters

Hard filters are deterministic rules that either **require** or **exclude** a style based on the presence of a specific pattern. They run first and can immediately eliminate styles from consideration.

Selected examples:

| Pattern | Effect |
|---|---|
| Entry starts with `[N]` (IEEE label) | Only IEEE allowed |
| `https://doi.org/` present | Only APA or IEEE allowed |
| `[Internet]` present | Only Vancouver allowed |
| `[cited YYYY` present | Only Vancouver allowed |
| `Publisher; YEAR` pattern (semicolon before year) | Only Vancouver allowed |
| `vol.` and `no.` present | Only MLA or Harvard allowed |
| `(Accessed DD Mon YYYY)` | Only Harvard allowed |
| Inverted full name at start (`Smith, Anne Frances`) | Vancouver excluded |

### Stage 2 — Scoring rules

After hard filters, each remaining style accumulates points based on weighted pattern matches. The style with the highest total score wins. Confidence is assigned based on the margin between the top score and the second-highest:

| Confidence | Condition |
|---|---|
| `HIGH` | Top score ≥ 8 and lead over second ≥ 4 |
| `MEDIUM` | Top score ≥ 4 or lead ≥ 2 |
| `LOW` | Everything else |

---

## Output

Each check contributes its findings to a unified output available in two forms:

### JSON (`--output results.json`)

Structured machine-readable output with per-entry issue arrays, scores, and a top-level summary including which checks passed and failed.

### Text report (`--report report.txt`)

Human-readable summary showing the check pass/fail table followed by per-entry issue details with fix suggestions.

---

## Accuracy (test set evaluation)

Evaluated on a manually labelled test set of 102 citations (mixed styles):

| Style | Correct / Total | Accuracy |
|---|---|---|
| IEEE | 20 / 20 | 100% |
| APA | 22 / 22 | 100% |
| MLA | 18 / 18 | 100% |
| Harvard | 17 / 17 | 100% |
| Vancouver | 18 / 18 | 100% |
| **Overall** | **95 / 102** | **93.1%** |

The 7 remaining misclassifications are entries with minimal distinguishing features (e.g. single-author books with no DOI and no style-specific punctuation).
