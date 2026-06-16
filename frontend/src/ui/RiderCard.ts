import { Rider, RaceResult } from "../db.js";
import { flagEmoji, posLabel, tierClass, el, parseResultDate } from "../utils.js";

type SortCol = "date" | "race" | "cat" | "rank" | "time" | "pts";
type SortDir = "asc" | "desc";

const ALL_COL_HEADERS: { key: SortCol; label: string }[] = [
  { key: "date",  label: "Date" },
  { key: "race",  label: "Race" },
  { key: "cat",   label: "Cat" },
  { key: "rank",  label: "Pos" },
  { key: "time",  label: "Time" },
  { key: "pts",   label: "Pts" },
];

function sortResults(results: RaceResult[], col: SortCol, dir: SortDir): RaceResult[] {
  return [...results].sort((a, b) => {
    let cmp = 0;
    switch (col) {
      case "date": cmp = parseResultDate(a.date) - parseResultDate(b.date); break;
      case "race": cmp = (a.race_name ?? "").localeCompare(b.race_name ?? ""); break;
      case "cat":  cmp = (a.cat ?? "").localeCompare(b.cat ?? ""); break;
      case "rank": cmp = (a.rank ?? 9999) - (b.rank ?? 9999); break;
      case "time": cmp = (a.time ?? "").localeCompare(b.time ?? ""); break;
      case "pts":  cmp = (b.uci_pts ?? -1) - (a.uci_pts ?? -1); break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
}

function buildPointsChart(results: RaceResult[]): HTMLElement | null {
  const sorted = [...results]
    .filter((r) => r.uci_pts != null)
    .sort((a, b) => parseResultDate(a.date) - parseResultDate(b.date));

  if (sorted.length < 2) return null;

  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag: string, attrs: Record<string, string | number> = {}): Element => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };

  const W = 460, H = 110;
  const PL = 28, PR = 8, PT = 8, PB = 22;
  const CW = W - PL - PR, CH = H - PT - PB;

  const maxVal = Math.max(...sorted.map((r) => r.uci_pts!));
  const yMax   = maxVal > 0 ? Math.ceil(maxVal / 5) * 5 : 10;
  const n      = sorted.length;
  const xOf    = (i: number) => PL + (n > 1 ? (i / (n - 1)) * CW : CW / 2);
  const yOf    = (v: number) => PT + CH - (v / yMax) * CH;

  const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });

  // Gridlines + Y labels at 0, mid, max
  for (const frac of [0, 0.5, 1]) {
    const val = frac * yMax;
    const y   = yOf(val);
    svg.appendChild(mk("line", {
      x1: PL, y1: y, x2: W - PR, y2: y,
      stroke: frac === 0 ? "#4a5568" : "#2d3748", "stroke-width": 1,
    }));
    const lbl = mk("text", {
      x: PL - 4, y: y + 4,
      "text-anchor": "end", "font-size": 9, fill: "#718096",
    });
    lbl.textContent = String(Math.round(val));
    svg.appendChild(lbl);
  }

  // Area fill under line
  const areaCoords = [
    `${xOf(0)},${PT + CH}`,
    ...sorted.map((r, i) => `${xOf(i)},${yOf(r.uci_pts!)}`),
    `${xOf(n - 1)},${PT + CH}`,
  ].join(" ");
  svg.appendChild(mk("polygon", { points: areaCoords, fill: "rgba(99,179,237,0.10)" }));

  // Line
  svg.appendChild(mk("polyline", {
    points: sorted.map((r, i) => `${xOf(i)},${yOf(r.uci_pts!)}`).join(" "),
    fill: "none", stroke: "#63b3ed", "stroke-width": 2,
    "stroke-linejoin": "round", "stroke-linecap": "round",
  }));

  // Dots — filled if points scored, hollow-ish if zero
  for (let i = 0; i < n; i++) {
    const r = sorted[i]!;
    const g = mk("g");
    const title = mk("title");
    title.textContent = `${r.race_name} · ${r.date}: ${r.uci_pts} pts`;
    g.appendChild(title);
    g.appendChild(mk("circle", {
      cx: xOf(i), cy: yOf(r.uci_pts!), r: 4,
      fill: (r.uci_pts ?? 0) > 0 ? "#90cdf4" : "#4a5568",
      stroke: "#1a202c", "stroke-width": 1.5,
    }));
    svg.appendChild(g);
  }

  // X axis: labels at first, last and (if many races) midpoint
  const labelIdx = new Set<number>([0, n - 1]);
  if (n > 4) labelIdx.add(Math.round((n - 1) / 2));
  for (const i of labelIdx) {
    const r = sorted[i]!;
    const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    const parts  = r.date.split(" ");
    const label  = parts.length === 3 ? `${parts[1]} '${parts[2]!.slice(2)}` : r.date;
    const lbl = mk("text", {
      x: xOf(i), y: H - 5,
      "text-anchor": anchor, "font-size": 9, fill: "#718096",
    });
    lbl.textContent = label;
    svg.appendChild(lbl);
  }

  const wrap = el("div", { class: "rc-chart" });
  wrap.appendChild(svg as unknown as HTMLElement);
  return wrap;
}

export function renderRiderCard(
  container: HTMLElement,
  rider: Rider,
  results: RaceResult[],
): void {
  container.innerHTML = "";

  const displayName = rider.corrected_name || `${rider.first_name} ${rider.last_name}`.trim();
  const ranked = results.filter((r) => r.rank != null);
  const bestRank = ranked.length ? Math.min(...ranked.map((r) => r.rank!)) : null;

  // ── Header ─────────────────────────────────────────────────────────────────
  const header = el("div", { class: "rc-header" });

  const nameRow = el("div", { class: "rc-name" });
  nameRow.textContent = `${rider.country ? flagEmoji(rider.country) + " " : ""}${displayName}`;
  header.appendChild(nameRow);

  const metaRow = el("div", { class: "rc-meta" });
  const metaParts: string[] = [];
  if (rider.country) metaParts.push(rider.country);
  if (rider.birth_year) metaParts.push(`Born ${rider.birth_year}`);
  if (rider.team) metaParts.push(rider.team);
  metaRow.textContent = metaParts.join(" · ");
  header.appendChild(metaRow);

  const uciRow = el("div", { class: "rc-uci" });
  const rankSpan = el("span", { class: `rc-rank ${tierClass(rider.uci_rank)}` });
  rankSpan.textContent = rider.uci_rank != null ? `#${rider.uci_rank} UCI` : "Unranked";
  uciRow.appendChild(rankSpan);
  if (rider.uci_points != null) {
    uciRow.appendChild(el("span", { class: "rc-pts" }, ` · ${rider.uci_points} pts`));
  }
  if (rider.xcodata_slug) {
    const xcoLink = el("a", {
      class: "xco-link",
      href: `https://www.xcodata.com${rider.xcodata_slug}`,
      target: "_blank",
    }, " ↗ xcodata");
    uciRow.appendChild(xcoLink);
  }
  header.appendChild(uciRow);
  container.appendChild(header);

  // ── Stats chips ────────────────────────────────────────────────────────────
  if (results.length > 0) {
    const totalPts   = results.reduce((s, r) => s + (r.uci_pts ?? 0), 0);
    const finishers  = results.filter((r) => r.rank != null);
    const wins       = finishers.filter((r) => r.rank === 1).length;
    const podiums    = finishers.filter((r) => r.rank! <= 3).length;
    const ptsResults = results.filter((r) => r.uci_pts != null);
    const avgPts     = ptsResults.length
      ? (totalPts / ptsResults.length).toFixed(1)
      : "—";

    const stats = el("div", { class: "rc-stats" });
    for (const [label, value] of [
      ["Starts",   String(results.length)],
      ["Best",     bestRank != null ? posLabel(bestRank) : "—"],
      ["Wins",     String(wins)],
      ["Podiums",  String(podiums)],
      ["Avg pts",  avgPts],
      ["UCI pts",  String(totalPts)],
    ] as [string, string][]) {
      const chip = el("div", { class: "rc-chip" });
      chip.appendChild(el("span", { class: "rc-chip-val" }, value));
      chip.appendChild(el("span", { class: "rc-chip-lbl" }, label));
      stats.appendChild(chip);
    }
    container.appendChild(stats);
  }

  // ── Form chart ─────────────────────────────────────────────────────────────
  const chart = buildPointsChart(results);
  if (chart) container.appendChild(chart);

  // ── Race history table ─────────────────────────────────────────────────────
  container.appendChild(el("p", { class: "section-title" },
    `Race history (${results.length} result${results.length !== 1 ? "s" : ""})`));

  if (results.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "No race history found."));
    return;
  }

  // Sort state
  let sortCol: SortCol = "date";
  let sortDir: SortDir = "desc";

  const hasTimes = results.some((r) => !!r.time);
  const hasPts   = results.some((r) => r.uci_pts != null);
  const COL_HEADERS = ALL_COL_HEADERS.filter((c) =>
    (c.key !== "time" || hasTimes) && (c.key !== "pts" || hasPts),
  );

  const table = el("table", { class: "h2h-table" });
  const thead = el("thead");
  const hRow = el("tr");
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  table.appendChild(tbody);
  container.appendChild(table);

  function buildHeaders(): void {
    hRow.innerHTML = "";
    for (const { key, label } of COL_HEADERS) {
      const th = el("th", { class: "sortable-th" });
      const isActive = key === sortCol;
      th.textContent = label + (isActive ? (sortDir === "asc" ? " ↑" : " ↓") : "");
      th.style.cursor = "pointer";
      if (isActive) th.style.color = "#90cdf4";
      th.addEventListener("click", () => {
        if (sortCol === key) sortDir = sortDir === "asc" ? "desc" : "asc";
        else { sortCol = key; sortDir = key === "date" ? "desc" : "asc"; }
        buildHeaders();
        buildBody();
      });
      hRow.appendChild(th);
    }
  }

  function buildBody(): void {
    tbody.innerHTML = "";
    for (const res of sortResults(results, sortCol, sortDir)) {
      const tr = el("tr");
      tr.appendChild(el("td", {}, res.date || "—"));
      tr.appendChild(el("td", {}, res.race_name || "—"));
      tr.appendChild(el("td", {}, res.cat || "—"));

      const posTd = el("td", {});
      const posSpan = el("span", {}, posLabel(res.rank));
      if (res.rank === 1) posSpan.style.color = "#f6e05e";
      else if (res.rank != null && res.rank <= 3) posSpan.style.fontWeight = "700";
      posTd.appendChild(posSpan);
      tr.appendChild(posTd);

      if (hasTimes) tr.appendChild(el("td", { style: "font-size:.82rem; color:#a0aec0" }, res.time || "—"));
      if (hasPts) tr.appendChild(el("td", { style: "font-size:.82rem; color:#68d391" },
        res.uci_pts != null ? String(res.uci_pts) : "—"));
      tbody.appendChild(tr);
    }
  }

  buildHeaders();
  buildBody();
}
