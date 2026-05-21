import { Rider } from "../db.js";
import { flagEmoji, el } from "../utils.js";

export function renderCountryChart(container: HTMLElement, riders: Rider[]): void {
  const counts: Record<string, number> = {};
  for (const r of riders) {
    const c = r.country || "—";
    counts[c] = (counts[c] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = sorted[0]?.[1] ?? 1;

  container.innerHTML = "";
  const table = el("table", { class: "country-table" });
  const tbody = el("tbody");

  for (const [country, count] of sorted) {
    const pct = Math.round((count / riders.length) * 100);
    const tr = el("tr");

    const flagCell = el("td", { class: "flag-cell" });
    flagCell.textContent = country !== "—" ? `${flagEmoji(country)} ${country}` : "—";

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
}
