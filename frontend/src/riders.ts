import {
  getAllRiders, getMeta,
  RiderListItem,
} from "./api.js";
import { catBadge, el, UCI_CAT_LABEL } from "./raceStats.js";
import { $, flagEmoji, tierClass, applyTwemoji } from "./utils.js";

function openRider(id: number): void {
  location.href = `./rider.html?id=${id}&from=${encodeURIComponent(location.href)}`;
}

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
  const loading     = $<HTMLElement>("#loading");
  const content     = $<HTMLElement>("#content");
  const tableArea   = $<HTMLElement>("#table-area");
  const searchInput = $<HTMLInputElement>("#search-input");
  const countEl     = $<HTMLElement>("#riders-count");
  const legendEl    = $<HTMLElement>("#cat-legend");

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

  function updateUrl(): void {
    const p = new URLSearchParams();
    if (searchInput.value.trim()) p.set("search", searchInput.value.trim());
    if (activeCategory) p.set("cat", activeCategory);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function applyFilters(): void {
    const q = searchInput.value.trim().toLowerCase();
    tableArea.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      const matchesCat  = !activeCategory || row.dataset["cat"] === activeCategory;
      const matchesText = !q || (row.textContent ?? "").toLowerCase().includes(q);
      row.style.display = matchesCat && matchesText ? "" : "none";
    });
    updateUrl();
  }

  buildLegend(legendEl, present, (cat) => { activeCategory = cat; applyFilters(); });
  searchInput.addEventListener("input", applyFilters);

  tableArea.appendChild(buildTable(riders, openRider));
  applyTwemoji(tableArea);

  // Restore filters from URL query params (preserved in the "from" back-link)
  const urlParams = new URLSearchParams(location.search);
  const restoredSearch = urlParams.get("search") ?? "";
  const restoredCat    = urlParams.get("cat") ?? "";
  if (restoredSearch) {
    searchInput.value = restoredSearch;
  }
  if (restoredCat) {
    activeCategory = restoredCat;
    legendEl.querySelectorAll<HTMLElement>(".legend-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset["cat"] === restoredCat);
    });
  }
  if (restoredSearch || restoredCat) applyFilters();

  loading.style.display = "none";
  content.style.display = "block";
})();
