import { Rider } from "../db.js";
import { flagEmoji, tierClass, el } from "../utils.js";

type SelectCallback = (riderId: number) => void;

export function renderRiderTable(
  container: HTMLElement,
  riders: Rider[],
  selectedIds: Set<number>,
  onSelect: SelectCallback,
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
    container.appendChild(buildTable(group, selectedIds, onSelect));
  }
}

function buildTable(
  riders: Rider[],
  selectedIds: Set<number>,
  onSelect: SelectCallback,
): HTMLTableElement {
  const table = el("table", { class: "rider-table" });
  const thead = el("thead");
  const hRow = el("tr");
  for (const h of ["#", "Name", "Country", "UCI rank", "UCI pts", "Team"]) {
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
    const nameSpan = el("span", {}, displayName);
    nameCell.appendChild(nameSpan);

    if (rider.match_confidence < 100) {
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

    // UCI rank
    tr.appendChild(el("td", { class: "rank-cell" }, rider.uci_rank != null ? `#${rider.uci_rank}` : "—"));

    // UCI pts
    tr.appendChild(el("td", { class: "pts-cell" }, rider.uci_points != null ? String(rider.uci_points) : "0"));

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
