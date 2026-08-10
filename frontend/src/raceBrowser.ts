// Shared by app.html (upcoming start lists) and results.html (races that have
// finished). Both pages use the identical race-select + stats + rider table +
// H2H + rider-card modal experience — the only thing that differs is which
// races populate the dropdown and what to say when there are none. Keeping
// one implementation means a fix to, say, H2H selection only has to happen
// once rather than being applied to two copies that will inevitably drift.

import { getRaces, getRiders, getResults, getMeta, Race, Rider, RaceResult } from "./api.js";
import { renderStatsBar } from "./ui/StatsBar.js";
import { renderCountryChart } from "./ui/CountryChart.js";
import { renderRiderTable, filterRiderTable } from "./ui/RiderTable.js";
import { renderH2H } from "./ui/H2H.js";
import { renderRiderCard } from "./ui/RiderCard.js";
import { renderTeamChart } from "./ui/TeamChart.js";
import { $, computeTrends } from "./utils.js";

export interface RaceBrowserOptions {
  /** Already filtered and sorted into the order the dropdown should show. */
  getDisplayRaces: () => Promise<Race[]>;
  /** Shown in place of the race view when getDisplayRaces() returns none. */
  emptyText: string;
}

export async function bootRaceBrowser(opts: RaceBrowserOptions): Promise<void> {
  // ── State ────────────────────────────────────────────────────────────────
  let currentRiders: Rider[]       = [];
  let currentResults: RaceResult[] = [];
  const selectedIds = new Set<number>();

  // ── DOM refs ─────────────────────────────────────────────────────────────
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

  // ── Load race ────────────────────────────────────────────────────────────
  async function loadRace(race: Race): Promise<void> {
    selectedIds.clear();
    // Both requests are independent, so overlap them rather than paying two
    // round trips in series.
    [currentRiders, currentResults] = await Promise.all([
      getRiders(race.slug),
      getResults(race.slug),
    ]);

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

  // ── Selection ────────────────────────────────────────────────────────────
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

  // ── Rider detail modal ───────────────────────────────────────────────────
  function openRiderCard(riderId: number): void {
    const rider = currentRiders.find((r) => r.id === riderId);
    if (!rider) return;
    // The whole field's history is already loaded, so the card opens instantly
    // instead of waiting on a request.
    const results = currentResults.filter((r) => r.rider_id === riderId);
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

  // ── Search ───────────────────────────────────────────────────────────────
  searchInput.addEventListener("input", () => {
    filterRiderTable(tableArea, searchInput.value);
  });

  // ── Boot ─────────────────────────────────────────────────────────────────
  let meta: Record<string, string>;
  let races: Race[];
  // The full, unfiltered list — kept only to resolve a #race=<slug> deep link
  // that points outside this page's own scope (e.g. a results.html link
  // opened before that race had any results, or vice versa). Fetched
  // separately from the display list because the two are filtered differently.
  let allRaces: Race[];
  try {
    [meta, races, allRaces] = await Promise.all([getMeta(), opts.getDisplayRaces(), getRaces()]);
  } catch (err) {
    loadingEl.textContent = `Failed to reach the API: ${err}`;
    return;
  }

  // A hash fragment is used instead of a query string because static file
  // servers (e.g. `serve`'s clean-URLs redirect from /app.html -> /app) can
  // drop query strings on redirect; fragments are client-side only and
  // always survive.
  const requestedSlug = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("race");
  const requestedRace = requestedSlug
    ? allRaces.find((r) => r.slug === requestedSlug)
    : undefined;
  if (requestedRace && !races.some((r) => r.id === requestedRace.id)) {
    races.unshift(requestedRace);
  }

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
    if (race) {
      loadRace(race).catch((err) => {
        raceName.textContent = `Failed to load race: ${err}`;
      });
    }
  });

  loadingEl.style.display = "none";
  appEl.style.display     = "block";

  if (races.length > 0) {
    const initial = requestedRace ?? races[0]!;
    raceSelect.value = String(initial.id);
    await loadRace(initial);
  } else {
    raceName.textContent = opts.emptyText;
  }
}
