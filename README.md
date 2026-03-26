# MTB Start List Analyzer

A command-line tool that fetches MTB race start lists, enriches them with UCI ranking data, and produces terminal output, HTML reports, or CSV exports. It also compares two races side by side to help you decide which one has the stronger field.

---

## Features

- **Auto-detects the website format** — supports sportzeitnehmung.at, runtix.com, and a generic fallback for other sites
- **UCI ranking lookup** — matches riders by UCI ID (exact) or by name using fuzzy matching when no ID is available (e.g. runtix.com)
- **Local cache** — downloads the UCI ranking once and caches it for 7 days so repeat runs are instant
- **Accurate category filtering** — word-boundary matching prevents `Men Juniors` from accidentally matching `Women Juniors`
- **HTML export** — self-contained dark-themed report with stat cards, colour-coded rider table, live search, country bar chart, and an optional race comparison section
- **CSV export** — plain spreadsheet, sorted by UCI ranking
- **Race comparison** — quality score formula ranks two start lists and declares a winner

---

## Requirements

Python 3.8 or newer. Install dependencies with:

```bash
pip install requests beautifulsoup4 rich thefuzz python-Levenshtein
```

`python-Levenshtein` is optional but makes fuzzy name matching significantly faster.

---

## Quick Start

```bash
# Analyse a single race — Men Juniors category
python mtb_analyzer.py \
  --url "https://www.sportzeitnehmung.at/en/component/eventbooking/34-ktm-kamptal-trophy-c/registrants-list.html" \
  --category "Men Juniors"

# Same race, export as HTML report
python mtb_analyzer.py \
  --url "https://www.sportzeitnehmung.at/..." \
  --category "Men Juniors" \
  --export report.html

# Compare two races (outputs a single HTML file with both lists + comparison)
python mtb_analyzer.py \
  --compare \
    "https://www.sportzeitnehmung.at/.../registrants-list.html" \
    "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --export comparison.html

# Refresh the cached UCI ranking
python mtb_analyzer.py --refresh-cache --uci-category MJ
```

---

## All Options

| Option | Short | Description |
|--------|-------|-------------|
| `--url URL` | | URL of the start list to analyse |
| `--compare URL1 URL2` | | Compare two start lists side by side |
| `--category TEXT` | `-c` | Category filter (see below) |
| `--uci-category` | `-u` | UCI ranking to use: `MJ` `WJ` `ME` `WE` (default: `MJ`) |
| `--refresh-cache` | | Force re-download of UCI ranking, ignoring local cache |
| `--export FILE` | | Export to `file.html` or `file.csv` (format detected by extension) |
| `--no-lookup` | | Skip UCI ranking lookup — just parse the start list |

### UCI category codes

| Code | Meaning |
|------|---------|
| `MJ` | Men Juniors (U19) — **default** |
| `WJ` | Women Juniors (U19) |
| `ME` | Men Elite |
| `WE` | Women Elite |

---

## Category Filter

The `--category` filter uses word-boundary matching, so partial words work and false positives are avoided:

```bash
--category "Men Juniors"   # matches "XCO Men Juniors" but NOT "Women Juniors"
--category "Junior"        # matches both "Men Juniors" and "Women Juniors"
--category "Elite"         # matches "Men Elite" and "Women Elite"
--category "Men Elite"     # matches only "Men Elite", not "Women Elite"
```

If you omit `--category`, all entries from the start list are included.

---

## Supported Websites

| Website | UCI ID available | Lookup method |
|---------|-----------------|---------------|
| sportzeitnehmung.at | ✅ Yes | Exact UCI ID match |
| runtix.com | ❌ No | Fuzzy name matching |
| Other | Depends | Generic parser + fuzzy match |

When fuzzy name matching is used, a confidence badge is shown in the output (e.g. `87%`). Only matches above 82 % are accepted; below that, the rider is listed as unranked.

---

## HTML Report

The exported HTML file is fully self-contained (no internet connection needed to open it) and includes:

- **Stat cards** — total starters, ranked count, best rank, average rank, TOP 50 / TOP 100 / TOP 200 counts, total UCI points, and TOP-10 points
- **Rider table** — sorted by UCI ranking, colour-coded by tier:
  - 🟢 **Bold green** — TOP 50
  - 🟢 Green — TOP 51–200
  - 🟡 Yellow — Ranked 201+
  - Grey — Unranked
- **Live search** — filter the table instantly by name, country, or team
- **Country breakdown** — bar chart with counts and percentages
- **Race comparison section** — included automatically when using `--compare`

When comparing two races with `--export comparison.html`, both start lists and the full comparison table are written into a single file.

---

## Race Comparison & Quality Score

The quality score formula used to rank two start lists:

```
score = (points of top-10 riders × 3)
      + (riders in TOP 50 × 10)
      + (riders in TOP 100 × 5)
      + (riders in TOP 200 × 2)
      + total ranked riders
```

A higher score means a stronger and deeper field. The verdict is shown both in the terminal and in the exported HTML.

---

## Caching

UCI ranking data is downloaded from [xcodata.com](https://www.xcodata.com) and stored locally in a `.mtb_cache/` folder next to the script. The cache is considered fresh for **7 days**. To force a re-download at any time:

```bash
python mtb_analyzer.py --refresh-cache --uci-category MJ
```

Cache files follow the naming pattern `.mtb_cache/ranking_MJ_2026.json`. Delete the folder to clear all cached data.

---

## Examples

### Single race — terminal output only

```bash
python mtb_analyzer.py \
  --url "https://www.sportzeitnehmung.at/en/component/eventbooking/34-ktm-kamptal-trophy-c/registrants-list.html" \
  --category "Men Juniors" \
  --uci-category MJ
```

### Single race — HTML export

```bash
python mtb_analyzer.py \
  --url "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --uci-category MJ \
  --export fullgaz_juniors.html
```

### Single race — CSV export

```bash
python mtb_analyzer.py \
  --url "https://www.sportzeitnehmung.at/..." \
  --category "Men Elite" \
  --uci-category ME \
  --export elite_men.csv
```

### Compare two races — HTML with comparison

```bash
python mtb_analyzer.py \
  --compare \
    "https://www.sportzeitnehmung.at/.../registrants-list.html" \
    "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --uci-category MJ \
  --export comparison.html
```

### Compare two races — CSV (two separate files)

When exporting a comparison to CSV, two files are created automatically:

```bash
python mtb_analyzer.py \
  --compare "https://race1..." "https://race2..." \
  --category "Junior" \
  --export results.csv
# produces: results_race1.csv  and  results_race2.csv
```

### Skip UCI lookup (fast, start list only)

```bash
python mtb_analyzer.py \
  --url "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --no-lookup
```

---

## Project Structure

```
mtb_analyzer.py      # main script — everything is in one file
.mtb_cache/          # auto-created local cache folder
  ranking_MJ_2026.json
  ranking_WJ_2026.json
  ...
```

---

## Data Sources

| Data | Source |
|------|--------|
| UCI rankings | [xcodata.com](https://www.xcodata.com) |
| Start lists | Directly from the provided URL |
