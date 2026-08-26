import { getUciArchive, getMeta, UciArchiveRace } from "./api.js";
import { catBadge, el } from "./raceStats.js";
import { GroupedRace, groupByCompetition, sortedCategories } from "./uciArchive.js";
import { $, flagEmoji, applyTwemoji } from "./utils.js";

function openRace(race: GroupedRace): void {
  // Stash this race's metadata so race.html can render instantly instead of
  // re-fetching and re-grouping the whole archive just to find one row.
  sessionStorage.setItem(`uci_race_${race.xco_race_id}`, JSON.stringify(race));
  const params = new URLSearchParams({ id: race.xco_race_id, from: location.href });
  location.href = `./race.html?${params.toString()}`;
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

// ── Country legend ───────────────────────────────────────────────────────
function buildCountryLegend(
  container: HTMLElement,
  races: GroupedRace[],
  onChange: (country: string | null) => void,
): void {
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
}

// ── Boot ─────────────────────────────────────────────────────────────────
(async () => {
  const loading         = $<HTMLElement>("#loading");
  const content         = $<HTMLElement>("#content");
  const tableArea       = $<HTMLElement>("#table-area");
  const searchInput     = $<HTMLInputElement>("#search-input");
  const countEl         = $<HTMLElement>("#archive-count");
  const countryLegendEl = $<HTMLElement>("#country-legend");

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

  tableArea.appendChild(buildTable(races, openRace));
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
