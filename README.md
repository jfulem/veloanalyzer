# VeloAnalyzer

A tool for analysing MTB cross-country race start lists. It fetches registered riders, enriches them with UCI ranking data and full race history, and powers a web frontend for browsing, comparing, and doing head-to-head analysis.

---

## How it works

```
races.yml
    │
    ▼
scripts/generate_site.py          ← main pipeline
    │  fetches start lists
    │  looks up UCI rankings (dataride.uci.ch)
    │  builds 12-month race history from all UCI XCO results
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
  uci_category: MJ                # which UCI ranking to use (MJ/WJ/ME/WE/MU23/WU23)
  cp_xco_standings_url: https://cpxcmtb.sportsoft.cz/2026/results.aspx  # optional
  uci_competition_id: 77488       # optional — forces supplement for very recent races
  extra_url: https://...          # optional — second start list, merged with url
  output: bedrichov-2026-mj.html  # slug for the frontend
```

**Optional fields:**

- `cp_xco_standings_url` — when set, unranked riders are sorted by Czech Cup XCO standings instead of alphabetically.
- `uci_competition_id` — UCI competition ID (from the URL on uci.org). Only needed for races that finished within the past week, before the catalog cache has refreshed. Older completed races are picked up automatically.
- `extra_url` — a second start-list URL to merge in, for races that split entries across two sources (e.g. a domestic registration site for local riders plus a separate Google Sheet for foreign entries). Parsed with the same `category` filter as `url`; riders already present (matched by name) aren't duplicated.

`MU23`/`WU23` (Men/Women U23) have no standalone official UCI ranking — UCI rank/points lookup for these automatically falls back to the Elite (ME/WE) ranking, since U23-eligible riders are officially ranked there. Start-list filtering still works normally, since many start lists do register U23 as its own field.

---

## Running the pipeline

`docs/` is generated and gitignored — on a fresh clone it's empty until you build it:

```bash
# Install dependencies
pip install -e .          # or: uv sync
cd frontend && npm install && cd ..

# Build the frontend (docs/app.html, docs/app-[hash].js, docs/index.css, docs/index.html)
cd frontend && npm run build && cd ..

# Rebuild docs/data.db and docs/races.html from races.yml
python scripts/generate_site.py
```

The script fetches each start list, looks up UCI rankings, downloads the last 12 months of XCO race results from the UCI (all finishers, including zero-point), and writes everything to `docs/data.db`. A `.mtb_cache/` folder caches all network responses so re-runs are fast.

**First run** fetches event codes for all UCI XCO competitions in the past 12 months (~2–3 minutes). Subsequent runs are near-instant since all results are cached.

In production, CI (`.github/workflows/generate-reports.yml`) runs both steps on every push and deploys the result to GitHub Pages — there's no need to commit `docs/` manually.

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

Non-English category words (e.g. German *Junioren*, Hungarian *Elit*, Czech *Junioři*) are normalised to English automatically.

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
| hynekmusil.cz | Czech events; URL unlock parameter added automatically |
| temposport.hu | Hungarian events; Hungarian name order handled |
| bike-revolution.ch | Delegates to embedded RaceResult widget once start list is published |
| Google Sheets (pubhtml) | Croatian/regional events |
| Generic fallback | Table scraper |

### my.raceresult.com

The parser auto-detects two modes:

- **Results mode** (`showResults=true`) — fetches the results list; gender comes from subgroup names.
- **Participants mode** (`showParticipants=true`, results not yet published) — fetches `/{event_id}/participants/list`; gender and column layout are read from `DataFields`. Categories are built as `"{gender} {contest name}"` (e.g. `Men XCO UCI C1`).

Pass the `/participants` URL for both modes — the parser picks the right API automatically.

### bike-revolution.ch

The start list is embedded via a RaceResult.com widget injected by Storyblok CMS when officially published (typically 5–7 days before the race). The parser auto-detects the RaceResult event ID from the DOM and delegates to the raceresult parser. Until the list is published, it returns no riders.

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
- **Rider card** — opens on click; shows UCI rank, birth year, team, nationality, and full race history (last 12 months, all finishes including zero-point)
- **Head-to-head comparison** — select any two riders in the same table to see their shared race record, sorted newest to oldest
- **Country chart** — breakdown of starters by nationality
- **Team chart** — breakdown by team
- **Stat cards** — total starters, ranked count, best rank, average rank, TOP 50/100/200, total UCI points

---

## Race history

Race history is sourced directly from the UCI via `dataride.uci.ch` and `uci.org`:

- **All finishers** are included, not just riders who scored UCI points
- **Finish times** are taken from the official UCI event results
- **Coverage**: all UCI XCO competitions (C1–C3, World Cup, Continental Championships, etc.) in the past 12 months
- **Name matching**: diacritic-stripped fallback ensures riders with accented names (e.g. *Milán Podgorník*) are matched regardless of start list encoding

This means H2H comparisons show every race where two riders competed against each other, even if neither scored points.

---

## Caching

All network responses are cached in `.mtb_cache/`:

| Cache type | TTL |
|-----------|-----|
| UCI rankings | 7 days |
| UCI competition catalog | 7 days |
| UCI event codes per competition | permanent (past results don't change) |
| UCI event results | weekday-aware: Mon–Fri outside summer = same week; weekends / July–August = 1–2 days |
| Czech Cup standings | same as event results |

---

## Project structure

```
races.yml                        # race configuration
main.py                          # interactive CLI entry point
scripts/
├── generate_site.py             # pipeline: races.yml → docs/data.db, docs/races.html, docs/index.html
├── sync_races.py                # syncs upcoming races from cycling.sportsoft.cz into races.yml
└── discover_races.py            # finds new UCI XCO competitions, stages them as stub entries
mtb_analyzer/
├── config.py                    # constants (flags, country maps, category aliases)
├── models.py                    # Rider dataclass
├── utils.py                     # fetch, normalize_*, category_matches
├── ranking.py                   # UCI ranking cache/lookup, race history, Czech Cup standings
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
    ├── hynekmusil.py
    ├── temposport.py
    ├── bike_revolution.py
    ├── gsheets.py
    ├── raceresult.py
    └── generic.py               # generic table fallback
frontend/                        # TypeScript SPA
├── app.html                     # SPA entry template (built into docs/app.html)
└── src/
docs/                            # generated — not committed to git
├── data.db                      # SQLite database (generate_site.py)
├── index.html                   # landing page dashboard (generate_site.py)
├── races.html                   # race calendar overview (generate_site.py)
├── app.html                     # SPA (built from frontend/app.html)
└── app-[hash].js                # compiled frontend bundle (content-hashed)
.mtb_cache/                      # auto-created network cache
```

`docs/` is rebuilt from scratch by CI on every push (see `.github/workflows/generate-reports.yml`) and is gitignored locally — there's no need to commit it. To preview locally, run both build steps (`npm run build` in `frontend/`, then `python scripts/generate_site.py`) and serve the `docs/` folder.

### Landing page (`docs/index.html`)

Generated by `generate_site.py` alongside `data.db` and `races.html` — shows live
stats (races tracked, riders tracked, days until the next race) and a preview of the
next few upcoming races, each linking directly into the start list viewer.

### Discovering new races (`scripts/discover_races.py`)

The UCI calendar API can tell us about every upcoming XCO competition (name, dates,
venue, country, competition ID) but not the actual start-list registration URL —
that lives on whichever third-party platform (RaceResult, sportsoft.cz, etc.) the
organizer happens to use, which UCI doesn't expose. So this script can't fully
populate `races.yml` the way `sync_races.py` does; instead it finds competitions not
yet tracked (scoped to the `discovery_countries:` list in `races.yml`) and appends
them as commented-out stub entries — with name/date/venue/competition ID already
filled in, plus the organizer's website as a hint — for you to complete by finding
the real start-list URL and uncommenting.

```bash
python scripts/discover_races.py
```

Safe to re-run: it never rewrites `races.yml`, only appends, and skips anything
already tracked (by competition ID or fuzzy name match) or already discovered in a
previous run.

To add a new website parser: create a file in `mtb_analyzer/parsers/`, register it in `parsers/__init__.py` (`detect_site` + `parse_start_list`).

---

## Data sources

| Data | Source |
|------|--------|
| UCI rankings | [dataride.uci.ch](https://dataride.uci.ch) |
| Race history (all finishers + times) | [uci.org](https://www.uci.org) competition results |
| Czech Cup XCO standings | [cpxcmtb.sportsoft.cz](https://cpxcmtb.sportsoft.cz) |
| Start lists | Directly from the URL in `races.yml` |
