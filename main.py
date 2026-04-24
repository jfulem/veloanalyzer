#!/usr/bin/env python3
"""
MTB Start List Analyzer
=======================
Fetches a race start list, enriches it with UCI ranking data and displays an overview.
Can also compare two races based on the quality of registered riders.

Usage:
  python main.py --url "https://..." --category "Men Juniors"
  python main.py --compare "https://race1..." "https://race2..."
  python main.py --url "https://..." --category "Junior" --export results.html
  python main.py --refresh-cache --uci-category MJ

UCI categories (--uci-category):
  MJ = Men Juniors   WJ = Women Juniors
  ME = Men Elite     WE = Women Elite

Export formats:
  --export results.html   → rich HTML report (auto-detected by extension)
  --export results.csv    → CSV spreadsheet
"""

import argparse
import os
import sys

from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from mtb_analyzer.config import console
from mtb_analyzer.display import display_comparison, display_riders
from mtb_analyzer.export import export_csv, export_file, export_html
from mtb_analyzer.parsers import parse_start_list
from mtb_analyzer.ranking import get_uci_cache, lookup_rider


def main():
    parser = argparse.ArgumentParser(
        description="MTB Start List Analyzer — fetches a start list and enriches it with UCI ranking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url", help="Start list URL")
    parser.add_argument("--compare", nargs=2, metavar=("URL1", "URL2"),
                        help="Compare two start lists side by side")
    parser.add_argument("--category", "-c", default=None,
                        help="Category filter, e.g. 'Men Juniors', 'Junior', 'Elite'")
    parser.add_argument("--uci-category", "-u", default="MJ",
                        choices=["MJ", "WJ", "ME", "WE"],
                        help="UCI ranking category to use (default: MJ = Men Juniors)")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Force re-download of UCI ranking (ignores local cache)")
    parser.add_argument("--export", metavar="file.html",
                        help="Export results to HTML (.html) or CSV (.csv)")
    parser.add_argument("--no-lookup", action="store_true",
                        help="Skip UCI ranking lookup (faster — start list only)")

    args = parser.parse_args()

    if not args.url and not args.compare and not args.refresh_cache:
        parser.print_help()
        sys.exit(0)

    console.print(Panel.fit(
        "[bold cyan]MTB Start List Analyzer[/bold cyan]\n"
        "[dim]Ranking data: xcodata.com[/dim]",
        border_style="cyan",
    ))

    uci_cache = {}
    if not args.no_lookup:
        uci_cache = get_uci_cache(args.uci_category, force_refresh=args.refresh_cache)

    if args.refresh_cache and not args.url and not args.compare:
        console.print("[green]Cache refreshed.[/green]")
        return

    def process_url(url):
        with console.status("[cyan]Fetching start list...[/cyan]"):
            riders, race_name = parse_start_list(url, args.category)

        if not riders:
            console.print("[red]No riders found — check your --category filter.[/red]")
            return [], race_name

        console.print(f"[green]✓ Found {len(riders)} riders[/green]")

        if not args.no_lookup and uci_cache:
            with Progress(SpinnerColumn(), TextColumn("Looking up UCI rankings..."),
                          console=console) as prog:
                task = prog.add_task("", total=len(riders))
                for rider in riders:
                    lookup_rider(rider, uci_cache)
                    prog.advance(task)

        return riders, race_name

    if args.url:
        riders, race_name = process_url(args.url)
        if riders:
            display_riders(riders, race_name, args.uci_category)
            if args.export:
                export_file(riders, race_name, args.uci_category, args.export)

    elif args.compare:
        url1, url2 = args.compare
        riders1, name1 = process_url(url1)
        riders2, name2 = process_url(url2)

        if riders1:
            display_riders(riders1, name1, args.uci_category)
        if riders2:
            display_riders(riders2, name2, args.uci_category)

        if riders1 and riders2:
            display_comparison(
                (riders1, name1, url1),
                (riders2, name2, url2),
                args.uci_category,
            )

        if args.export:
            ext = os.path.splitext(args.export)[1].lower()
            if ext in (".html", ".htm"):
                export_html(riders1, name1, args.uci_category, args.export,
                            compare_data=(riders2, name2, url2, url1))
                console.print(f"[dim]Both races and comparison written to {args.export}[/dim]")
            else:
                p1 = args.export.replace(".csv", "_race1.csv")
                p2 = args.export.replace(".csv", "_race2.csv")
                if riders1: export_csv(riders1, p1)
                if riders2: export_csv(riders2, p2)


if __name__ == "__main__":
    main()
