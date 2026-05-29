import { Rider, RaceResult } from "../db.js";
import { flagEmoji, posLabel, tierClass, el } from "../utils.js";

export function renderRiderCard(
  container: HTMLElement,
  rider: Rider,
  results: RaceResult[],
): void {
  container.innerHTML = "";

  const displayName = rider.corrected_name || `${rider.first_name} ${rider.last_name}`.trim();
  const sorted = [...results].sort((a, b) => b.date.localeCompare(a.date));

  const ranked = results.filter((r) => r.rank != null);
  const bestRank = ranked.length ? Math.min(...ranked.map((r) => r.rank!)) : null;
  const top10 = ranked.filter((r) => r.rank! <= 10).length;

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
    const stats = el("div", { class: "rc-stats" });
    const chips: [string, string][] = [
      ["Races", String(results.length)],
      ["Best", bestRank != null ? posLabel(bestRank) : "—"],
      ["Top 10", String(top10)],
    ];
    for (const [label, value] of chips) {
      const chip = el("div", { class: "rc-chip" });
      chip.appendChild(el("span", { class: "rc-chip-val" }, value));
      chip.appendChild(el("span", { class: "rc-chip-lbl" }, label));
      stats.appendChild(chip);
    }
    container.appendChild(stats);
  }

  // ── Race history table ─────────────────────────────────────────────────────
  const histTitle = el("p", { class: "section-title" },
    `Race history (${results.length} result${results.length !== 1 ? "s" : ""})`);
  container.appendChild(histTitle);

  if (results.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "No race history found."));
    return;
  }

  const table = el("table", { class: "h2h-table" });
  const thead = el("thead");
  const hRow = el("tr");
  for (const h of ["Date", "Race", "Cat", "Pos", "Time"]) {
    hRow.appendChild(el("th", {}, h));
  }
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const res of sorted) {
    const tr = el("tr");
    tr.appendChild(el("td", {}, res.date || "—"));
    tr.appendChild(el("td", {}, res.race_name || "—"));
    tr.appendChild(el("td", {}, res.cat || "—"));
    const posTd = el("td", {});
    posTd.appendChild(el("span", { class: "pos-label" }, posLabel(res.rank)));
    posTd.style.fontWeight = res.rank != null && res.rank <= 3 ? "700" : "";
    posTd.style.color = res.rank === 1 ? "#f6e05e" : "";
    tr.appendChild(posTd);
    tr.appendChild(el("td", { class: "time-label", style: "display:table-cell; font-size:.85rem" },
      res.time || "—"));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}
