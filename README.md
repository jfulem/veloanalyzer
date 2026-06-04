# VeloAnalyzer

A tool for analysing MTB cross-country race start lists. It fetches registered riders, enriches them with UCI ranking data and race history, and powers a web frontend for browsing, comparing, and doing head-to-head analysis.

---

## How it works

```
races.yml
    │
    ▼
scripts/generate_site.py          ← main pipeline
    │  fetches start lists
    │  looks up UCI rankings (xcodata.com)
    │  fetches rider race history
    │  enriches with Czech Cup standings (optional)
    │
    ▼
docs/data.db  (SQLite)
    │
    ▼
frontend/  (TypeScript SPA, served via GitHub Pages)
```

`races.yml` defines which races to process. Running `generate_site.py` rebuilds the SQLite database read by the frontend.

---

## races.yml

Each entry in `races.yml` has:

```yaml
races:
- url: https://registrace.sportsoft.cz/startlist.aspx?e=3545
  name: ČP XCO Bedřichov 2026 — Men Juniors
  date: '2026-06-06'
  category: Men Juniors           # passed to the parser as a filter
  uci_category: MJ                # which UCI ranking to use (MJ/WJ/ME/WE)
  cp_xco_standings_url: https://cpxcmtb.sportsoft.cz/2026/results.aspx  # optional
  output: bedrichov-2026-mj.html  # slug for the frontend
```

`cp_xco_standings_url` is optional. When set, unranked riders are sorted by their Czech Cup XCO standings points instead of alphabetically.

---

## Running the pipeline

```bash
# Install dependencies
pip install -e .          # or: uv sync

# Rebuild docs/data.db from races.yml
python scripts/generate_site.py
```

The script fetches each race, looks up UCI rankings, downloads rider race histories from xcodata.com, and writes everything to `docs/data.db`. A `.mtb_cache/` folder caches network responses so re-runs are fast.

---

## CLI tool (`main.py`)

An interactive command-line tool for one-off analysis of any start list URL, without touching `races.yml`.

```bash
# Analyse a race — terminal output
python main.py --url "https://my.raceresult.com/381877/participants" \
               --category "Men XCO UCI C1"

# Export as self-contained HTML report
python main.py --url "https://www.sportzeitnehmung.at/.../registrants-list.html" \
               --category "Men Juniors" --export report.html

# Compare two start lists → single HTML file
python main.py --compare "https://race1..." "https://race2..." \
               --category "Junior" --uci-category MJ --export comparison.html

# Force-refresh the cached UCI ranking
python main.py --refresh-cache --uci-category WJ
```

### Options

| Option | Short | Description |
|--------|-------|-------------|
| `--url URL` | | URL of the start list to analyse |
| `--compare URL1 URL2` | | Compare two start lists side by side |
| `--category TEXT` | `-c` | Category filter (word-boundary matching) |
| `--uci-category` | `-u` | `MJ` `WJ` `ME` `WE` (default: `MJ`) |
| `--refresh-cache` | | Force re-download of UCI ranking |
| `--export FILE` | | Export to `.html` or `.csv` |
| `--no-lookup` | | Skip UCI lookup — parse start list only |

---

## Category filter

The `--category` filter uses word-boundary matching. It also requires the same number of words as the target category, so `Men XCO UCI C3` will not accidentally match `Men XCO UCI C3 Short`.

```bash
--category "Men Juniors"       # matches "Men Juniors" but not "Women Juniors"
--category "Junior"            # matches both "Men Juniors" and "Women Juniors"
--category "Men XCO UCI C1"    # matches exactly, not "Men XCO UCI C1 Short"
```

Non-English category words (e.g. German *Junioren*, Hungarian *Elit*) are normalised to English automatically.

---

## Supported start list websites

| Website | Notes |
|---------|-------|
| sportzeitnehmung.at | UCI ID available; paginated |
| runtix.com | Fuzzy name matching |
| sportkrono.hu | AJAX-based |
| my.raceresult.com | JSON API; auto-detects results mode vs participants mode |
| sportsoft.cz | Czech/Slovak events |
| stoperica.com | Regional events |
| wowtiming.com | Regional events |
| Google Sheets (pubhtml) | Croatian/regional events |
| Generic fallback | Table scraper |

### my.raceresult.com

The parser auto-detects two modes:

- **Results mode** (`showResults=true`) — fetches the results list; gender comes from subgroup names.
- **Participants mode** (`showParticipants=true`, results not yet published) — fetches `/{event_id}/participants/list`; gender and column layout are read from `DataFields`. Categories are built as `"{gender} {contest name}"` (e.g. `Men XCO UCI C1`).

Pass the `/participants` URL for both modes — the parser picks the right API automatically.

---

## Sorting

Riders are sorted:

1. **Ranked riders** — by UCI rank (ascending)
2. **Unranked riders** — by Czech Cup XCO standings points (descending) if `cp_xco_standings_url` is set, then alphabetically

The Czech Cup standings are fetched per-category (Juniors M/W, Elite M/W) from `cpxcmtb.sportsoft.cz`.

---

## Frontend features

The TypeScript SPA reads `docs/data.db` via sql.js and provides:

- **Start list table** — colour-coded by UCI rank tier (TOP 50 / TOP 51–200 / Ranked 201+ / Unranked), with live search
- **Rider card** — opens on click; shows UCI rank, birth year, team, nationality, and full race history
- **Head-to-head comparison** — select any two riders in the same table to see their shared race record
- **Country chart** — breakdown of starters by nationality
- **Team chart** — breakdown by team
- **Stat cards** — total starters, ranked count, best rank, average rank, TOP 50/100/200, total and top-10 UCI points

---

## Caching

All network responses are cached in `.mtb_cache/`:

| Cache type | TTL |
|-----------|-----|
| UCI rankings | 7 days |
| Rider race histories | weekday-aware: Mon–Fri outside summer = same week; weekends / July–August = 1–2 days |
| Race pages (for supplementing history) | same as rider histories |
| Czech Cup standings | same as rider histories |

---

## Project structure

```
races.yml                        # race configuration
main.py                          # interactive CLI entry point
scripts/
├── generate_site.py             # pipeline: races.yml → docs/data.db
└── sync_races.py                # syncs upcoming races from cycling.sportsoft.cz into races.yml
mtb_analyzer/
├── config.py                    # constants (flags, country maps, category aliases)
├── models.py                    # Rider dataclass
├── utils.py                     # fetch, normalize_*, category_matches
├── ranking.py                   # UCI ranking cache/lookup, xcodata.com history, Czech Cup standings
├── display.py                   # terminal output, sort_riders, race_quality_stats
├── export.py                    # HTML and CSV export (CLI)
├── export_db.py                 # SQLite export (pipeline)
└── parsers/
    ├── __init__.py              # detect_site + parse_start_list
    ├── sportzeitnehmung.py
    ├── runtix.py
    ├── sportkrono.py
    ├── sportsoft.py
    ├── stoperica.py
    ├── wowtiming.py
    ├── gsheets.py
    ├── raceresult.py
    └── generic.py               # generic table fallback
frontend/                        # TypeScript SPA
docs/
├── data.db                      # generated SQLite database
└── index.js                     # compiled frontend bundle
.mtb_cache/                      # auto-created network cache
```

To add a new website parser: create a file in `mtb_analyzer/parsers/`, register it in `parsers/__init__.py` (`detect_site` + `parse_start_list`).

---

## Data sources

| Data | Source |
|------|--------|
| UCI rankings & race history | [xcodata.com](https://www.xcodata.com) |
| Czech Cup XCO standings | [cpxcmtb.sportsoft.cz](https://cpxcmtb.sportsoft.cz) |
| Start lists | Directly from the URL in `races.yml` |
