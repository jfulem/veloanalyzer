#!/usr/bin/env python3
"""
Reads races.yml, fetches and enriches rider data, then writes docs/data.db
for the TypeScript SPA frontend to query via sql.js.
"""

import os
import sys
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


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_UCI_CAT_COLOR = {
    "ME": "#68d391",  # green
    "MJ": "#90cdf4",  # blue
    "WE": "#f6ad55",  # orange
    "WJ": "#f687b3",  # pink
}
_UCI_CAT_LABEL = {
    "ME": "Men Elite", "MJ": "Men Juniors",
    "WE": "Women Elite", "WJ": "Women Juniors",
}


def _cat_badge(uci_cat: str) -> str:
    color = _UCI_CAT_COLOR.get(uci_cat, "#a0aec0")
    label = _esc(uci_cat or "—")
    return (f"<span class='cat-badge' style='background:{color}22; "
            f"color:{color}; border:1px solid {color}66'>{label}</span>")


def generate_races_html(race_configs: list, rider_groups: list, docs_dir: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Per-race stats
    stats = []
    for rc, riders in zip(race_configs, rider_groups):
        ranked = [r for r in riders if r.uci_rank is not None]
        best   = min((r.uci_rank for r in ranked), default=None)
        avg    = round(sum(r.uci_rank for r in ranked) / len(ranked)) if ranked else None
        stats.append({"name": rc.get("name", ""), "date": rc.get("date", ""),
                      "cat": rc.get("category", ""), "uci_cat": rc.get("uci_category", ""),
                      "slug": rc.get("output", "").removesuffix(".html"),
                      "total": len(riders), "ranked": len(ranked),
                      "best": best, "avg": avg})

    upcoming = sorted((s for s in stats if s["date"] >= today), key=lambda s: s["date"])
    past     = sorted((s for s in stats if s["date"] < today), key=lambda s: s["date"], reverse=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def rows_html(rows: list) -> str:
        return "".join(
            f"<tr data-cat='{_esc(s['uci_cat'])}'>"
            f"<td>{_esc(s['date'])}</td>"
            f"<td><a href='./app.html#race={_esc(s['slug'])}'>{_esc(s['name'])}</a></td>"
            f"<td>{_cat_badge(s['uci_cat'])} {_esc(s['cat'])}</td>"
            f"<td class='num'>{s['total']}</td><td class='num'>{s['ranked']}</td>"
            f"<td class='num'>{'#'+str(s['best']) if s['best'] else '—'}</td>"
            f"<td class='num'>{'#'+str(s['avg']) if s['avg'] else '—'}</td>"
            f"</tr>"
            for s in rows
        )

    def table_section(title: str, rows: list) -> str:
        if not rows:
            body = '<p class="h2h-empty">None.</p>'
        else:
            body = f"""<table class="h2h-table">
      <thead>
        <tr>
          <th>Date</th><th>Race</th><th>Category</th>
          <th class="num">Riders</th><th class="num">Ranked</th>
          <th class="num">Best</th><th class="num">Avg rank</th>
        </tr>
      </thead>
      <tbody>{rows_html(rows)}</tbody>
    </table>"""
        return f"""
  <div class="races-section">
    <p class="section-title">{title} ({len(rows)})</p>
    {body}
  </div>"""

    legend = "".join(
        f"<button class='legend-item' data-cat='{c}'>{_cat_badge(c)} {label}</button>"
        for c, label in _UCI_CAT_LABEL.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>VeloAnalyzer — Race Comparison</title>
  <link rel="stylesheet" href="./index.css">
  <style>
    .races-section {{ margin-bottom:2.5rem; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .cat-badge {{ display:inline-block; border-radius:4px; padding:1px 6px;
                  font-size:.72rem; font-weight:600; white-space:nowrap; }}
    .cat-legend {{ margin-bottom:1.5rem; display:flex; gap:.6rem; flex-wrap:wrap; }}
    .legend-item {{
      font-size:.82rem; color:#a0aec0; display:flex; align-items:center; gap:.4rem;
      background:transparent; border:1px solid transparent; border-radius:6px;
      padding:.25rem .5rem; cursor:pointer; font-family:inherit;
    }}
    .legend-item:hover {{ border-color:#4a5568; }}
    .legend-item.active {{ border-color:#90cdf4; background:#2d3748; color:#e2e8f0; }}
  </style>
</head>
<body>
<div class="container">
  <header class="site-header">
    <h1>&#x1F6B5; VeloAnalyzer</h1>
    <p class="header-sub">Race comparison &nbsp;&middot;&nbsp; Updated: {generated_at}</p>
  </header>

  <a class="back-link" href="./index.html">&larr; Home</a>

  <div class="cat-legend">{legend}</div>

  {table_section("Upcoming races", upcoming)}
  {table_section("Past races", past)}

  <footer class="site-footer">
    <a href="./app.html">Start list viewer</a> &nbsp;&middot;&nbsp;
    Generated by <a href="https://github.com/jfulem/veloanalyzer" target="_blank">veloanalyzer</a>
  </footer>
</div>
<script>
  document.querySelectorAll('.legend-item').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var cat = btn.dataset.cat;
      var wasActive = btn.classList.contains('active');
      document.querySelectorAll('.legend-item').forEach(function (b) {{ b.classList.remove('active'); }});
      document.querySelectorAll('tr[data-cat]').forEach(function (tr) {{ tr.style.display = ''; }});
      if (!wasActive) {{
        btn.classList.add('active');
        document.querySelectorAll('tr[data-cat]').forEach(function (tr) {{
          if (tr.dataset.cat !== cat) tr.style.display = 'none';
        }});
      }}
    }});
  }});
</script>
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
