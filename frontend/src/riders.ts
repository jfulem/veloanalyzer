import {
  getAllRiders, getMeta, getRiderDetail, getRiderHistory,
  Rider, RiderListItem,
} from "./api.js";
import { catBadge, el, UCI_CAT_LABEL } from "./raceStats.js";
import { $, flagEmoji, tierClass, applyTwemoji } from "./utils.js";
import { renderRiderCard } from "./ui/RiderCard.js";

// ── Table ────────────────────────────────────────────────────────────────
function buildRow(rider: RiderListItem, index: number, onOpen: (id: number) => void): HTMLTableRowElement {
  const tr = el("tr", {
    class: tierClass(rider.uci_rank),
  }) as HTMLTableRowElement;
  tr.dataset["cat"] = rider.uci_category || "";
  tr.style.cursor = "pointer";
  tr.addEventListener("click", () => onOpen(rider.id));

  tr.appendChild(el("td", { class: "num-cell" }, String(index + 1)));

  const nameCell = el("td", { class: "name-cell" });
  nameCell.appendChild(el("span", { class: "rider-name-link" }, `${rider.first_name} ${rider.last_name}`.trim()));
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

  const flag = rider.country ? `${flagEmoji(rider.country)} ${rider.country}` : "—";
  tr.appendChild(el("td", { class: "country-cell" }, flag));

  const catCell = el("td");
  if (rider.uci_category) catCell.appendChild(catBadge(rider.uci_category));
  else catCell.textContent = "—";
  tr.appendChild(catCell);

  const rankCell = el("td", { class: "rank-cell" });
  rankCell.textContent = rider.uci_rank != null ? `#${rider.uci_rank}` : "—";
  tr.appendChild(rankCell);

  const ptsCell = el("td", { class: "pts-cell" });
  ptsCell.textContent = rider.uci_points != null ? String(rider.uci_points) : "—";
  tr.appendChild(ptsCell);

  const team = rider.team ? rider.team.slice(0, 50) : "—";
  tr.appendChild(el("td", { class: "team-cell" }, team));

  tr.appendChild(el("td", { class: "num-cell" }, String(rider.races_count)));

  return tr;
}

function buildTable(riders: RiderListItem[], onOpen: (id: number) => void): HTMLTableElement {
  const table = el("table", { class: "rider-table" }) as HTMLTableElement;
  const thead = el("thead");
  const hRow = el("tr");
  for (const h of ["#", "Name", "Country", "Category", "UCI rank", "UCI pts", "Team", "Races"]) {
    hRow.appendChild(el("th", {}, h));
  }
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  riders.forEach((rider, i) => tbody.appendChild(buildRow(rider, i, onOpen)));
  table.appendChild(tbody);
  return table;
}

// ── Category legend ─────────────────────────────────────────────────────────
// Filters by uci_category (MJ/WJ/ME/WE/MU23/WU23) — a rider's most recent
// race, since that is the only category information a rider carries once
// pulled out of any one start list.
function buildLegend(container: HTMLElement, present: Set<string>, onChange: (cat: string | null) => void): void {
  for (const [cat, label] of Object.entries(UCI_CAT_LABEL)) {
    if (!present.has(cat)) continue;   // no point offering a filter with zero matches
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.dataset["cat"] = cat;
    btn.appendChild(catBadge(cat));
    btn.appendChild(document.createTextNode(` ${label}`));
    container.appendChild(btn);
  }

  container.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLElement>(".legend-item");
    if (!btn) return;
    const wasActive = btn.classList.contains("active");
    container.querySelectorAll(".legend-item").forEach((b) => b.classList.remove("active"));
    if (wasActive) {
      onChange(null);
      return;
    }
    btn.classList.add("active");
    onChange(btn.dataset["cat"] ?? null);
  });
}

// ── Boot ─────────────────────────────────────────────────────────────────
(async () => {
  const loading = $<HTMLElement>("#loading");
  const content = $<HTMLElement>("#content");
  const tableArea = $<HTMLElement>("#table-area");
  const searchInput = $<HTMLInputElement>("#search-input");
  const countEl = $<HTMLElement>("#riders-count");
  const legendEl = $<HTMLElement>("#cat-legend");

  const riderBackdrop = $<HTMLElement>("#rider-backdrop");
  const riderClose    = $<HTMLElement>("#rider-close");
  const riderCardEl   = $<HTMLElement>("#rider-card");

  function closeRiderModal(): void {
    riderBackdrop.setAttribute("hidden", "");
    document.body.style.overflow = "";
  }
  riderClose.addEventListener("click", closeRiderModal);
  riderBackdrop.addEventListener("click", (e) => {
    if (e.target === riderBackdrop) closeRiderModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !riderBackdrop.hasAttribute("hidden")) closeRiderModal();
  });

  async function openRider(id: number): Promise<void> {
    try {
      const [detail, history] = await Promise.all([getRiderDetail(id), getRiderHistory(id)]);
      // Shim into the race-context Rider shape RiderCard.ts expects. The
      // fields with no meaning outside a specific start list — bib, entry
      // category text, official result, corrected spelling, match confidence —
      // are left at neutral defaults; renderRiderCard only shows them when set.
      const shim: Rider = {
        id: detail.id,
        race_id: 0,
        first_name: detail.first_name,
        last_name: detail.last_name,
        corrected_name: "",
        country: detail.country,
        birth_year: detail.birth_year,
        start_nr: "",
        uci_id: detail.uci_id,
        uci_rank: detail.uci_rank,
        uci_points: detail.uci_points,
        cp_xco_points: null,
        computed_points: null,
        result_rank: null,
        result_time: null,
        team: detail.team,
        category: "",
        match_confidence: 100,
        xcodata_slug: detail.xcodata_slug,
        race_name: "",
        last_points_date: null,
      };
      renderRiderCard(riderCardEl, shim, history);
      riderBackdrop.removeAttribute("hidden");
      document.body.style.overflow = "hidden";
    } catch (err) {
      console.error("failed to open rider", id, err);
    }
  }

  let riders: RiderListItem[];
  let meta: Record<string, string>;
  try {
    [riders, meta] = await Promise.all([getAllRiders(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  $<HTMLElement>("#generated-at").textContent = meta["generated_at"] ?? "";
  countEl.textContent = `${riders.length} riders tracked`;

  const present = new Set(riders.map((r) => r.uci_category).filter(Boolean));
  let activeCategory: string | null = null;

  function applyFilters(): void {
    const q = searchInput.value.trim().toLowerCase();
    tableArea.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      const matchesCat  = !activeCategory || row.dataset["cat"] === activeCategory;
      const matchesText = !q || (row.textContent ?? "").toLowerCase().includes(q);
      row.style.display = matchesCat && matchesText ? "" : "none";
    });
  }

  buildLegend(legendEl, present, (cat) => { activeCategory = cat; applyFilters(); });
  searchInput.addEventListener("input", applyFilters);

  tableArea.appendChild(buildTable(riders, openRider));
  applyTwemoji(tableArea);

  loading.style.display = "none";
  content.style.display = "block";
})();
