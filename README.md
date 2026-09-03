# VeloAnalyzer

Race analysis for **MTB cross-country** and **cyclo-cross**: tracked start
lists enriched with UCI rank, points and a season of race history, browsable at
**[www.veloanalyzer.com](https://www.veloanalyzer.com)**.

Both disciplines share one database and one site; a switcher in the sidebar
picks between them, and every API route takes `?discipline=XCO|CX`. See
[Disciplines](#disciplines) for what differs between the two.

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

Other optional fields:

| Field | Meaning |
|---|---|
| `discipline` | `XCO` (default, so every existing entry is unchanged) or `CX` |
| `extra_url` | A second start list merged in by name, for races split across two sources |
| `cup_standings_url` | Domestic cup standings page, or a **list** of them tried in order until one has data. Sorts riders the UCI hasn't ranked; in cyclo-cross it sets the grid outright. `cp_xco_standings_url` is the old name and still works |
| `birth_years` | Narrow the start list to these birth years — how a category that shares a course with another is pulled out of it |
| `lat` / `lon` | Explicit coordinates, for a venue the geocoder gets wrong |

`MU23`/`WU23` have no standalone UCI ranking and fall back to Elite
automatically; in cyclo-cross `WJ` does too (see below).

`uci_competition_id` also drives two fallbacks: it reconstructs a past race's
field from official UCI results if the organizer's start list has gone
offline, and it supplies the venue string a `?selectorResult=` (or similar
per-round quirk — see comments next to the Swiss Bike Cup entries) can't.

## Disciplines

`mtb_analyzer/discipline.py` holds everything that differs. The identifiers
elsewhere still say "xco" (`xco_race_id`, `uci_xco_race_results`,
`build_uci_xco_history`) — that is historical, and now reads as "UCI
competition result" for whichever discipline was passed.

|  | MTB XCO | Cyclo-cross |
|---|---|---|
| UCI discipline | `MTB`, race type `XCO` (dataride id 7/92) | `CRO`, race type `CRO-IND` (dataride id 3, no race-type filter) |
| Season | Calendar year | Aug → Feb, filed by the UCI under the **later** year: a race on 5 Dec 2026 is season 2027 |
| Class codes | `1`, `2`, `3`, `HC`, `CS`, `S1`… | `C1`, `C2`, `CDM`, `CM`, `CC`, `CN`, `CMM` |
| Points quota | Best 5 per class, best 4 for juniors (art. 4.16.008) | Everything counts, except men's juniors: best 6 from C1/C2, best 5 from the junior World Cup (art. C1029) |
| Grid order | UCI ranking | The domestic cup standings — art. C0919 lines riders up by "the current standings" of the year-long series |
| Junior women | Their own race and their own ranking | Ranked and (usually) raced with the elite women |

**Junior women in cyclo-cross** are the one genuinely awkward case. Art. C1025
gives the discipline three individual rankings, and junior women sit inside the
women's one; art. C0922 confirms their grid comes from it too. At a class 1 or
2 cup round they also start in the combined "Ženy / U23 / Juniorky" race, with
one classification. So:

* `uci_category: WJ` with `discipline: CX` reads the **Women Elite** ranking
  and history — not the standalone Women Junior ranking dataride publishes,
  which is not what decides anything;
* `birth_years: [2009, 2010]` (the 17- and 18-year-olds of the 2026/27 season)
  pulls them out of the combined start list;
* where a real Women Junior event *does* exist — a national championship, a
  World Cup round — the exact event wins and the combined one is only the
  fallback. That chain lives in `ranking._event_code_for()`.

Cyclo-cross start lists are ordered by cup standing rather than UCI rank, per
the table above. The national championship is gridded differently (art. C0921:
defending champion, then the UCI ranking, then the cup) and is not special-cased
— read its order as indicative and the rank column as authoritative.

The multi-year archive sweep that fills the Archive page is MTB-only unless
`archive_disciplines:` in `races.yml` says otherwise; a discipline's rolling
12-month results are collected either way, because rider histories need them.

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
| `--discipline`, `-d` | `XCO` (default) or `CX` |
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
├── discipline.py                   # per-discipline config: UCI ids, season shape, points rules
├── geocode.py                      # Nominatim lookup for races.yml `location:`
└── parsers/                          # one module per start-list site
scripts/
├── ingest.py                # CLI wrapper around mtb_analyzer.ingest (needs DATABASE_URL)
├── sync_races.py            # pulls upcoming races from cycling.sportsoft.cz into races.yml
└── discover_races.py        # finds untracked UCI XCO competitions, appends stub entries
worker/src/index.ts        # Cloudflare Worker: read API on /api/*, serves frontend/'s build too
frontend/                  # TypeScript + Vite multi-page site (index/app/results/races/riders/about)
frontend/src/discipline.ts # active discipline: URL param + sidebar switcher, threaded onto every API call
migrations/                # Alembic
```

## Data sources

| Data | Source |
|---|---|
| UCI rankings & race history | [dataride.uci.ch](https://dataride.uci.ch), [uci.org](https://www.uci.org) |
| Czech Cup XCO standings | [cpxcmtb.sportsoft.cz](https://cpxcmtb.sportsoft.cz) |
| Czech Cup cyclo-cross standings (JANEV Cup, formerly HSF System Cup) | [cpcx.sportsoft.cz](https://cpcx.sportsoft.cz) |
| Race venue coordinates | [Nominatim](https://nominatim.openstreetmap.org) (OpenStreetMap) |
| Start lists | Directly from each race's `url:` in `races.yml` |
