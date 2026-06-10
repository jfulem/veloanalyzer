import { Rider, RaceResult } from "../db.js";
import { flagEmoji, posLabel, tierClass, el, parseResultDate } from "../utils.js";

type SortCol = "date" | "race" | "cat" | "rank" | "time";
type SortDir = "asc" | "desc";

const ALL_COL_HEADERS: { key: SortCol; label: string }[] = [
  { key: "date",  label: "Date" },
  { key: "race",  label: "Race" },
  { key: "cat",   label: "Cat" },
  { key: "rank",  label: "Pos" },
  { key: "time",  label: "Time" },
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
    }
    return dir === "asc" ? cmp : -cmp;
  });
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
    for (const [label, value] of [
      ["Races", String(results.length)],
      ["Best",  bestRank != null ? posLabel(bestRank) : "—"],
      ["Top 10", String(top10)],
    ] as [string, string][]) {
      const chip = el("div", { class: "rc-chip" });
      chip.appendChild(el("span", { class: "rc-chip-val" }, value));
      chip.appendChild(el("span", { class: "rc-chip-lbl" }, label));
      stats.appendChild(chip);
    }
    container.appendChild(stats);
  }

  // ── Race history table ─────────────────────────────────────────────────────
  const historyNote = (!rider.xcodata_slug && rider.uci_rank != null)
    ? " · UCI scored races only"
    : "";
  container.appendChild(el("p", { class: "section-title" },
    `Race history (${results.length} result${results.length !== 1 ? "s" : ""}${historyNote})`));

  if (results.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "No race history found."));
    return;
  }

  // Sort state
  let sortCol: SortCol = "date";
  let sortDir: SortDir = "desc";

  const hasTimes = results.some((r) => !!r.time);
  const COL_HEADERS = hasTimes ? ALL_COL_HEADERS : ALL_COL_HEADERS.filter((c) => c.key !== "time");

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
      tbody.appendChild(tr);
    }
  }

  buildHeaders();
  buildBody();
}
