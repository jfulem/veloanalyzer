import { Rider } from "../api.js";
import { flagEmoji, tierClass, el, Trend, applyTwemoji } from "../utils.js";

type SelectCallback = (riderId: number) => void;
type DetailCallback = (riderId: number) => void;

export function renderRiderTable(
  container: HTMLElement,
  riders: Rider[],
  selectedIds: Set<number>,
  onSelect: SelectCallback,
  onDetail: DetailCallback,
  trends: Map<number, Trend> = new Map(),
): void {
  container.innerHTML = "";

  // Group by sub-race label if present
  const groups = new Map<string, Rider[]>();
  for (const r of riders) {
    const key = r.race_name || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(r);
  }

  for (const [label, group] of groups) {
    if (label) {
      const h3 = el("h3", { class: "subrace-label" }, label);
      container.appendChild(h3);
    }
    container.appendChild(buildTable(group, selectedIds, onSelect, onDetail, trends));
  }

  applyTwemoji(container);
}

function buildTable(
  riders: Rider[],
  selectedIds: Set<number>,
  onSelect: SelectCallback,
  onDetail: DetailCallback,
  trends: Map<number, Trend>,
): HTMLTableElement {
  // Past races carry an official finishing rank/time fetched from UCI —
  // show those as dedicated "Result"/"Time" columns instead of only the
  // pre-race UCI ranking context.
  const hasResults = riders.some((r) => r.result_rank != null || r.result_time);

  const table = el("table", { class: "rider-table" });
  const thead = el("thead");
  const hRow = el("tr");
  const headers = ["#", "Name", "Country"];
  if (hasResults) headers.push("Result", "Time");
  headers.push("UCI rank", "UCI pts", "Team");
  for (const h of headers) {
    hRow.appendChild(el("th", {}, h));
  }
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  riders.forEach((rider, i) => {
    const tr = el("tr", {
      class: [tierClass(rider.uci_rank), selectedIds.has(rider.id) ? "selected" : ""].join(" ").trim(),
      "data-rider-id": String(rider.id),
    });
    tr.addEventListener("click", () => onSelect(rider.id));

    // #
    tr.appendChild(el("td", { class: "num-cell" }, String(i + 1)));

    // Name
    const nameCell = el("td", { class: "name-cell" });
    const displayName = rider.corrected_name || `${rider.first_name} ${rider.last_name}`.trim();
    const nameSpan = el("span", { class: "rider-name-link" }, displayName);
    nameSpan.addEventListener("click", (e) => { e.stopPropagation(); onDetail(rider.id); });
    nameCell.appendChild(nameSpan);

    if (rider.match_confidence < 100 && rider.uci_rank != null) {
      const badge = el("span", { class: "conf-badge" }, `${rider.match_confidence}%`);
      nameCell.appendChild(badge);
    }
    if (rider.xcodata_slug) {
      const link = el("a", {
        class: "xco-link",
        href: `https://www.xcodata.com${rider.xcodata_slug}`,
        target: "_blank",
      }, "↗");
      link.addEventListener("click", (e) => e.stopPropagation());
      nameCell.appendChild(link);
    }
    tr.appendChild(nameCell);

    // Country
    const flag = rider.country ? `${flagEmoji(rider.country)} ${rider.country}` : "—";
    tr.appendChild(el("td", { class: "country-cell" }, flag));

    // Result + Time (past races only)
    if (hasResults) {
      const resultCell = el("td", { class: "num-cell" });
      if (rider.result_rank === 1) resultCell.style.color = "#f6e05e";
      else if (rider.result_rank != null && rider.result_rank <= 3) resultCell.style.fontWeight = "700";
      resultCell.textContent = rider.result_rank != null ? String(rider.result_rank) : "—";
      tr.appendChild(resultCell);
      tr.appendChild(el("td", { class: "time-cell" }, rider.result_time || "—"));
    }

    // UCI rank + trend
    const rankCell = el("td", { class: "rank-cell" });
    rankCell.textContent = rider.uci_rank != null ? `#${rider.uci_rank}` : "—";
    const trend = trends.get(rider.id);
    if (trend) {
      const arrow = el("span", { class: `trend trend-${trend}` },
        trend === "up" ? " ↑" : trend === "down" ? " ↓" : "");
      // The arrow sits beside the UCI rank but is not about ranking movement,
      // so say what it actually measures.
      arrow.title = trend === "up"
        ? "Form: scoring more UCI points recently than earlier in the season"
        : "Form: scoring fewer UCI points recently than earlier in the season";
      if (trend !== "flat") rankCell.appendChild(arrow);
    }
    tr.appendChild(rankCell);

    // UCI pts — official total when ranked, otherwise a best-N estimate from race history
    const ptsCell = el("td", { class: "pts-cell" });
    if (rider.uci_points != null) {
      ptsCell.textContent = String(rider.uci_points);
    } else if (rider.computed_points) {
      ptsCell.textContent = `~${rider.computed_points}`;
      ptsCell.title = "Estimated from race history (best results, UCI art. 4.16.008)";
    } else {
      ptsCell.textContent = "0";
    }
    tr.appendChild(ptsCell);

    // Team
    const team = rider.team ? rider.team.slice(0, 50) : "—";
    tr.appendChild(el("td", { class: "team-cell" }, team));

    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  return table;
}

export function filterRiderTable(container: HTMLElement, query: string): void {
  const q = query.toLowerCase();
  container.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
    const text = row.textContent?.toLowerCase() ?? "";
    row.style.display = text.includes(q) ? "" : "none";
  });
}
