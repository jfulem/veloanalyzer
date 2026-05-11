from collections import Counter

from rich.panel import Panel
from rich.table import Table

from .config import FLAG, console
from .models import Rider


def sort_riders(riders: list) -> list:
    ranked   = sorted([r for r in riders if r.uci_rank is not None], key=lambda r: r.uci_rank)
    unranked = sorted([r for r in riders if r.uci_rank is None],     key=lambda r: r.full_name)
    return ranked + unranked


def race_quality_stats(riders: list) -> dict:
    ranked    = [r for r in riders if r.uci_rank is not None and r.uci_points]
    total_pts = sum(r.uci_points for r in ranked)
    top10_pts = sum(r.uci_points for r in sorted(ranked, key=lambda r: r.uci_rank)[:10])
    avg_rank  = (sum(r.uci_rank for r in ranked) / len(ranked)) if ranked else None
    best_rank = min((r.uci_rank for r in ranked), default=None)
    return {
        "total":     len(riders),
        "ranked":    len(ranked),
        "top50":     sum(1 for r in ranked if r.uci_rank <= 50),
        "top100":    sum(1 for r in ranked if r.uci_rank <= 100),
        "top200":    sum(1 for r in ranked if r.uci_rank <= 200),
        "best_rank": best_rank,
        "avg_rank":  avg_rank,
        "total_pts": total_pts,
        "top10_pts": top10_pts,
    }


def _riders_table(riders: list, title: str) -> Table:
    table = Table(
        title=title, show_header=True, header_style="bold magenta",
        border_style="dim", show_lines=False,
    )
    table.add_column("#",       style="dim", width=4,  justify="right")
    table.add_column("Name",                min_width=22)
    table.add_column("Country",             width=8)
    table.add_column("UCI rank",            width=9,  justify="right")
    table.add_column("UCI pts",             width=8,  justify="right")
    table.add_column("UCI ID", style="dim", width=13)
    table.add_column("Team",   style="dim", min_width=20)

    for i, r in enumerate(sort_riders(riders), 1):
        rank_str   = str(r.uci_rank) if r.uci_rank else "[dim]—[/dim]"
        pts_str    = str(r.uci_points) if r.uci_points else "[dim]0[/dim]"
        confidence = ""
        if r.match_confidence < 100 and r.uci_rank:
            confidence = f" [dim]({r.match_confidence}%)[/dim]"

        if   r.uci_rank and r.uci_rank <= 50:  name_style = "bold green"
        elif r.uci_rank and r.uci_rank <= 200:  name_style = "green"
        elif r.uci_rank:                        name_style = "yellow"
        else:                                   name_style = "white"

        display_name = r.corrected_name if r.corrected_name else r.full_name
        table.add_row(
            str(i),
            f"[{name_style}]{display_name}[/{name_style}]{confidence}",
            f"{r.flag} {r.country}",
            rank_str, pts_str,
            r.uci_id or "—",
            r.team[:40] if r.team else "—",
        )
    return table


def display_riders(riders: list, race_name: str, uci_cat: str):
    """Displays the rider table(s) sorted by UCI ranking."""
    race_keys = list(dict.fromkeys(r.race_name for r in riders if r.race_name))

    if len(race_keys) > 1:
        # Multi-race meeting: one table per race
        console.print(f"\n[bold cyan]{race_name}[/bold cyan]  "
                      f"[dim]UCI: {uci_cat} | {len(riders)} total starters[/dim]")
        for rk in race_keys:
            group = [r for r in riders if r.race_name == rk]
            console.print(_riders_table(
                group,
                f"[bold]{rk}[/bold]  [dim]{len(group)} starters[/dim]",
            ))
        display_country_stats(sort_riders(riders))
    else:
        sorted_riders = sort_riders(riders)
        console.print(_riders_table(
            riders,
            (f"[bold cyan]{race_name}[/bold cyan]\n"
             f"[dim]UCI category: {uci_cat} | Total starters: {len(riders)}[/dim]"),
        ))
        display_country_stats(sorted_riders)


def display_country_stats(riders: list):
    country_counts = Counter(r.country for r in riders)

    table = Table(title="[bold]Starters by Country[/bold]",
                  show_header=True, header_style="bold blue",
                  border_style="dim", padding=(0, 1))
    table.add_column("Country",  min_width=12)
    table.add_column("Count",    justify="right", width=7)
    table.add_column("Bar",      min_width=20)

    total = len(riders)
    for country, count in sorted(country_counts.items(), key=lambda x: -x[1]):
        flag = FLAG.get(country, "  ")
        bar  = "█" * count
        pct  = f"{count / total * 100:.0f}%"
        table.add_row(f"{flag} {country}", str(count),
                      f"[cyan]{bar}[/cyan] [dim]{pct}[/dim]")

    console.print(table)


def display_comparison(race1_data: tuple, race2_data: tuple, uci_cat: str):
    """Compares two races side by side and recommends the one with the stronger field."""
    riders1, name1, url1 = race1_data
    riders2, name2, url2 = race2_data
    stats1 = race_quality_stats(riders1)
    stats2 = race_quality_stats(riders2)

    def quality_score(s):
        return (s["top10_pts"] * 3 + s["top50"] * 10 +
                s["top100"] * 5 + s["top200"] * 2 + s["ranked"])

    score1 = quality_score(stats1)
    score2 = quality_score(stats2)

    console.print()
    console.rule("[bold yellow]⚔  RACE COMPARISON  ⚔[/bold yellow]")
    console.print()

    comp = Table(show_header=True, header_style="bold", border_style="blue", padding=(0, 2))
    comp.add_column("Metric",    style="bold",  min_width=30)
    comp.add_column("🏁 Race 1", justify="center", min_width=22, style="cyan")
    comp.add_column("🏁 Race 2", justify="center", min_width=22, style="magenta")

    def winner_style(v1, v2, higher_is_better=True):
        if v1 is None or v2 is None:
            return str(v1 or "—"), str(v2 or "—")
        better = (v1 > v2) if higher_is_better else (v1 < v2)
        s1 = f"[bold green]{v1}[/bold green]" if better     else str(v1)
        s2 = f"[bold green]{v2}[/bold green]" if not better else str(v2)
        return s1, s2

    rows_data = [
        ("Race name", name1[:45], name2[:45], None),
        ("URL",
         (url1[:50] + "...") if len(url1) > 50 else url1,
         (url2[:50] + "...") if len(url2) > 50 else url2, None),
        ("─" * 27, "", "", None),
        ("Total starters",               stats1["total"],     stats2["total"],     True),
        ("Riders in UCI ranking",         stats1["ranked"],    stats2["ranked"],    True),
        ("─" * 27, "", "", None),
        ("Riders in TOP 50",              stats1["top50"],     stats2["top50"],     True),
        ("Riders in TOP 100",             stats1["top100"],    stats2["top100"],    True),
        ("Riders in TOP 200",             stats1["top200"],    stats2["top200"],    True),
        ("─" * 27, "", "", None),
        ("Best UCI ranking",              stats1["best_rank"], stats2["best_rank"], False),
        ("Average rank (ranked riders)",
         f"{stats1['avg_rank']:.0f}" if stats1["avg_rank"] else "—",
         f"{stats2['avg_rank']:.0f}" if stats2["avg_rank"] else "—", False),
        ("─" * 27, "", "", None),
        ("Points of TOP 10 riders",       stats1["top10_pts"], stats2["top10_pts"], True),
        ("Total UCI points",              stats1["total_pts"], stats2["total_pts"], True),
        ("─" * 27, "", "", None),
        ("🏆 QUALITY SCORE",              score1,              score2,              True),
    ]

    for row in rows_data:
        label, v1, v2, higher = row
        if higher is None:
            comp.add_row(f"[dim]{label}[/dim]", str(v1), str(v2))
        else:
            try:
                s1, s2 = winner_style(int(str(v1).replace("—", "0")),
                                       int(str(v2).replace("—", "0")), higher)
            except (ValueError, TypeError):
                s1, s2 = str(v1), str(v2)
            comp.add_row(label, s1, s2)

    console.print(comp)
    console.print()

    if   score1 > score2:
        diff    = score1 - score2
        verdict = (f"[bold green]✅  RACE 1 has a stronger field[/bold green]\n"
                   f"[dim]{name1}[/dim]\n[dim](quality score higher by {diff})[/dim]")
    elif score2 > score1:
        diff    = score2 - score1
        verdict = (f"[bold green]✅  RACE 2 has a stronger field[/bold green]\n"
                   f"[dim]{name2}[/dim]\n[dim](quality score higher by {diff})[/dim]")
    else:
        verdict = "[yellow]⚖  Both races are of comparable quality[/yellow]"

    console.print(Panel(verdict, title="Verdict", border_style="green", padding=(1, 4)))
    console.print()

    for label, riders in [(f"TOP 5 — {name1[:40]}", riders1),
                           (f"TOP 5 — {name2[:40]}", riders2)]:
        top5 = sorted([r for r in riders if r.uci_rank], key=lambda r: r.uci_rank)[:5]
        if top5:
            top = Table(title=label, show_header=False, border_style="dim", padding=(0, 1))
            top.add_column("Rank",    width=6, justify="right")
            top.add_column("Name",    min_width=22)
            top.add_column("Points",  width=7, justify="right")
            top.add_column("Country", width=8)
            for r in top5:
                top.add_row(str(r.uci_rank), r.full_name,
                            str(r.uci_points), f"{r.flag} {r.country}")
            console.print(top)
            console.print()
