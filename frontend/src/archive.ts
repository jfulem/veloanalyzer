import {
  getUciArchive, getXcoRaceResults, getMeta,
  UciArchiveRace, XcoRaceFinisher,
} from "./api.js";
import { catBadge, el, UCI_CAT_LABEL } from "./raceStats.js";
import { $, flagEmoji, applyTwemoji, posLabel } from "./utils.js";

// Preferred tab order when a race has more than one category on record.
const CAT_ORDER = ["ME", "WE", "MJ", "WJ", "MU23", "WU23"];

// One row per competition, not per category — a race's categories become a
// choice made inside the results panel instead of duplicating the row for
// each one, which used to make a 4-category race look like 4 races.
interface GroupedRace {
  xco_race_id: string;
  comp_name: string;
  date: string;
  venue: string;
  country: string;
  categories: Record<string, number>;   // category → finisher count
}

function groupByCompetition(races: UciArchiveRace[]): GroupedRace[] {
  const byId = new Map<string, GroupedRace>();
  for (const r of races) {
    let g = byId.get(r.xco_race_id);
    if (!g) {
      g = { xco_race_id: r.xco_race_id, comp_name: r.comp_name, date: r.date,
            venue: r.venue, country: r.country, categories: {} };
      byId.set(r.xco_race_id, g);
    }
    g.categories[r.category] = r.finishers;
  }
  return [...byId.values()].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

function sortedCategories(categories: Record<string, number>): string[] {
  const cats = Object.keys(categories);
  return cats.sort((a, b) => {
    const ia = CAT_ORDER.indexOf(a), ib = CAT_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

// ── Table ────────────────────────────────────────────────────────────────
function buildRow(race: GroupedRace, onOpen: (race: GroupedRace) => void): HTMLTableRowElement {
  const tr = el("tr") as HTMLTableRowElement;
  tr.dataset["country"] = race.country;
  tr.style.cursor = "pointer";
  tr.title = "Click to see full race results";
  tr.addEventListener("click", () => onOpen(race));

  tr.appendChild(el("td", {}, race.date || "—"));

  const nameTd = el("td", { class: "rc-race-link" });
  nameTd.appendChild(el("span", {}, race.comp_name || "—"));
  const sub = [race.venue, race.country ? `${flagEmoji(race.country)} ${race.country}` : ""]
    .filter(Boolean).join(" · ");
  if (sub) nameTd.appendChild(el("span", { class: "time-label" }, sub));
  tr.appendChild(nameTd);

  const catTd = el("td", { class: "archive-cats" });
  for (const cat of sortedCategories(race.categories)) catTd.appendChild(catBadge(cat));
  tr.appendChild(catTd);

  const total = Object.values(race.categories).reduce((s, n) => s + n, 0);
  tr.appendChild(el("td", { class: "num-cell" }, String(total)));

  return tr;
}

function buildTable(races: GroupedRace[], onOpen: (race: GroupedRace) => void): HTMLTableElement {
  const table = el("table", { class: "rider-table" }) as HTMLTableElement;
  const thead = el("thead");
  const hRow  = el("tr");
  for (const h of ["Date", "Race", "Categories", "Finishers"]) {
    hRow.appendChild(el("th", {}, h));
  }
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  races.forEach((r) => tbody.appendChild(buildRow(r, onOpen)));
  table.appendChild(tbody);
  return table;
}

// ── Results panel ────────────────────────────────────────────────────────
// One shared panel below the table. A race with several categories on record
// gets a small tab row so the category choice happens here, after picking a
// race — not up front in the browse list.
let activeRaceId    = "";
let activeCategory  = "";

async function loadCategoryResults(panel: HTMLElement, race: GroupedRace, category: string): Promise<void> {
  activeCategory = category;
  const body = panel.querySelector<HTMLElement>(".archive-panel-body")!;
  body.innerHTML = "<p class='h2h-empty'>Loading…</p>";

  let finishers: XcoRaceFinisher[];
  try {
    finishers = await getXcoRaceResults(race.xco_race_id, category);
  } catch {
    body.innerHTML = "<p class='h2h-empty'>Could not load race results.</p>";
    return;
  }
  if (activeRaceId !== race.xco_race_id || activeCategory !== category) return;

  body.innerHTML = "";
  if (finishers.length === 0) {
    body.appendChild(el("p", { class: "h2h-empty" }, "No results stored yet."));
    return;
  }

  const t  = el("table", { class: "h2h-table" });
  const th = el("thead");
  const hr = el("tr");
  for (const h of ["Pos", "Name", "NAT", "Time", "Pts"]) hr.appendChild(el("th", {}, h));
  th.appendChild(hr);
  t.appendChild(th);

  const tb = el("tbody");
  for (const f of finishers) {
    const tr = el("tr");
    const posTd   = el("td", { class: "num-cell" });
    const posSpan = el("span", {}, posLabel(f.rank));
    if (f.rank === 1) posSpan.style.color = "#f6e05e";
    else if (f.rank != null && f.rank <= 3) posSpan.style.fontWeight = "700";
    posTd.appendChild(posSpan);
    tr.appendChild(posTd);
    tr.appendChild(el("td", {}, `${f.first_name} ${f.last_name}`.trim()));
    tr.appendChild(el("td", { class: "country-cell" },
      f.nationality ? `${flagEmoji(f.nationality)} ${f.nationality}` : "—"));
    tr.appendChild(el("td", { class: "time-cell", style: "font-size:.82rem; color:#a0aec0" },
      f.race_time || "—"));
    tr.appendChild(el("td", { class: "num-cell", style: "font-size:.82rem; color:#68d391" },
      f.uci_pts != null ? String(f.uci_pts) : "—"));
    tb.appendChild(tr);
  }
  t.appendChild(tb);
  body.appendChild(t);
  applyTwemoji(body);
}

function openResultsPanel(panel: HTMLElement, race: GroupedRace): void {
  if (activeRaceId === race.xco_race_id) {
    panel.setAttribute("hidden", "");
    activeRaceId = "";
    return;
  }
  activeRaceId = race.xco_race_id;
  panel.removeAttribute("hidden");
  panel.innerHTML = "";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  panel.appendChild(el("p", { class: "section-title" }, `${race.comp_name} (${race.date})`));

  const cats = sortedCategories(race.categories);
  const tabs = el("div", { class: "cat-legend" });
  for (const cat of cats) {
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.appendChild(catBadge(cat));
    btn.appendChild(document.createTextNode(` ${UCI_CAT_LABEL[cat] ?? cat}`));
    btn.addEventListener("click", () => {
      tabs.querySelectorAll(".legend-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadCategoryResults(panel, race, cat);
    });
    tabs.appendChild(btn);
  }
  panel.appendChild(tabs);
  panel.appendChild(el("div", { class: "archive-panel-body" }));
  applyTwemoji(tabs);

  const defaultCat = cats[0]!;
  tabs.querySelector<HTMLElement>(".legend-item")?.classList.add("active");
  loadCategoryResults(panel, race, defaultCat);
}

// ── Country legend ───────────────────────────────────────────────────────
function buildCountryLegend(
  container: HTMLElement,
  races: GroupedRace[],
  onChange: (country: string | null) => void,
): string[] {
  const counts: Record<string, number> = {};
  for (const r of races) if (r.country) counts[r.country] = (counts[r.country] ?? 0) + 1;
  const sorted = Object.keys(counts).sort((a, b) => counts[b]! - counts[a]!);

  for (const country of sorted) {
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.dataset["value"] = country;
    btn.appendChild(el("span", {}, `${flagEmoji(country)} ${country} (${counts[country]})`));
    container.appendChild(btn);
  }
  container.addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLElement>(".legend-item");
    if (!btn) return;
    const wasActive = btn.classList.contains("active");
    container.querySelectorAll(".legend-item").forEach((b) => b.classList.remove("active"));
    if (wasActive) { onChange(null); return; }
    btn.classList.add("active");
    onChange(btn.dataset["value"] ?? null);
  });
  return sorted;
}

// ── Boot ─────────────────────────────────────────────────────────────────
(async () => {
  const loading         = $<HTMLElement>("#loading");
  const content         = $<HTMLElement>("#content");
  const tableArea       = $<HTMLElement>("#table-area");
  const searchInput     = $<HTMLInputElement>("#search-input");
  const countEl         = $<HTMLElement>("#archive-count");
  const countryLegendEl = $<HTMLElement>("#country-legend");
  const resultsPanel    = $<HTMLElement>("#results-panel");

  let raw: UciArchiveRace[];
  let meta: Record<string, string>;
  try {
    [raw, meta] = await Promise.all([getUciArchive(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  $<HTMLElement>("#generated-at").textContent = meta["generated_at"] ?? "";

  const races = groupByCompetition(raw);
  const countries = new Set(races.map((r) => r.country).filter(Boolean));
  countEl.textContent = `${races.length} races across ${countries.size} countries`;

  let activeCountry: string | null = null;

  function updateUrl(): void {
    const p = new URLSearchParams();
    if (searchInput.value.trim()) p.set("search", searchInput.value.trim());
    if (activeCountry) p.set("country", activeCountry);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function applyFilters(): void {
    const q = searchInput.value.trim().toLowerCase();
    tableArea.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      const matchesCountry = !activeCountry || row.dataset["country"] === activeCountry;
      const matchesText    = !q || (row.textContent ?? "").toLowerCase().includes(q);
      row.style.display = matchesCountry && matchesText ? "" : "none";
    });
    updateUrl();
  }

  buildCountryLegend(countryLegendEl, races, (country) => { activeCountry = country; applyFilters(); });
  searchInput.addEventListener("input", applyFilters);

  tableArea.appendChild(buildTable(races, (race) => openResultsPanel(resultsPanel, race)));
  applyTwemoji(tableArea);
  applyTwemoji(countryLegendEl);

  // Restore filters from URL query params
  const urlParams       = new URLSearchParams(location.search);
  const restoredSearch  = urlParams.get("search") ?? "";
  const restoredCountry = urlParams.get("country") ?? "";
  if (restoredSearch) searchInput.value = restoredSearch;
  if (restoredCountry) {
    activeCountry = restoredCountry;
    countryLegendEl.querySelectorAll<HTMLElement>(".legend-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset["value"] === restoredCountry);
    });
  }
  if (restoredSearch || restoredCountry) applyFilters();

  loading.style.display = "none";
  content.style.display = "block";
})();
