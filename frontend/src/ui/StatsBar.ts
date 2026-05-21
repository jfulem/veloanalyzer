import { Rider } from "../db.js";
import { el } from "../utils.js";

export function renderStatsBar(container: HTMLElement, riders: Rider[]): void {
  const ranked = riders.filter((r) => r.uci_rank != null);
  const top50  = ranked.filter((r) => r.uci_rank! <= 50).length;
  const top100 = ranked.filter((r) => r.uci_rank! <= 100).length;
  const top200 = ranked.filter((r) => r.uci_rank! <= 200).length;
  const avgRank = ranked.length
    ? Math.round(ranked.reduce((s, r) => s + r.uci_rank!, 0) / ranked.length)
    : null;
  const totalPts = riders.reduce((s, r) => s + (r.uci_points ?? 0), 0);
  const bestRank = ranked.length ? Math.min(...ranked.map((r) => r.uci_rank!)) : null;

  const stats = [
    { label: "Starters",    value: String(riders.length) },
    { label: "Ranked",      value: String(ranked.length) },
    { label: "Best rank",   value: bestRank != null ? `#${bestRank}` : "—" },
    { label: "Avg rank",    value: avgRank  != null ? `#${avgRank}`  : "—" },
    { label: "TOP 50",      value: String(top50)  },
    { label: "TOP 100",     value: String(top100) },
    { label: "TOP 200",     value: String(top200) },
    { label: "Total pts",   value: String(totalPts) },
  ];

  container.innerHTML = "";
  const grid = el("div", { class: "stats-grid" });
  for (const s of stats) {
    const card = el("div", { class: "stat-card" });
    card.appendChild(el("div", { class: "stat-value" }, s.value));
    card.appendChild(el("div", { class: "stat-label" }, s.label));
    grid.appendChild(card);
  }
  container.appendChild(grid);
}
