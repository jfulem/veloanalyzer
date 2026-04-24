# MTB Start List Analyzer

A command-line tool that fetches MTB race start lists, enriches them with UCI ranking data, and produces terminal output, HTML reports, or CSV exports. It also compares two races side by side to help you decide which one has the stronger field.

---

## Features

- **Auto-detects the website format** — supports sportzeitnehmung.at, runtix.com, sportkrono.hu, my.raceresult.com, Google Sheets (pubhtml), and a generic fallback
- **UCI ranking lookup** — matches riders by UCI ID (exact) or by name using fuzzy matching when no ID is available
- **Local cache** — downloads the UCI ranking once and caches it for 7 days so repeat runs are instant
- **Accurate category filtering** — word-boundary matching prevents `Men Juniors` from accidentally matching `Women Juniors`
- **Category name normalisation** — non-English category words (e.g. German *Junioren*, Hungarian *Elit*) are mapped to standard English so `--category "Men Juniors"` works across all sources
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
python main.py \
  --url "https://www.sportzeitnehmung.at/en/component/eventbooking/34-ktm-kamptal-trophy-c/registrants-list.html" \
  --category "Men Juniors"

# Same race, export as HTML report
python main.py \
  --url "https://www.sportzeitnehmung.at/..." \
  --category "Men Juniors" \
  --export report.html

# Compare two races (outputs a single HTML file with both lists + comparison)
python main.py \
  --compare \
    "https://www.sportzeitnehmung.at/.../registrants-list.html" \
    "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --export comparison.html

# Refresh the cached UCI ranking
python main.py --refresh-cache --uci-category MJ
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

Non-English category words are automatically normalised to English before filtering, so you always use English terms regardless of the source site:

| Raw (source) | Normalised |
|---|---|
| Junioren (German) | Juniors |
| Amateure (German) | Amateur |
| Elit (Hungarian) | Elite |

If you omit `--category`, all entries from the start list are included.

---

## Supported Websites

| Website | UCI ID | Country | Notes |
|---------|--------|---------|-------|
| sportzeitnehmung.at | ✅ | ✅ | Exact UCI ID match; paginated |
| runtix.com | ❌ | ✅ | Fuzzy name matching |
| sportkrono.hu | ❌ | ❌ | Hungarian race series; AJAX-based |
| my.raceresult.com | ❌ | ✅ | JSON API; gender from subgroup names |
| Google Sheets (pubhtml) | ✅ | ❌ | Croatian/regional events; CSV export used |
| Other | Depends | Depends | Generic table parser + fuzzy match |

When fuzzy name matching is used, a confidence badge is shown in the output (e.g. `87%`). Only matches above 82 % are accepted; below that, the rider is listed as unranked.

### sportkrono.hu

Pass the event URL directly — the event ID is extracted automatically:

```bash
python main.py \
  --url "https://sportkrono.hu/Rendezvenyek2/nevezes-lista/152" \
  --category "U19"
```

### my.raceresult.com

Pass the participants page URL — the tool fetches the config and data via the internal JSON API:

```bash
python main.py \
  --url "https://my.raceresult.com/379442/participants" \
  --category "Men Juniors"
```

Categories follow the `Men <age group>` / `Women <age group>` pattern (e.g. `Men Elite`, `Women U23`, `Men Juniors`).

### Google Sheets (pubhtml)

Pass the published `pubhtml` URL. The tool converts it to a CSV export internally:

```bash
python main.py \
  --url "https://docs.google.com/spreadsheets/d/e/DOCID/pubhtml?gid=GID&single=true" \
  --category "Men Juniors"
```

The sheet must have columns: `#`, `UCI ID`, `Prezime`, `Ime`, `Spol` (M/Ž), `Kategorija`, `Klub`.

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
python main.py --refresh-cache --uci-category MJ
```

Cache files follow the naming pattern `.mtb_cache/ranking_MJ_2026.json`. Delete the folder to clear all cached data.

---

## Examples

### Single race — terminal output only

```bash
python main.py \
  --url "https://www.sportzeitnehmung.at/en/component/eventbooking/34-ktm-kamptal-trophy-c/registrants-list.html" \
  --category "Men Juniors" \
  --uci-category MJ
```

### Single race — HTML export

```bash
python main.py \
  --url "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --uci-category MJ \
  --export fullgaz_juniors.html
```

### Single race — CSV export

```bash
python main.py \
  --url "https://www.sportzeitnehmung.at/..." \
  --category "Men Elite" \
  --uci-category ME \
  --export elite_men.csv
```

### Compare two races — HTML with comparison

```bash
python main.py \
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
python main.py \
  --compare "https://race1..." "https://race2..." \
  --category "Junior" \
  --export results.csv
# produces: results_race1.csv  and  results_race2.csv
```

### Skip UCI lookup (fast, start list only)

```bash
python main.py \
  --url "https://my.raceresult.com/379442/participants" \
  --category "Men Juniors" \
  --no-lookup
```

---

## Project Structure

```
main.py                          # CLI entry point
mtb_analyzer/                    # package
├── config.py                    # constants (flags, country maps, category aliases)
├── models.py                    # Rider dataclass
├── utils.py                     # fetch, normalize_*, category_matches
├── ranking.py                   # UCI ranking cache + lookup
├── display.py                   # terminal output, sort_riders, race_quality_stats
├── export.py                    # HTML and CSV export
└── parsers/
    ├── __init__.py              # detect_site + parse_start_list
    ├── sportzeitnehmung.py
    ├── runtix.py
    ├── sportkrono.py
    ├── gsheets.py
    ├── raceresult.py
    └── generic.py               # generic table fallback
.mtb_cache/                      # auto-created local cache folder
  ranking_MJ_2026.json
  ranking_WJ_2026.json
  ...
```

To add support for a new website, create a parser file in `mtb_analyzer/parsers/`, register it in `parsers/__init__.py` (`detect_site` + `parse_start_list`), and nothing else needs to change.

---

## Data Sources

| Data | Source |
|------|--------|
| UCI rankings | [xcodata.com](https://www.xcodata.com) |
| Start lists | Directly from the provided URL |
