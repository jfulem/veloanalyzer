import sqlWasmUrl from "sql.js/dist/sql-wasm.wasm?url";
import { initDb, getRaces, getRiders, getResults, getMeta, Race, Rider, RaceResult } from "./db.js";
import { renderStatsBar } from "./ui/StatsBar.js";
import { renderCountryChart } from "./ui/CountryChart.js";
import { renderRiderTable, filterRiderTable } from "./ui/RiderTable.js";
import { renderH2H } from "./ui/H2H.js";
import { renderRiderCard } from "./ui/RiderCard.js";
import { renderTeamChart } from "./ui/TeamChart.js";
import { $, computeTrends } from "./utils.js";

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
const teamArea     = $<HTMLElement>("#team-area");
const h2hPanel      = $<HTMLElement>("#h2h-panel");
const h2hBackdrop   = $<HTMLElement>("#h2h-backdrop");
const h2hClose      = $<HTMLElement>("#h2h-close");
const riderCard     = $<HTMLElement>("#rider-card");
const riderBackdrop = $<HTMLElement>("#rider-backdrop");
const riderClose    = $<HTMLElement>("#rider-close");
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

  const trends = computeTrends(currentResults);
  renderStatsBar(statsArea, currentRiders);
  renderRiderTable(tableArea, currentRiders, selectedIds, onSelect, openRiderCard, trends);
  renderCountryChart(countryArea, currentRiders);
  renderTeamChart(teamArea, currentRiders);
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
  if (selectedIds.size === 2) {
    renderH2H(h2hPanel, currentRiders, currentResults, [...selectedIds]);
    h2hBackdrop.removeAttribute("hidden");
    document.body.style.overflow = "hidden";
  }
}

function closeModal(): void {
  h2hBackdrop.setAttribute("hidden", "");
  document.body.style.overflow = "";
  selectedIds.clear();
  tableArea.querySelectorAll<HTMLTableRowElement>("tr[data-rider-id]").forEach((row) => {
    row.classList.remove("selected");
  });
}

h2hClose.addEventListener("click", closeModal);
h2hBackdrop.addEventListener("click", (e) => {
  if (e.target === h2hBackdrop) closeModal();
});

// ── Rider detail modal ─────────────────────────────────────────────────────
function openRiderCard(riderId: number): void {
  const rider = currentRiders.find((r) => r.id === riderId);
  if (!rider) return;
  const results = getResults([riderId]);
  renderRiderCard(riderCard, rider, results);
  riderBackdrop.removeAttribute("hidden");
  document.body.style.overflow = "hidden";
}

function closeRiderCard(): void {
  riderBackdrop.setAttribute("hidden", "");
  document.body.style.overflow = "";
}

riderClose.addEventListener("click", closeRiderCard);
riderBackdrop.addEventListener("click", (e) => {
  if (e.target === riderBackdrop) closeRiderCard();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!riderBackdrop.hasAttribute("hidden")) closeRiderCard();
    else closeModal();
  }
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
  const allRaces = getRaces();
  const races = allRaces.filter((r) => {
    if (!r.date) return true;
    const cutoff = new Date(r.date);
    cutoff.setHours(20, 0, 0, 0);
    return new Date() <= cutoff;
  });

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

  if (races.length > 0) {
    loadRace(races[0]!);
  } else {
    $<HTMLElement>("#race-name").textContent = "No upcoming races";
  }
})();
