import sqlWasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { initDb, getRaces, getRiders, getResults, getMeta, Race, Rider, RaceResult } from "./db.js";
import { renderStatsBar } from "./ui/StatsBar.js";
import { renderCountryChart } from "./ui/CountryChart.js";
import { renderRiderTable, filterRiderTable } from "./ui/RiderTable.js";
import { renderH2H } from "./ui/H2H.js";
import { $ } from "./utils.js";

// ── State ──────────────────────────────────────────────────────────────────
let currentRiders: Rider[]     = [];
let currentResults: RaceResult[] = [];
const selectedIds = new Set<number>();

// ── DOM refs ───────────────────────────────────────────────────────────────
const raceSelect   = $<HTMLSelectElement>("#race-select");
const raceName     = $<HTMLElement>("#race-name");
const raceDate     = $<HTMLElement>("#race-date");
const raceCat      = $<HTMLElement>("#race-cat");
const statsArea    = $<HTMLElement>("#stats-area");
const searchInput  = $<HTMLInputElement>("#search-input");
const tableArea    = $<HTMLElement>("#table-area");
const countryArea  = $<HTMLElement>("#country-area");
const h2hPanel     = $<HTMLElement>("#h2h-panel");
const h2hClear     = $<HTMLElement>("#h2h-clear");
const loadingEl    = $<HTMLElement>("#loading");
const appEl        = $<HTMLElement>("#app");
const generatedAt  = $<HTMLElement>("#generated-at");

// ── Load race ──────────────────────────────────────────────────────────────
function loadRace(race: Race): void {
  selectedIds.clear();
  currentRiders  = getRiders(race.id);
  currentResults = getResults(currentRiders.map((r) => r.id));

  raceName.textContent = race.name;
  raceDate.textContent = race.date || "";
  raceCat.textContent  = `${race.category} · ${race.uci_category}`;

  renderStatsBar(statsArea, currentRiders);
  renderRiderTable(tableArea, currentRiders, selectedIds, onSelect);
  renderCountryChart(countryArea, currentRiders);
  renderH2H(h2hPanel, currentRiders, currentResults, [...selectedIds]);
  searchInput.value = "";
}

// ── Selection ──────────────────────────────────────────────────────────────
function onSelect(riderId: number): void {
  if (selectedIds.has(riderId)) {
    selectedIds.delete(riderId);
  } else {
    if (selectedIds.size >= 2) {
      // Drop the oldest selection
      const [first] = selectedIds;
      selectedIds.delete(first!);
    }
    selectedIds.add(riderId);
  }
  // Update row highlight without full re-render
  tableArea.querySelectorAll<HTMLTableRowElement>("tr[data-rider-id]").forEach((row) => {
    const id = Number(row.dataset["riderId"]);
    row.classList.toggle("selected", selectedIds.has(id));
  });
  renderH2H(h2hPanel, currentRiders, currentResults, [...selectedIds]);
}

h2hClear.addEventListener("click", () => {
  selectedIds.clear();
  tableArea.querySelectorAll<HTMLTableRowElement>("tr[data-rider-id]").forEach((row) => {
    row.classList.remove("selected");
  });
  h2hPanel.innerHTML = "";
});

// ── Search ─────────────────────────────────────────────────────────────────
searchInput.addEventListener("input", () => {
  filterRiderTable(tableArea, searchInput.value);
});

// ── Boot ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    await initDb(sqlWasmUrl, "data.db");
  } catch (err) {
    loadingEl.textContent = `Failed to load database: ${err}`;
    return;
  }

  const meta  = getMeta();
  const races = getRaces();

  generatedAt.textContent = meta["generated_at"] ?? "";

  for (const race of races) {
    const opt = document.createElement("option");
    opt.value = String(race.id);
    opt.textContent = `${race.name}${race.date ? ` (${race.date})` : ""}`;
    raceSelect.appendChild(opt);
  }

  raceSelect.addEventListener("change", () => {
    const id = Number(raceSelect.value);
    const race = races.find((r) => r.id === id);
    if (race) loadRace(race);
  });

  loadingEl.style.display = "none";
  appEl.style.display     = "block";

  if (races.length > 0) loadRace(races[0]!);
})();
