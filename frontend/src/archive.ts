import {
  getUciArchive, getXcoRaceResults, getMeta,
  UciArchiveRace, XcoRaceFinisher,
} from "./api.js";
import { catBadge, el, UCI_CAT_LABEL } from "./raceStats.js";
import { renderRaceCountryChart } from "./ui/RaceCountryChart.js";
import { $, flagEmoji, applyTwemoji, posLabel } from "./utils.js";

// ── Table ────────────────────────────────────────────────────────────────
function buildRow(race: UciArchiveRace, onOpen: (race: UciArchiveRace) => void): HTMLTableRowElement {
  const tr = el("tr") as HTMLTableRowElement;
  tr.dataset["cat"]     = race.category;
  tr.dataset["country"] = race.country;
  tr.style.cursor = "pointer";
  tr.title = "Click to see full race results";
  tr.addEventListener("click", () => onOpen(race));

  tr.appendChild(el("td", {}, race.date || "—"));

  const nameTd = el("td", { class: "rc-race-link" });
  nameTd.appendChild(el("span", {}, race.comp_name || "—"));
  if (race.venue) nameTd.appendChild(el("span", { class: "time-label" }, race.venue));
  tr.appendChild(nameTd);

  tr.appendChild(el("td", { class: "country-cell" },
    race.country ? `${flagEmoji(race.country)} ${race.country}` : "—"));

  const catTd = el("td");
  catTd.appendChild(catBadge(race.category));
  tr.appendChild(catTd);

  tr.appendChild(el("td", { class: "num-cell" }, race.race_class || "—"));
  tr.appendChild(el("td", { class: "num-cell" }, String(race.finishers)));

  return tr;
}

function buildTable(races: UciArchiveRace[], onOpen: (race: UciArchiveRace) => void): HTMLTableElement {
  const table = el("table", { class: "rider-table" }) as HTMLTableElement;
  const thead = el("thead");
  const hRow  = el("tr");
  for (const h of ["Date", "Race", "Country", "Category", "Class", "Finishers"]) {
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
// One shared panel below the table, toggled open/closed by row clicks —
// mirrors RiderCard.ts's openRacePanel, minus the "is this me" highlighting
// that only makes sense inside a specific rider's own history.
let activePanelKey = "";

async function openResultsPanel(panel: HTMLElement, race: UciArchiveRace): Promise<void> {
  const key = `${race.xco_race_id}|${race.category}`;
  if (activePanelKey === key) {
    panel.setAttribute("hidden", "");
    activePanelKey = "";
    return;
  }
  activePanelKey = key;
  panel.removeAttribute("hidden");
  panel.innerHTML = "<p class='h2h-empty'>Loading…</p>";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  let finishers: XcoRaceFinisher[];
  try {
    finishers = await getXcoRaceResults(race.xco_race_id, race.category);
  } catch {
    panel.innerHTML = "<p class='h2h-empty'>Could not load race results.</p>";
    return;
  }
  if (activePanelKey !== key) return;   // user clicked a different row meanwhile

  panel.innerHTML = "";
  if (finishers.length === 0) {
    panel.appendChild(el("p", { class: "h2h-empty" }, "No results stored yet."));
    return;
  }

  panel.appendChild(el("p", { class: "section-title" },
    `${race.comp_name} — ${race.category} (${race.date})`));

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
  panel.appendChild(t);
  applyTwemoji(panel);

  requestAnimationFrame(() => panel.scrollIntoView({ behavior: "smooth", block: "nearest" }));
}

// ── Legends ──────────────────────────────────────────────────────────────
function buildToggleLegend(
  container: HTMLElement,
  items: [string, HTMLElement][],  // [value, label-element] pairs
  onChange: (value: string | null) => void,
): void {
  for (const [value, label] of items) {
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.dataset["value"] = value;
    btn.appendChild(label);
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
}

// ── Boot ─────────────────────────────────────────────────────────────────
(async () => {
  const loading      = $<HTMLElement>("#loading");
  const content       = $<HTMLElement>("#content");
  const tableArea      = $<HTMLElement>("#table-area");
  const countryChartArea = $<HTMLElement>("#country-chart-area");
  const searchInput   = $<HTMLInputElement>("#search-input");
  const countEl        = $<HTMLElement>("#archive-count");
  const catLegendEl     = $<HTMLElement>("#cat-legend");
  const countryLegendEl = $<HTMLElement>("#country-legend");
  const resultsPanel    = $<HTMLElement>("#results-panel");

  let races: UciArchiveRace[];
  let meta: Record<string, string>;
  try {
    [races, meta] = await Promise.all([getUciArchive(), getMeta()]);
  } catch (err) {
    loading.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  $<HTMLElement>("#generated-at").textContent = meta["generated_at"] ?? "";

  const distinctCompetitions = new Set(races.map((r) => r.xco_race_id)).size;
  const countries = new Set(races.map((r) => r.country).filter(Boolean));
  countEl.textContent = `${distinctCompetitions} races across ${countries.size} countries`;

  renderRaceCountryChart(countryChartArea, races);

  let activeCategory: string | null = null;
  let activeCountry: string | null  = null;

  function updateUrl(): void {
    const p = new URLSearchParams();
    if (searchInput.value.trim()) p.set("search", searchInput.value.trim());
    if (activeCategory) p.set("cat", activeCategory);
    if (activeCountry) p.set("country", activeCountry);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function applyFilters(): void {
    const q = searchInput.value.trim().toLowerCase();
    tableArea.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      const matchesCat     = !activeCategory || row.dataset["cat"] === activeCategory;
      const matchesCountry = !activeCountry  || row.dataset["country"] === activeCountry;
      const matchesText    = !q || (row.textContent ?? "").toLowerCase().includes(q);
      row.style.display = matchesCat && matchesCountry && matchesText ? "" : "none";
    });
    updateUrl();
  }

  const presentCats = new Set(races.map((r) => r.category).filter(Boolean));
  buildToggleLegend(
    catLegendEl,
    Object.entries(UCI_CAT_LABEL)
      .filter(([cat]) => presentCats.has(cat))
      .map(([cat, label]) => {
        const wrap = document.createElement("span");
        wrap.style.display = "flex";
        wrap.style.alignItems = "center";
        wrap.style.gap = ".3rem";
        wrap.appendChild(catBadge(cat));
        wrap.appendChild(document.createTextNode(label));
        return [cat, wrap] as [string, HTMLElement];
      }),
    (cat) => { activeCategory = cat; applyFilters(); },
  );

  const countryCounts: Record<string, number> = {};
  for (const r of races) if (r.country) countryCounts[r.country] = (countryCounts[r.country] ?? 0) + 1;
  const sortedCountries = Object.keys(countryCounts).sort((a, b) => countryCounts[b]! - countryCounts[a]!);
  buildToggleLegend(
    countryLegendEl,
    sortedCountries.map((c) => [c, el("span", {}, `${flagEmoji(c)} ${c}`)]),
    (country) => { activeCountry = country; applyFilters(); },
  );

  searchInput.addEventListener("input", applyFilters);

  tableArea.appendChild(buildTable(races, (race) => openResultsPanel(resultsPanel, race)));
  applyTwemoji(tableArea);
  applyTwemoji(countryLegendEl);

  // Restore filters from URL query params
  const urlParams       = new URLSearchParams(location.search);
  const restoredSearch  = urlParams.get("search") ?? "";
  const restoredCat     = urlParams.get("cat") ?? "";
  const restoredCountry = urlParams.get("country") ?? "";
  if (restoredSearch) searchInput.value = restoredSearch;
  if (restoredCat) {
    activeCategory = restoredCat;
    catLegendEl.querySelectorAll<HTMLElement>(".legend-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset["value"] === restoredCat);
    });
  }
  if (restoredCountry) {
    activeCountry = restoredCountry;
    countryLegendEl.querySelectorAll<HTMLElement>(".legend-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset["value"] === restoredCountry);
    });
  }
  if (restoredSearch || restoredCat || restoredCountry) applyFilters();

  loading.style.display = "none";
  content.style.display = "block";
})();
