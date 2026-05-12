import csv
import json
import os
from collections import Counter
from datetime import datetime
from typing import Optional

from .config import IOC_TO_ISO2, console


def _flag_img(country: str) -> str:
    iso2 = IOC_TO_ISO2.get(country, "")
    if not iso2:
        return ""
    return f'<img src="https://flagcdn.com/16x12/{iso2}.png" alt="{country}" style="vertical-align:middle">'
from .display import race_quality_stats, sort_riders
from .models import Rider


def rank_tier(uci_rank: Optional[int]) -> str:
    if uci_rank and uci_rank <= 50:  return "tier-top50"
    if uci_rank and uci_rank <= 200: return "tier-top200"
    if uci_rank:                     return "tier-ranked"
    return "tier-unranked"


def export_csv(riders: list, path: str):
    sorted_riders = sort_riders(riders)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "First name", "Last name", "Country",
                          "UCI rank", "UCI points", "UCI ID",
                          "Team", "Category", "Birth year"])
        for i, r in enumerate(sorted_riders, 1):
            writer.writerow([i, r.first_name, r.last_name, r.country,
                              r.uci_rank or "", r.uci_points or 0,
                              r.uci_id, r.team, r.category, r.birth_year])
    console.print(f"[green]✓ CSV exported to {path}[/green]")


def export_html(riders: list, race_name: str, uci_cat: str, path: str,
                compare_data: tuple = None, race_date: str = ""):
    """
    Exports a polished, self-contained HTML report.
    If compare_data=(riders2, name2, url2, url1) is provided, a comparison
    section is appended at the end of the file.
    """
    sorted_riders  = sort_riders(riders)
    country_counts = Counter(r.country for r in sorted_riders)
    stats          = race_quality_stats(riders)
    generated_at   = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Global index map for H2H (data-ridx must match position in riders_json)
    global_idx = {id(r): i for i, r in enumerate(sorted_riders)}

    def rider_row(sec_rank: int, r: Rider, ridx: int) -> str:
        tier        = rank_tier(r.uci_rank)
        rank_disp   = str(r.uci_rank)   if r.uci_rank   else "—"
        pts_disp    = str(r.uci_points) if r.uci_points else "0"
        conf_badge  = ""
        if r.match_confidence < 100 and r.uci_rank:
            conf_badge = f'<span class="conf-badge">{r.match_confidence}%</span>'
        display_name = r.corrected_name if r.corrected_name else r.full_name
        xco_link = (
            f' <a class="xco-link" href="https://www.xcodata.com{r.xcodata_slug}"'
            f' target="_blank" onclick="event.stopPropagation()">↗</a>'
            if r.xcodata_slug else ""
        )
        return (
            f'<tr class="{tier}" data-ridx="{ridx}" onclick="selectRider({ridx})">'
            f'<td class="num">{sec_rank}</td>'
            f'<td class="name">{display_name}{conf_badge}{xco_link}</td>'
            f'<td class="country">{_flag_img(r.country)} {r.country}</td>'
            f'<td class="rank">{rank_disp}</td>'
            f'<td class="pts">{pts_disp}</td>'
            f'<td class="uci-id">{r.uci_id if r.uci_id else "—"}</td>'
            f'<td class="team">{r.team[:50] if r.team else "—"}</td>'
            f'</tr>\n'
        )

    # Detect multi-race: distinct non-empty race_name values
    race_keys = list(dict.fromkeys(r.race_name for r in sorted_riders if r.race_name))
    multi_race = len(race_keys) > 1

    riders_json = json.dumps([{
        "name":    r.corrected_name or r.full_name,
        "rank":    r.uci_rank,
        "points":  r.uci_points or 0,
        "country": r.country,
        "flag":    IOC_TO_ISO2.get(r.country, ""),
        "results": r.race_results,
    } for r in sorted_riders], ensure_ascii=False)

    total     = len(sorted_riders)
    max_count = max(country_counts.values(), default=1)
    country_rows = ""
    for country, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        pct      = count / total * 100
        bar_pct  = count / max_count * 100
        country_rows += (
            f'<tr>'
            f'<td class="c-flag">{_flag_img(country)} {country}</td>'
            f'<td class="c-count">{count}</td>'
            f'<td class="c-bar-cell">'
            f'  <div class="c-bar" style="width:{bar_pct:.1f}%"></div>'
            f'  <span class="c-pct">{pct:.0f}%</span>'
            f'</td>'
            f'</tr>\n'
        )

    def stat_card(label: str, value, sub: str = "") -> str:
        sub_html = f'<div class="card-sub">{sub}</div>' if sub else ""
        return (f'<div class="stat-card">'
                f'<div class="card-val">{value}</div>'
                f'<div class="card-label">{label}</div>'
                f'{sub_html}</div>\n')

    avg_str   = f"{stats['avg_rank']:.0f}" if stats["avg_rank"] else "—"
    stat_cards = (
        stat_card("Total starters",  stats["total"])  +
        stat_card("Ranked riders",   stats["ranked"]) +
        stat_card("Best UCI rank",   stats["best_rank"] or "—") +
        stat_card("Avg UCI rank",    avg_str, "(ranked only)") +
        stat_card("TOP 50",          stats["top50"]) +
        stat_card("TOP 100",         stats["top100"]) +
        stat_card("TOP 200",         stats["top200"]) +
        stat_card("Total UCI pts",   stats["total_pts"]) +
        stat_card("TOP-10 pts",      stats["top10_pts"], "(top 10 riders)")
    )

    TABLE_HEAD = ('<thead><tr>'
                  '<th>#</th><th>Name</th><th>Country</th>'
                  '<th>UCI rank</th><th>UCI pts</th><th>UCI ID</th><th>Team</th>'
                  '</tr></thead>')

    if multi_race:
        start_list_block = ""
        for rk in race_keys:
            group = [r for r in sorted_riders if r.race_name == rk]
            gs    = race_quality_stats(group)
            g_avg = f"{gs['avg_rank']:.0f}" if gs["avg_rank"] else "—"
            g_stat_cards = (
                stat_card("Starters",   gs["total"]) +
                stat_card("Ranked",     gs["ranked"]) +
                stat_card("Best rank",  gs["best_rank"] or "—") +
                stat_card("Avg rank",   g_avg, "(ranked only)") +
                stat_card("TOP 50",     gs["top50"]) +
                stat_card("TOP 100",    gs["top100"]) +
                stat_card("Total pts",  gs["total_pts"])
            )
            group_rows = "".join(
                rider_row(sec_rank, r, global_idx[id(r)])
                for sec_rank, r in enumerate(sort_riders(group), 1)
            )
            start_list_block += (
                f'\n  <section class="race-section">'
                f'\n    <h2 class="race-section-title">{rk}</h2>'
                f'\n    <div class="stats-grid">{g_stat_cards}</div>'
                f'\n    <div class="rider-table-wrap">'
                f'\n      <table class="rider-table">{TABLE_HEAD}'
                f'\n        <tbody>{group_rows}</tbody>'
                f'\n      </table></div>'
                f'\n  </section>'
            )
    else:
        rows_html = "".join(
            rider_row(i, r, i - 1) for i, r in enumerate(sorted_riders, 1)
        )
        start_list_block = (
            f'\n  <div class="section-title">Start List</div>'
            f'\n  <div class="rider-table-wrap">'
            f'\n    <table class="rider-table" id="riderTable">{TABLE_HEAD}'
            f'\n      <tbody>\n{rows_html}      </tbody>'
            f'\n    </table>'
            f'\n  </div>'
        )

    comparison_html = ""
    if compare_data:
        riders2, name2, url2, url1 = compare_data
        stats2 = race_quality_stats(riders2)

        def qs(s):
            return (s["top10_pts"]*3 + s["top50"]*10 +
                    s["top100"]*5 + s["top200"]*2 + s["ranked"])

        sc1, sc2 = qs(stats), qs(stats2)

        if   sc1 > sc2: verdict_txt = f"🏆 Race 1 has a stronger field (score +{sc1-sc2})"
        elif sc2 > sc1: verdict_txt = f"🏆 Race 2 has a stronger field (score +{sc2-sc1})"
        else:           verdict_txt = "⚖ Both races are of comparable quality"

        def cmp_row(label, v1, v2, higher=True):
            try:
                iv1 = int(str(v1).replace("—", "0"))
                iv2 = int(str(v2).replace("—", "0"))
                c1  = ' class="win"' if (iv1 > iv2 if higher else iv1 < iv2) else ""
                c2  = ' class="win"' if (iv2 > iv1 if higher else iv2 < iv1) else ""
            except (ValueError, TypeError):
                c1 = c2 = ""
            return f'<tr><td>{label}</td><td{c1}>{v1}</td><td{c2}>{v2}</td></tr>\n'

        avg1 = f"{stats['avg_rank']:.0f}"  if stats["avg_rank"]  else "—"
        avg2 = f"{stats2['avg_rank']:.0f}" if stats2["avg_rank"] else "—"

        top5_r1 = sorted([r for r in riders  if r.uci_rank], key=lambda r: r.uci_rank)[:5]
        top5_r2 = sorted([r for r in riders2 if r.uci_rank], key=lambda r: r.uci_rank)[:5]

        def top5_html(top5):
            rows = ""
            for r in top5:
                rows += (f'<tr><td class="rank">{r.uci_rank}</td>'
                         f'<td class="name">{r.full_name}</td>'
                         f'<td class="pts">{r.uci_points}</td>'
                         f'<td class="country">{_flag_img(r.country)} {r.country}</td></tr>\n')
            return rows or '<tr><td colspan="4">No ranked riders</td></tr>'

        comparison_html = f"""
<section class="comparison">
  <h2>⚔ Race Comparison</h2>
  <div class="verdict-box">{verdict_txt}</div>

  <table class="cmp-table">
    <thead>
      <tr><th>Metric</th><th>🏁 Race 1</th><th>🏁 Race 2</th></tr>
    </thead>
    <tbody>
      {cmp_row("Race name",              race_name[:50], name2[:50],          higher=None)}
      {cmp_row("Total starters",         stats["total"],      stats2["total"],      True)}
      {cmp_row("Riders in UCI ranking",  stats["ranked"],     stats2["ranked"],     True)}
      {cmp_row("Riders in TOP 50",       stats["top50"],      stats2["top50"],      True)}
      {cmp_row("Riders in TOP 100",      stats["top100"],     stats2["top100"],     True)}
      {cmp_row("Riders in TOP 200",      stats["top200"],     stats2["top200"],     True)}
      {cmp_row("Best UCI ranking",       stats["best_rank"] or "—", stats2["best_rank"] or "—", False)}
      {cmp_row("Avg rank (ranked only)", avg1,                avg2,                 False)}
      {cmp_row("Points of TOP 10",       stats["top10_pts"],  stats2["top10_pts"],  True)}
      {cmp_row("Total UCI points",       stats["total_pts"],  stats2["total_pts"],  True)}
      {cmp_row("🏆 Quality score",       sc1,                 sc2,                  True)}
    </tbody>
  </table>

  <div class="top5-grid">
    <div>
      <h3>TOP 5 — Race 1</h3>
      <table class="top5-table">
        <thead><tr><th>Rank</th><th>Name</th><th>Pts</th><th>Country</th></tr></thead>
        <tbody>{top5_html(top5_r1)}</tbody>
      </table>
    </div>
    <div>
      <h3>TOP 5 — Race 2</h3>
      <table class="top5-table">
        <thead><tr><th>Rank</th><th>Name</th><th>Pts</th><th>Country</th></tr></thead>
        <tbody>{top5_html(top5_r2)}</tbody>
      </table>
    </div>
  </div>
</section>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{race_name}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0f1117; color: #e2e8f0; line-height: 1.5; padding: 2rem 1rem;
  }}
  a {{ color: #63b3ed; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .page-header {{
    border-left: 4px solid #4299e1; padding: 1rem 1.5rem; margin-bottom: 2rem;
    background: #1a202c; border-radius: 0 8px 8px 0;
  }}
  .page-header h1 {{ font-size: 1.6rem; color: #90cdf4; font-weight: 700; margin-bottom: .3rem; }}
  .page-header .meta {{ font-size: .85rem; color: #718096; }}
  .stats-grid {{ display: flex; flex-wrap: wrap; gap: .75rem; margin-bottom: 2rem; }}
  .stat-card {{
    background: #1a202c; border: 1px solid #2d3748; border-radius: 8px;
    padding: .8rem 1.2rem; min-width: 110px; text-align: center;
  }}
  .card-val   {{ font-size: 1.7rem; font-weight: 700; color: #63b3ed; }}
  .card-label {{ font-size: .75rem; color: #a0aec0; margin-top: .2rem; }}
  .card-sub   {{ font-size: .7rem; color: #718096; }}
  .section-title {{
    font-size: 1.1rem; font-weight: 600; color: #a0aec0;
    margin: 1.5rem 0 .6rem; text-transform: uppercase; letter-spacing: .08em;
  }}
  .race-section {{ margin-bottom: 2.5rem; }}
  .race-section-title {{
    font-size: 1.15rem; font-weight: 700; color: #90cdf4;
    border-left: 3px solid #4299e1; padding-left: .75rem;
    margin: 1.5rem 0 .8rem;
  }}
  .rider-table-wrap {{ overflow-x: auto; margin-bottom: 2rem; }}
  table.rider-table {{ width: 100%; border-collapse: collapse; font-size: .88rem; }}
  table.rider-table thead tr {{
    background: #2d3748; color: #a0aec0;
    text-transform: uppercase; font-size: .75rem; letter-spacing: .06em;
  }}
  table.rider-table th, table.rider-table td {{
    padding: .55rem .75rem; text-align: left;
    border-bottom: 1px solid #2d3748; white-space: nowrap;
  }}
  table.rider-table td.num    {{ color: #718096; text-align: right; width: 40px; }}
  table.rider-table td.rank   {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.rider-table td.pts    {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.rider-table td.uci-id {{ color: #718096; font-size: .8rem; }}
  table.rider-table td.team   {{ color: #a0aec0; font-size: .82rem; }}
  tr.tier-top50  td.name {{ color: #68d391; font-weight: 600; }}
  tr.tier-top50  td.rank {{ color: #68d391; font-weight: 600; }}
  tr.tier-top200 td.name {{ color: #9ae6b4; }}
  tr.tier-top200 td.rank {{ color: #9ae6b4; }}
  tr.tier-ranked td.name {{ color: #f6e05e; }}
  tr.tier-ranked td.rank {{ color: #f6e05e; }}
  tr.tier-unranked td.rank {{ color: #4a5568; }}
  table.rider-table tbody tr:hover {{ background: #1e2738; }}
  .conf-badge {{
    display: inline-block; margin-left: .4rem; font-size: .7rem;
    background: #2d3748; color: #718096; border-radius: 4px;
    padding: 1px 5px; vertical-align: middle;
  }}
  table.country-table {{ border-collapse: collapse; font-size: .88rem; margin-bottom: 2rem; }}
  table.country-table td {{ padding: .4rem .75rem; border-bottom: 1px solid #2d3748; }}
  td.c-flag  {{ white-space: nowrap; min-width: 80px; }}
  td.c-count {{ text-align: right; min-width: 50px; color: #63b3ed; font-weight: 600; }}
  td.c-bar-cell {{ width: 260px; position: relative; }}
  .c-bar {{
    height: 14px; background: linear-gradient(90deg, #3182ce, #63b3ed);
    border-radius: 3px; display: inline-block; vertical-align: middle;
  }}
  .c-pct {{ margin-left: .5rem; color: #718096; font-size: .78rem; vertical-align: middle; }}
  .comparison {{ margin-top: 3rem; }}
  .comparison h2 {{
    font-size: 1.3rem; color: #f6ad55; margin-bottom: 1rem;
    padding-bottom: .5rem; border-bottom: 1px solid #2d3748;
  }}
  .verdict-box {{
    background: #1c3044; border: 1px solid #2b6cb0; border-radius: 8px;
    padding: 1rem 1.5rem; font-size: 1rem; font-weight: 600;
    color: #90cdf4; margin-bottom: 1.5rem;
  }}
  table.cmp-table {{
    width: 100%; max-width: 700px; border-collapse: collapse;
    font-size: .88rem; margin-bottom: 2rem;
  }}
  table.cmp-table th {{
    background: #2d3748; color: #a0aec0; text-transform: uppercase;
    font-size: .75rem; letter-spacing: .06em; padding: .55rem .9rem; text-align: center;
  }}
  table.cmp-table th:first-child {{ text-align: left; }}
  table.cmp-table td {{ padding: .5rem .9rem; border-bottom: 1px solid #2d3748; text-align: center; }}
  table.cmp-table td:first-child {{ text-align: left; color: #a0aec0; }}
  table.cmp-table td.win {{ color: #68d391; font-weight: 700; }}
  .top5-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-top: 1rem; }}
  @media (max-width: 640px) {{ .top5-grid {{ grid-template-columns: 1fr; }} }}
  .top5-grid h3 {{ font-size: .95rem; color: #a0aec0; margin-bottom: .5rem; }}
  table.top5-table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  table.top5-table th {{
    background: #2d3748; color: #718096; text-transform: uppercase;
    font-size: .72rem; padding: .4rem .6rem; text-align: left;
  }}
  table.top5-table td {{ padding: .4rem .6rem; border-bottom: 1px solid #2d3748; }}
  table.top5-table td.rank {{ color: #63b3ed; font-weight: 600; text-align: right; }}
  table.top5-table td.pts  {{ text-align: right; color: #a0aec0; }}
  .legend {{
    display: flex; gap: 1.2rem; flex-wrap: wrap;
    font-size: .78rem; margin-bottom: 1rem; color: #a0aec0;
  }}
  .legend span {{ display: flex; align-items: center; gap: .35rem; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .dot-top50  {{ background: #68d391; }}
  .dot-top200 {{ background: #9ae6b4; }}
  .dot-ranked {{ background: #f6e05e; }}
  .dot-none   {{ background: #4a5568; }}
  .footer {{
    margin-top: 3rem; font-size: .75rem; color: #4a5568;
    border-top: 1px solid #2d3748; padding-top: 1rem;
  }}
  .search-wrap {{ margin-bottom: .75rem; }}
  #search {{
    background: #1a202c; border: 1px solid #2d3748; color: #e2e8f0;
    border-radius: 6px; padding: .45rem .8rem; font-size: .88rem;
    width: 280px; outline: none;
  }}
  #search:focus {{ border-color: #4299e1; }}
  table.rider-table tbody tr {{ cursor: pointer; user-select: none; }}
  tr.selected {{ background: #172a45 !important; outline: 1px solid #4299e1; outline-offset: -1px; }}
  tr.selected td.name {{ color: #63b3ed !important; font-weight: 600; }}
  .xco-link {{ color: #4a5568; font-size: .72rem; margin-left: .35rem; text-decoration: none; vertical-align: middle; }}
  .xco-link:hover {{ color: #63b3ed; }}
  #h2h-hint {{
    font-size: .8rem; color: #4a5568; margin-bottom: 1rem; font-style: italic;
  }}
  #h2h-panel {{
    display: none; margin-top: 2.5rem; border: 1px solid #2d3748;
    border-radius: 10px; overflow: hidden;
  }}
  .h2h-header {{
    background: #1c2f3f; padding: .75rem 1.2rem;
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid #2d3748;
  }}
  .h2h-header span {{ font-size: 1rem; font-weight: 700; color: #f6ad55; }}
  .h2h-clear {{
    background: none; border: 1px solid #4a5568; color: #a0aec0;
    border-radius: 4px; padding: .25rem .7rem; cursor: pointer; font-size: .8rem;
  }}
  .h2h-clear:hover {{ border-color: #a0aec0; color: #e2e8f0; }}
  .h2h-cards {{
    display: grid; grid-template-columns: 1fr auto 1fr;
    gap: 0; background: #141920;
  }}
  .h2h-card {{
    padding: 1.2rem 1.5rem; background: #1a202c;
  }}
  .h2h-card:last-child {{ text-align: right; }}
  .h2h-card .hc-name {{ font-size: 1.05rem; font-weight: 700; color: #e2e8f0; margin-bottom: .25rem; }}
  .h2h-card .hc-country {{ font-size: .85rem; color: #718096; margin-bottom: .5rem; }}
  .h2h-card .hc-rank {{ font-size: 1.5rem; font-weight: 700; color: #63b3ed; }}
  .h2h-card .hc-label {{ font-size: .72rem; color: #4a5568; text-transform: uppercase; letter-spacing: .06em; }}
  .h2h-card .hc-pts {{ font-size: .9rem; color: #a0aec0; margin-top: .2rem; }}
  .h2h-vs {{
    display: flex; align-items: center; justify-content: center;
    padding: 0 1rem; font-size: 1.1rem; font-weight: 900;
    color: #4a5568; background: #141920;
  }}
  .h2h-record {{
    padding: .8rem 1.5rem; background: #141920; border-top: 1px solid #2d3748;
    font-size: .88rem; color: #a0aec0; display: flex; gap: 2rem; flex-wrap: wrap;
  }}
  .h2h-record .rec-win  {{ color: #68d391; font-weight: 700; }}
  .h2h-record .rec-loss {{ color: #fc8181; font-weight: 700; }}
  .h2h-record .rec-tie  {{ color: #718096; }}
  .h2h-races-wrap {{ overflow-x: auto; }}
  table.h2h-races {{
    width: 100%; border-collapse: collapse; font-size: .85rem;
    border-top: 1px solid #2d3748;
  }}
  table.h2h-races th {{
    background: #1e2738; color: #a0aec0; text-transform: uppercase;
    font-size: .72rem; letter-spacing: .06em; padding: .5rem .9rem; text-align: left;
  }}
  table.h2h-races td {{ padding: .5rem .9rem; border-bottom: 1px solid #1e2738; }}
  table.h2h-races td.hr-race {{ color: #e2e8f0; max-width: 360px; }}
  table.h2h-races td.hr-date {{ color: #718096; white-space: nowrap; }}
  table.h2h-races td.hr-r1   {{ text-align: center; font-weight: 600; }}
  table.h2h-races td.hr-r2   {{ text-align: center; font-weight: 600; }}
  table.h2h-races td.hr-win  {{ color: #68d391; }}
  table.h2h-races td.hr-loss {{ color: #fc8181; }}
  table.h2h-races .no-shared {{ padding: 1rem 1.5rem; color: #718096; font-style: italic; }}
</style>
</head>
<body>
<div class="container">

  <header class="page-header">
    <h1>{race_name}</h1>
    <div class="meta">
      {f'Date: <strong>{race_date}</strong> &nbsp;|&nbsp; ' if race_date else ''}UCI category: <strong>{uci_cat}</strong> &nbsp;|&nbsp;
      Total starters: <strong>{len(riders)}</strong> &nbsp;|&nbsp;
      Generated: {generated_at} &nbsp;|&nbsp;
      Ranking data: <a href="https://www.xcodata.com" target="_blank">xcodata.com</a>
    </div>
  </header>

  {'<div class="stats-grid">' + stat_cards + '</div>' if not multi_race else ''}

  <div class="legend">
    <span><span class="dot dot-top50"></span>TOP 50</span>
    <span><span class="dot dot-top200"></span>TOP 51–200</span>
    <span><span class="dot dot-ranked"></span>Ranked 201+</span>
    <span><span class="dot dot-none"></span>Unranked</span>
    <span style="margin-left:.5rem;font-style:italic">Badge (87%) = fuzzy name match confidence</span>
  </div>

  <div class="search-wrap">
    <input id="search" type="text" placeholder="🔍  Filter by name, country or team…" oninput="filterTable()">
  </div>
  <div id="h2h-hint">Click any two riders to compare head-to-head ↓</div>

{start_list_block}

  <div class="section-title">Starters by Country</div>
  <table class="country-table">
    <tbody>
{country_rows}
    </tbody>
  </table>

  <div id="h2h-panel">
    <div class="h2h-header">
      <span>⚔ Head-to-Head</span>
      <button class="h2h-clear" onclick="clearSelection()">× Clear</button>
    </div>
    <div class="h2h-cards" id="h2h-cards"></div>
    <div class="h2h-record" id="h2h-record"></div>
    <div class="h2h-races-wrap">
      <table class="h2h-races" id="h2h-races"></table>
    </div>
  </div>

{comparison_html}

  <div class="footer">
    MTB Start List Analyzer &nbsp;|&nbsp; Ranking data © xcodata.com &nbsp;|&nbsp; {generated_at}
  </div>
</div>

<script>
var RIDERS = {riders_json};
var selected = [];

function esc(s) {{
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function selectRider(idx) {{
  var pos = selected.indexOf(idx);
  if (pos >= 0) {{
    selected.splice(pos, 1);
    var row = document.querySelector('tr[data-ridx="' + idx + '"]');
    if (row) row.classList.remove('selected');
  }} else {{
    if (selected.length >= 2) {{
      var old = selected.shift();
      var oldRow = document.querySelector('tr[data-ridx="' + old + '"]');
      if (oldRow) oldRow.classList.remove('selected');
    }}
    selected.push(idx);
    var row = document.querySelector('tr[data-ridx="' + idx + '"]');
    if (row) row.classList.add('selected');
  }}
  updateH2H();
}}

function clearSelection() {{
  selected.forEach(function(idx) {{
    var row = document.querySelector('tr[data-ridx="' + idx + '"]');
    if (row) row.classList.remove('selected');
  }});
  selected = [];
  updateH2H();
}}

function rankDisp(r) {{
  return r == null ? '—' : '#' + r;
}}

function posLabel(rank) {{
  if (rank == null) return '—';
  var s = ['th','st','nd','rd'];
  var v = rank % 100;
  return rank + (s[(v-20)%10] || s[v] || s[0]);
}}

function updateH2H() {{
  var panel = document.getElementById('h2h-panel');
  var hint  = document.getElementById('h2h-hint');
  if (selected.length < 2) {{
    panel.style.display = 'none';
    if (hint) hint.style.display = '';
    return;
  }}
  var r1 = RIDERS[selected[0]], r2 = RIDERS[selected[1]];
  if (!r1 || !r2) return;
  if (hint) hint.style.display = 'none';

  // Build shared races map
  var map1 = {{}};
  (r1.results || []).forEach(function(res) {{ if (res.race_id) map1[res.race_id] = res; }});
  var shared = [];
  (r2.results || []).forEach(function(res) {{
    if (res.race_id && map1[res.race_id]) {{
      shared.push({{ r1res: map1[res.race_id], r2res: res }});
    }}
  }});

  var wins1 = shared.filter(function(s) {{ return s.r1res.rank < s.r2res.rank; }}).length;
  var wins2 = shared.filter(function(s) {{ return s.r2res.rank < s.r1res.rank; }}).length;
  var ties  = shared.length - wins1 - wins2;

  // Render cards
  function card(r, wins, losses, right) {{
    var rankColor = r.rank && r.rank <= 50 ? '#68d391' : r.rank && r.rank <= 200 ? '#9ae6b4' : r.rank ? '#f6e05e' : '#a0aec0';
    return '<div class="h2h-card' + (right ? ' right' : '') + '">' +
      '<div class="hc-name">' + (r.flag ? '<img src="https://flagcdn.com/16x12/' + r.flag + '.png" style="vertical-align:middle" alt=""> ' : '') + esc(r.name) + '</div>' +
      '<div class="hc-country">' + esc(r.country) + '</div>' +
      '<div class="hc-rank" style="color:' + rankColor + '">' + rankDisp(r.rank) + '</div>' +
      '<div class="hc-label">UCI rank</div>' +
      '<div class="hc-pts">' + r.points + ' pts</div>' +
      (shared.length > 0 ? '<div class="hc-pts" style="margin-top:.5rem"><span class="rec-win">' + wins + 'W</span> / <span class="rec-loss">' + losses + 'L</span></div>' : '') +
      '</div>';
  }}
  document.getElementById('h2h-cards').innerHTML =
    card(r1, wins1, wins2, false) +
    '<div class="h2h-vs">VS</div>' +
    card(r2, wins2, wins1, true);

  // Record bar
  var recHtml = '<span>' + shared.length + ' shared race' + (shared.length !== 1 ? 's' : '') + '</span>';
  if (shared.length > 0) {{
    recHtml += '<span>' + esc(r1.name.split(' ').pop()) + ': <span class="rec-win">' + wins1 + ' win' + (wins1!==1?'s':'') + '</span></span>';
    recHtml += '<span>' + esc(r2.name.split(' ').pop()) + ': <span class="rec-win">' + wins2 + ' win' + (wins2!==1?'s':'') + '</span></span>';
    if (ties > 0) recHtml += '<span class="rec-tie">' + ties + ' tie' + (ties!==1?'s':'') + '</span>';
  }}
  document.getElementById('h2h-record').innerHTML = recHtml;

  // Races table
  var raceHtml = '<thead><tr>' +
    '<th>Race</th><th>Date</th>' +
    '<th>' + esc(r1.name.split(' ').pop()) + '</th>' +
    '<th>' + esc(r2.name.split(' ').pop()) + '</th>' +
    '</tr></thead><tbody>';
  if (shared.length === 0) {{
    var noMsg = 'No shared races found';
    var missing = [];
    if (!r1.results || r1.results.length === 0) missing.push(esc(r1.name));
    if (!r2.results || r2.results.length === 0) missing.push(esc(r2.name));
    if (missing.length > 0) noMsg = 'No race history available for: ' + missing.join(', ') + ' (no xcodata profile found)';
    raceHtml += '<tr><td colspan="4" class="no-shared">' + noMsg + '</td></tr>';
  }} else {{
    shared.forEach(function(s) {{
      var c1 = s.r1res.rank < s.r2res.rank ? ' hr-win' : s.r1res.rank > s.r2res.rank ? ' hr-loss' : '';
      var c2 = s.r2res.rank < s.r1res.rank ? ' hr-win' : s.r2res.rank > s.r1res.rank ? ' hr-loss' : '';
      raceHtml += '<tr>' +
        '<td class="hr-race">' + esc(s.r2res.race_name) + '</td>' +
        '<td class="hr-date">' + esc(s.r2res.date) + '</td>' +
        '<td class="hr-r1' + c1 + '">' + posLabel(s.r1res.rank) + '</td>' +
        '<td class="hr-r2' + c2 + '">' + posLabel(s.r2res.rank) + '</td>' +
        '</tr>';
    }});
  }}
  raceHtml += '</tbody>';
  document.getElementById('h2h-races').innerHTML = raceHtml;

  panel.style.display = 'block';
  panel.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
}}

function filterTable() {{
  var q = document.getElementById('search').value.toLowerCase();
  var rows = document.querySelectorAll('.rider-table tbody tr');
  rows.forEach(function(row) {{
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    console.print(f"[green]✓ HTML report exported to {path}[/green]")


def export_file(riders: list, race_name: str, uci_cat: str, path: str,
                compare_data: tuple = None):
    """Routes to HTML or CSV export based on file extension."""
    if path.lower().endswith((".html", ".htm")):
        export_html(riders, race_name, uci_cat, path, compare_data=compare_data)
    else:
        export_csv(riders, path)
