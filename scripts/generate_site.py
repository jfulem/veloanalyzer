#!/usr/bin/env python3
"""
Reads races.yml, fetches and enriches rider data, then writes docs/data.db
for the TypeScript SPA frontend to query via sql.js.
"""

import os
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mtb_analyzer.config import console
from mtb_analyzer.export_db import export_db
from mtb_analyzer.parsers import parse_start_list
from mtb_analyzer.ranking import (build_uci_xco_history, enrich_cp_xco_points,
                                   fetch_cp_xco_standings, get_uci_cache, lookup_rider,
                                   supplement_from_uci_competition,
                                   _lookup_rider_history)

REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_FILE = os.path.join(REPO_ROOT, "races.yml")
DOCS_DIR   = os.path.join(REPO_ROOT, "docs")


def load_races() -> list:
    with open(RACES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f).get("races", [])


def fetch_riders(race: dict, uci_caches: dict) -> list:
    url          = race["url"]
    category     = race.get("category")
    uci_category = race.get("uci_category", "MJ")

    if uci_category not in uci_caches:
        uci_caches[uci_category] = get_uci_cache(uci_category)
    cache = uci_caches[uci_category]

    console.print(f"\n[cyan]Processing:[/cyan] {race.get('name', url)}")
    riders, _ = parse_start_list(url, category)

    if not riders:
        console.print("[yellow]  No riders found — skipping[/yellow]")
        return []

    console.print(f"[green]  ✓ {len(riders)} riders[/green]")
    console.print("[dim]  Looking up UCI rankings and building race histories...[/dim]")

    history_db = build_uci_xco_history(uci_category)
    for rider in riders:
        lookup_rider(rider, cache)
        rider.race_results = _lookup_rider_history(history_db, rider.first_name, rider.last_name)
        if not rider.country and rider.race_results:
            rider.country = next(
                (r.get("nationality", "") for r in rider.race_results if r.get("nationality")),
                "",
            )

    uci_comp_id = race.get("uci_competition_id")
    if uci_comp_id:
        race_year = int(race.get("date", "2026")[:4])
        supplement_from_uci_competition(riders, str(uci_comp_id), race_year, uci_category)

    cp_url = race.get("cp_xco_standings_url")
    if cp_url:
        standings = fetch_cp_xco_standings(cp_url, uci_category)
        enrich_cp_xco_points(riders, standings)

    return riders


def _sd(s: str) -> str:
    """Strip diacritics for cross-race name matching."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_races_html(race_configs: list, rider_groups: list, docs_dir: str) -> None:
    # Per-race stats
    stats = []
    for rc, riders in zip(race_configs, rider_groups):
        ranked = [r for r in riders if r.uci_rank is not None]
        best   = min((r.uci_rank for r in ranked), default=None)
        avg    = round(sum(r.uci_rank for r in ranked) / len(ranked)) if ranked else None
        stats.append({"name": rc.get("name", ""), "date": rc.get("date", ""),
                      "cat": rc.get("category", ""), "total": len(riders),
                      "ranked": len(ranked), "best": best, "avg": avg})

    # Rider → race appearances
    appearances: dict = defaultdict(list)
    for i, riders in enumerate(rider_groups):
        for rider in riders:
            name = (rider.corrected_name or
                    f"{rider.first_name} {rider.last_name}").strip()
            appearances[_sd(name).lower()].append((i, rider, name))

    overlap = sorted(
        ((k, v) for k, v in appearances.items() if len(v) >= 2),
        key=lambda x: (-len(x[1]),
                       min((e[1].uci_rank or 9999 for e in x[1]), default=9999)),
    )

    n = len(race_configs)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Race table ──────────────────────────────────────────────────────────
    race_rows = "".join(
        f"<tr>"
        f"<td>{_esc(s['date'])}</td><td>{_esc(s['name'])}</td>"
        f"<td>{_esc(s['cat'])}</td>"
        f"<td class='num'>{s['total']}</td><td class='num'>{s['ranked']}</td>"
        f"<td class='num'>{'#'+str(s['best']) if s['best'] else '—'}</td>"
        f"<td class='num'>{'#'+str(s['avg']) if s['avg'] else '—'}</td>"
        f"</tr>"
        for s in stats
    )

    # ── Overlap table ────────────────────────────────────────────────────────
    def short_name(rc: dict) -> str:
        n = rc.get("name", "")
        return _esc(n.split(" — ")[-1] if " — " in n else n[:24])

    race_th = "".join(f"<th>{short_name(rc)}</th>" for rc in race_configs)

    overlap_rows = ""
    for _, entries in overlap:
        em = {idx: rider for idx, rider, _ in entries}
        _, first, display = entries[0]
        country = _esc(first.country or "")
        cells = f"<td>{country} {_esc(display)}</td>"
        for idx in range(n):
            if idx in em:
                r = em[idx]
                cells += f"<td class='num'>{'#'+str(r.uci_rank) if r.uci_rank else '—'}</td>"
            else:
                cells += "<td class='num muted'>–</td>"
        overlap_rows += f"<tr>{cells}</tr>"

    if overlap:
        overlap_section = f"""
  <div class="races-section">
    <p class="section-title">Riders in multiple races ({len(overlap)})</p>
    <table class="h2h-table">
      <thead><tr><th>Rider</th>{race_th}</tr></thead>
      <tbody>{overlap_rows}</tbody>
    </table>
  </div>"""
    else:
        overlap_section = '<p class="h2h-empty">No riders appear in multiple races.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>VeloAnalyzer — Race Comparison</title>
  <link rel="stylesheet" href="./index.css">
  <style>
    .back-link {{ display:inline-block; margin-bottom:1.5rem; color:#90cdf4;
                  text-decoration:none; font-size:.9rem; }}
    .back-link:hover {{ text-decoration:underline; }}
    .races-section {{ margin-bottom:2.5rem; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .muted {{ color:#4a5568; }}
  </style>
</head>
<body>
<div class="container">
  <header class="site-header">
    <h1>&#x1F6B5; VeloAnalyzer</h1>
    <p class="header-sub">Race comparison &nbsp;&middot;&nbsp; Updated: {generated_at}</p>
  </header>

  <a class="back-link" href="./index.html">&larr; Home</a>

  <div class="races-section">
    <p class="section-title">Races ({n})</p>
    <table class="h2h-table">
      <thead>
        <tr>
          <th>Date</th><th>Race</th><th>Category</th>
          <th class="num">Riders</th><th class="num">Ranked</th>
          <th class="num">Best</th><th class="num">Avg rank</th>
        </tr>
      </thead>
      <tbody>{race_rows}</tbody>
    </table>
  </div>

  {overlap_section}

  <footer class="site-footer">
    <a href="./app.html">Start list viewer</a> &nbsp;&middot;&nbsp;
    Generated by <a href="https://github.com/jfulem/veloanalyzer" target="_blank">veloanalyzer</a>
  </footer>
</div>
</body>
</html>"""

    out = os.path.join(docs_dir, "races.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    console.print(f"[green]✓ Races page → {out}[/green]")


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    races = load_races()
    if not races:
        console.print("[yellow]No races defined in races.yml[/yellow]")
        return

    console.print(f"[bold cyan]Processing {len(races)} race(s)...[/bold cyan]")
    uci_caches   = {}
    race_configs = []
    rider_groups = []
    for race in races:
        riders = fetch_riders(race, uci_caches)
        race_configs.append(race)
        rider_groups.append(riders)

    db_path = os.path.join(DOCS_DIR, "data.db")
    export_db(race_configs, rider_groups, db_path)
    console.print(f"\n[green]✓ Database written to {db_path}[/green]")

    generate_races_html(race_configs, rider_groups, DOCS_DIR)
    console.print("\n[bold green]Done.[/bold green]")


if __name__ == "__main__":
    main()
