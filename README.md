# VeloAnalyzer

MTB cross-country race analysis: tracked start lists enriched with UCI rank,
points and a season of race history, browsable at
**[www.veloanalyzer.com](https://www.veloanalyzer.com)**.

## How it works

```
races.yml  ──▶  ingest (GitHub Actions, daily)  ──▶  Neon Postgres  ──▶  Cloudflare Worker
                 mtb_analyzer/pipeline.py              (derived data,       /api/* + static site
                 scrapes each start list,               rebuildable          (frontend/, Vite)
                 enriches from the UCI,                 from races.yml)
                 geocodes venues
```

One Worker serves the built frontend and the read API from the same origin —
see [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full runbook (accounts, secrets,
rollback, local dev). `main.py` is a separate, standalone CLI for analysing a
one-off start list URL that isn't in `races.yml` — the Worker architecture
can't do that on demand, so it stays local-only.

## `races.yml`

One entry per race **and** category (a race with 4 categories is 4 entries
sharing a `url:`):

```yaml
races:
- url: https://registrace.sportsoft.cz/startlist.aspx?e=3545
  name: ČP XCO Bedřichov 2026 — Men Juniors
  date: '2026-06-06'
  category: Men Juniors           # filter passed to the parser
  uci_category: MJ                # MJ/WJ/ME/WE/MU23/WU23 — which UCI ranking to use
  uci_competition_id: 77488       # optional — see below
  location: "Bedřichov, Czech Republic"  # optional — geocoded for the home page map
  output: bedrichov-2026-mj.html  # slug
```

Other optional fields: `extra_url` (a second start list merged in by name, for
races split across two sources), `cp_xco_standings_url` (sorts unranked riders
by Czech Cup standings instead of alphabetically). `MU23`/`WU23` have no
standalone UCI ranking and fall back to Elite automatically.

`uci_competition_id` also drives two fallbacks: it reconstructs a past race's
field from official UCI results if the organizer's start list has gone
offline, and it supplies the venue string a `?selectorResult=` (or similar
per-round quirk — see comments next to the Swiss Bike Cup entries) can't.

## Running the ingest locally

```bash
uv sync                                    # or: pip install -e .
export DATABASE_URL=postgresql://...       # Neon connection string
uv run alembic upgrade head                # once, or after a schema change
uv run python scripts/ingest.py
```

Network responses are cached in `.mtb_cache/` (UCI rankings, competition
results, geocoding) so re-runs are fast; a cold run takes ~10 minutes.

```bash
cd frontend && npm install && npm run dev  # Vite dev server, proxies /api → :8787
cd worker && npx wrangler dev              # Worker locally, same origin as prod
```

## CLI tool (`main.py`)

One-off analysis of a single start list, independent of `races.yml`:

```bash
python main.py --url "https://my.raceresult.com/381877/participants" --category "Men XCO UCI C1"
python main.py --compare "https://race1..." "https://race2..." --category "Junior" --uci-category MJ
python main.py --url "https://..." --category "Junior" --export report.html   # or .csv
```

| Option | Description |
|---|---|
| `--url` / `--compare URL1 URL2` | Analyse one race or compare two |
| `--category`, `-c` | Word-boundary category filter, e.g. `"Men Juniors"` (not `"Women Juniors"`); non-English words (*Junioren*, *Junioři*, *Elit*...) normalize automatically |
| `--uci-category`, `-u` | `MJ`/`WJ`/`ME`/`WE`/`MU23`/`WU23` |
| `--refresh-cache` | Force re-download of the UCI ranking |
| `--export FILE` | `.html` or `.csv` |
| `--no-lookup` | Skip UCI lookup — start list only |

## Supported start-list sites

`mtb_analyzer/parsers/`, auto-detected by URL: `sportsoft.cz` (Czech/Slovak),
`my.raceresult.com` (JSON API — auto-detects participants vs. results mode,
and handles season-long projects with one event ID per stage via `?list=` or
`?selectorResult=`), `sportzeitnehmung.at`, `runtix.com`, `sportkrono.hu`,
`hynekmusil.cz`, `temposport.hu`, `bike-revolution.ch` (delegates to an
embedded RaceResult widget), `stoperica.com`, `wowtiming.com`, Google Sheets
(`pubhtml`), and a generic table-scraper fallback. To add a site, drop a
parser in `mtb_analyzer/parsers/` and register it in `parsers/__init__.py`.

## Project structure

```
races.yml                  # race configuration — the source of truth
main.py                    # standalone CLI (see above)
mtb_analyzer/
├── pipeline.py             # fetch + enrich one race (shared by ingest and, later, on-demand jobs)
├── ingest.py                # races.yml → pipeline → store, for every tracked race
├── store.py                  # Postgres upserts; rider identity resolution
├── schema.py, db.py            # SQLAlchemy schema + engine
├── ranking.py                    # UCI ranking cache, race history, points-quota rules
├── geocode.py                      # Nominatim lookup for races.yml `location:`
└── parsers/                          # one module per start-list site
scripts/
├── ingest.py                # CLI wrapper around mtb_analyzer.ingest (needs DATABASE_URL)
├── sync_races.py            # pulls upcoming races from cycling.sportsoft.cz into races.yml
└── discover_races.py        # finds untracked UCI XCO competitions, appends stub entries
worker/src/index.ts        # Cloudflare Worker: read API on /api/*, serves frontend/'s build too
frontend/                  # TypeScript + Vite multi-page site (index/app/results/races/riders/about)
migrations/                # Alembic
```

## Data sources

| Data | Source |
|---|---|
| UCI rankings & race history | [dataride.uci.ch](https://dataride.uci.ch), [uci.org](https://www.uci.org) |
| Czech Cup XCO standings | [cpxcmtb.sportsoft.cz](https://cpxcmtb.sportsoft.cz) |
| Race venue coordinates | [Nominatim](https://nominatim.openstreetmap.org) (OpenStreetMap) |
| Start lists | Directly from each race's `url:` in `races.yml` |
