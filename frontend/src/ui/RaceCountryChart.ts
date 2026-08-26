import { UciArchiveRace } from "../api.js";
import { flagEmoji, el, applyTwemoji } from "../utils.js";

/** Bar chart of archived-race counts per country. Mirrors CountryChart.ts
 *  (rider nationality within one race's field) but counts distinct
 *  competitions across the whole archive instead. */
export function renderRaceCountryChart(container: HTMLElement, races: UciArchiveRace[]): void {
  const seen = new Set<string>();
  const counts: Record<string, number> = {};
  for (const r of races) {
    if (!r.country) continue;
    const key = `${r.country}|${r.xco_race_id}`;
    if (seen.has(key)) continue;   // one competition can carry several categories
    seen.add(key);
    counts[r.country] = (counts[r.country] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max   = sorted[0]?.[1] ?? 1;
  const total = seen.size;

  container.innerHTML = "";
  if (sorted.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "No archived races yet."));
    return;
  }

  const table = el("table", { class: "country-table" });
  const tbody = el("tbody");

  for (const [country, count] of sorted) {
    const pct = Math.round((count / total) * 100);
    const tr = el("tr");

    const flagCell = el("td", { class: "flag-cell" });
    flagCell.textContent = `${flagEmoji(country)} ${country}`;

    const countCell = el("td", { class: "count-cell" }, String(count));

    const barCell = el("td", { class: "bar-cell" });
    const bar = el("div", { class: "bar" });
    bar.style.width = `${(count / max) * 100}%`;
    const pctLabel = el("span", { class: "bar-pct" }, `${pct}%`);
    barCell.appendChild(bar);
    barCell.appendChild(pctLabel);

    tr.appendChild(flagCell);
    tr.appendChild(countCell);
    tr.appendChild(barCell);
    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  container.appendChild(table);

  applyTwemoji(container);
}
