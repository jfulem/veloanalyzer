import { Rider } from "../db.js";
import { el } from "../utils.js";

const PALETTE = [
  "#63b3ed","#68d391","#f6ad55","#fc8181","#b794f4",
  "#76e4f7","#f6e05e","#9ae6b4","#fbb6ce","#90cdf4",
];
const MAX_SLICES = 8;

export function renderTeamChart(container: HTMLElement, riders: Rider[]): void {
  const counts: Record<string, number> = {};
  for (const r of riders) {
    if (!r.team) continue;
    counts[r.team] = (counts[r.team] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0) { container.innerHTML = ""; return; }

  const total = sorted.reduce((s, [, n]) => s + n, 0);

  // Cap at MAX_SLICES; group remainder as "Others"
  const slices: [string, number][] = sorted.slice(0, MAX_SLICES);
  const othersCount = sorted.slice(MAX_SLICES).reduce((s, [, n]) => s + n, 0);
  if (othersCount > 0) slices.push(["Others", othersCount]);

  // Build conic-gradient string
  let deg = 0;
  const stops: string[] = [];
  slices.forEach(([, n], i) => {
    const share = (n / total) * 360;
    const color = PALETTE[i % PALETTE.length]!;
    stops.push(`${color} ${deg.toFixed(1)}deg ${(deg + share).toFixed(1)}deg`);
    deg += share;
  });

  container.innerHTML = "";
  const wrap = el("div", { class: "team-chart" });

  const pie = el("div", { class: "team-pie" });
  pie.style.background = `conic-gradient(${stops.join(", ")})`;
  wrap.appendChild(pie);

  const legend = el("table", { class: "team-legend" });
  slices.forEach(([name, count], i) => {
    const color = PALETTE[i % PALETTE.length]!;
    const pct   = Math.round((count / total) * 100);
    const tr    = el("tr");
    const dot   = el("td");
    const dotSpan = el("span", { class: "team-dot" });
    dotSpan.style.background = color;
    dot.appendChild(dotSpan);
    tr.appendChild(dot);
    tr.appendChild(el("td", { class: "team-name" }, name));
    tr.appendChild(el("td", { class: "team-count" }, `${count} (${pct}%)`));
    legend.appendChild(tr);
  });
  wrap.appendChild(legend);

  container.appendChild(wrap);
}
