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
  const h2hPanel    = $<HTMLElement>("#h2h-panel");
  const h2hBackdrop = $<HTMLElement>("#h2h-backdrop");
  const h2hClose    = $<HTMLElement>("#h2h-close");
  const loadingEl   = $<HTMLElement>("#loading");
  const appEl       = $<HTMLElement>("#app");
  const generatedAt = $<HTMLElement>("#generated-at");

  // ── Load race ────────────────────────────────────────────────────────────
  async function loadRace(race: Race, preserveSearch = false): Promise<void> {
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

    if (!preserveSearch) searchInput.value = "";
    else filterRiderTable(tableArea, searchInput.value);

    // Keep the hash in sync so the "from" URL passed to rider.html always
    // reflects the currently selected race and search term.
    updateHash(race.slug, searchInput.value);
  }

  function updateHash(slug: string, search: string): void {
    const p = new URLSearchParams({ race: slug });
    if (search) p.set("search", search);
    history.replaceState(null, "", `#${p.toString()}`);
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

  // ── Rider detail — full page navigation ─────────────────────────────────
  function openRiderCard(riderId: number): void {
    // Cache pre-loaded data so rider.html can render instantly without a
    // round trip. The rider page still fetches fresh data in the background
    // when opened from a context that didn't pre-load (riders list, direct link).
    const rider = currentRiders.find((r) => r.id === riderId);
    const results = currentResults.filter((r) => r.rider_id === riderId);
    if (rider) {
      try {
        sessionStorage.setItem(`rider_${riderId}`, JSON.stringify({ rider, results }));
      } catch { /* storage full — fall through to normal fetch */ }
    }
    location.href = `./rider.html?id=${riderId}&from=${encodeURIComponent(location.href)}`;
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // ── Search ───────────────────────────────────────────────────────────────
  searchInput.addEventListener("input", () => {
    filterRiderTable(tableArea, searchInput.value);
    const slug = races.find((r) => r.id === Number(raceSelect.value))?.slug ?? "";
    if (slug) updateHash(slug, searchInput.value);
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
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const requestedSlug = hashParams.get("race");
  const restoredSearch = hashParams.get("search") ?? "";
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
      loadRace(race, false).catch((err) => {
        raceName.textContent = `Failed to load race: ${err}`;
      });
    }
  });

  loadingEl.style.display = "none";
  appEl.style.display     = "block";

  if (races.length > 0) {
    const initial = requestedRace ?? races[0]!;
    raceSelect.value = String(initial.id);
    if (restoredSearch) searchInput.value = restoredSearch;
    await loadRace(initial, !!restoredSearch);
  } else {
    raceName.textContent = opts.emptyText;
  }
}
