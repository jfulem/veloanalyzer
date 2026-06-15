import { Rider, RaceResult } from "../db.js";
import { flagEmoji, posLabel, timeGap, tierClass, el, parseResultDate } from "../utils.js";

export function renderH2H(
  container: HTMLElement,
  riders: Rider[],
  allResults: RaceResult[],
  selectedIds: number[],
): void {
  container.innerHTML = "";
  if (selectedIds.length < 2) return;

  const [id1, id2] = selectedIds as [number, number];
  const r1 = riders.find((r) => r.id === id1);
  const r2 = riders.find((r) => r.id === id2);
  if (!r1 || !r2) return;

  const res1 = allResults.filter((r) => r.rider_id === id1);
  const res2 = allResults.filter((r) => r.rider_id === id2);

  // Find shared races by xco_race_id
  const map1 = new Map<string, RaceResult>(res1.map((r) => [r.xco_race_id, r]));
  const shared = res2.filter((r) => r.xco_race_id && map1.has(r.xco_race_id));

  let w1 = 0, w2 = 0, ties = 0;
  for (const r2res of shared) {
    const r1res = map1.get(r2res.xco_race_id)!;
    if (r1res.rank == null || r2res.rank == null) continue;
    if (r1res.rank < r2res.rank) w1++;
    else if (r2res.rank < r1res.rank) w2++;
    else ties++;
  }

  container.appendChild(buildCards(r1, r2, w1, w2, ties));
  container.appendChild(buildRacesTable(shared, map1, r1, r2));
}

function buildCards(r1: Rider, r2: Rider, w1: number, w2: number, ties: number): HTMLElement {
  const wrap = el("div", { class: "h2h-cards" });

  for (const [rider, wins, losses] of [[r1, w1, w2], [r2, w2, w1]] as [Rider, number, number][]) {
    const card = el("div", { class: "h2h-card" });
    const name = rider.corrected_name || `${rider.first_name} ${rider.last_name}`.trim();
    card.appendChild(el("div", { class: "h2h-name" },
      `${flagEmoji(rider.country)} ${name}`));
    card.appendChild(el("div", { class: "h2h-country" }, rider.country || "—"));
    const rankEl = el("div", { class: `h2h-rank ${tierClass(rider.uci_rank)}` });
    rankEl.textContent = rider.uci_rank != null ? `#${rider.uci_rank}` : "—";
    card.appendChild(rankEl);
    card.appendChild(el("div", { class: "h2h-pts" },
      `${rider.uci_points ?? 0} UCI pts`));
    card.appendChild(el("div", { class: "h2h-wl" },
      `${wins}W – ${losses}L${ties > 0 ? ` – ${ties}T` : ""}`));
    wrap.appendChild(card);
  }
  return wrap;
}

function buildRacesTable(
  shared: RaceResult[],
  map1: Map<string, RaceResult>,
  r1: Rider,
  r2: Rider,
): HTMLElement {
  const wrap = el("div", { class: "h2h-races" });

  if (shared.length === 0) {
    wrap.appendChild(el("p", { class: "h2h-empty" }, "No shared races found."));
    return wrap;
  }

  const n1 = r1.corrected_name || `${r1.first_name} ${r1.last_name}`.trim();
  const n2 = r2.corrected_name || `${r2.first_name} ${r2.last_name}`.trim();

  const byDate = [...shared].sort((a, b) => parseResultDate(b.date) - parseResultDate(a.date));
  const hasTimes = byDate.some((r2res) => {
    const r1res = map1.get(r2res.xco_race_id)!;
    return !!(r1res.time || r2res.time);
  });

  const table = el("table", { class: "h2h-table" });
  const thead = el("thead");
  const hRow = el("tr");
  const headers = ["Race", "Date", n1, n2];
  if (hasTimes) headers.push("Gap");
  for (const h of headers) hRow.appendChild(el("th", {}, h));
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const r2res of byDate) {
    const r1res = map1.get(r2res.xco_race_id)!;
    const rank1 = r1res.rank;
    const rank2 = r2res.rank;
    let rowClass = "";
    if (rank1 != null && rank2 != null) {
      if (rank1 < rank2) rowClass = "win1";
      else if (rank2 < rank1) rowClass = "win2";
      else rowClass = "tie";
    }

    const tr = el("tr", { class: rowClass });
    tr.appendChild(el("td", {}, r2res.race_name || r2res.xco_race_id));
    tr.appendChild(el("td", {}, r2res.date));

    for (const [rank, time] of [[rank1, r1res.time], [rank2, r2res.time]] as [number | null, string][]) {
      const td = el("td", {});
      td.appendChild(el("span", { class: "pos-label" }, posLabel(rank)));
      if (time) td.appendChild(el("span", { class: "time-label" }, time));
      tr.appendChild(td);
    }

    if (hasTimes) {
      const gap = timeGap(r1res.time, r2res.time);
      tr.appendChild(el("td", { class: "gap-cell" }, gap));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}
