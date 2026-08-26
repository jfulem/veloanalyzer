import { getUciArchive, getXcoRaceResults, getMeta, XcoRaceFinisher } from "./api.js";
import { catBadge, el, UCI_CAT_LABEL } from "./raceStats.js";
import { GroupedRace, groupByCompetition, sortedCategories } from "./uciArchive.js";
import { $, flagEmoji, applyTwemoji, posLabel } from "./utils.js";

const PAGE_LABELS: Record<string, string> = {
  "archive": "Archive",
};

function backLabel(fromUrl: string): string {
  try {
    const u = new URL(fromUrl, location.href);
    const stem = u.pathname.replace(/^.*\//, "").replace(/\.html$/, "");
    return PAGE_LABELS[stem] ?? "Back";
  } catch {
    return "Back";
  }
}

async function loadCategory(
  body: HTMLElement, race: GroupedRace, category: string, token: symbol, current: { value: symbol },
): Promise<void> {
  body.innerHTML = "<p class='h2h-empty'>Loading…</p>";

  let finishers: XcoRaceFinisher[];
  try {
    finishers = await getXcoRaceResults(race.xco_race_id, category);
  } catch {
    body.innerHTML = "<p class='h2h-empty'>Could not load race results.</p>";
    return;
  }
  if (current.value !== token) return;   // a different tab was clicked meanwhile

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

function renderRace(container: HTMLElement, race: GroupedRace, initialCat: string | null): void {
  container.innerHTML = "";
  document.title = `${race.comp_name} — VeloAnalyzer`;

  const header = el("div", { class: "rc-header" });
  header.appendChild(el("div", { class: "rc-name" }, race.comp_name || "—"));
  const sub = [race.date, race.venue, race.country ? `${flagEmoji(race.country)} ${race.country}` : ""]
    .filter(Boolean).join(" · ");
  header.appendChild(el("div", { class: "rc-meta" }, sub));
  container.appendChild(header);

  const cats = sortedCategories(race.categories);
  const tabs = el("div", { class: "cat-legend" });
  const body = el("div", { class: "archive-panel-body" });

  const current = { value: Symbol() };
  function selectCat(cat: string): void {
    tabs.querySelectorAll(".legend-item").forEach((b) => b.classList.remove("active"));
    tabs.querySelector<HTMLElement>(`[data-value="${cat}"]`)?.classList.add("active");
    const token = Symbol();
    current.value = token;
    loadCategory(body, race, cat, token, current);
  }

  for (const cat of cats) {
    const btn = el("button", { class: "legend-item" }) as HTMLButtonElement;
    btn.dataset["value"] = cat;
    btn.appendChild(catBadge(cat));
    btn.appendChild(document.createTextNode(` ${UCI_CAT_LABEL[cat] ?? cat}`));
    btn.addEventListener("click", () => selectCat(cat));
    tabs.appendChild(btn);
  }
  container.appendChild(tabs);
  container.appendChild(body);
  applyTwemoji(header);
  applyTwemoji(tabs);

  const defaultCat = initialCat && cats.includes(initialCat) ? initialCat : cats[0]!;
  selectCat(defaultCat);
}

(async () => {
  const params  = new URLSearchParams(location.search);
  const raceId  = params.get("id") ?? "";
  const initCat = params.get("cat");
  const fromUrl = params.get("from") ?? "";

  const backBar   = $<HTMLElement>("#back-bar");
  const loadingEl = $<HTMLElement>("#loading");
  const raceEl    = $<HTMLElement>("#race-content");

  const backBtn = el("a", { class: "rider-back-btn", href: fromUrl || "./archive.html" },
    `← ${backLabel(fromUrl)}`);
  backBar.appendChild(backBtn);

  if (!raceId) {
    loadingEl.textContent = "No race specified.";
    return;
  }

  getMeta().then((m) => {
    $<HTMLElement>("#generated-at").textContent = m["generated_at"] ?? "";
  }).catch(() => { /* non-critical */ });

  // Instant render when navigating from the archive list, which already has
  // this race's metadata in memory — avoids re-fetching + re-grouping the
  // whole archive just to find the one row the user already clicked.
  const cacheKey = `uci_race_${raceId}`;
  let race: GroupedRace | undefined;
  const cached = sessionStorage.getItem(cacheKey);
  if (cached) {
    try { race = JSON.parse(cached) as GroupedRace; } catch { /* corrupt cache — fall through */ }
    sessionStorage.removeItem(cacheKey);
  }

  if (!race) {
    // Direct link / reload: no shared-memory shortcut available, so pull the
    // whole archive and find this one race — there's no single-race endpoint,
    // and the browse page already fetches the same list this way.
    try {
      const all = await getUciArchive();
      race = groupByCompetition(all).find((r) => r.xco_race_id === raceId);
    } catch (err) {
      loadingEl.textContent = `Failed to load race: ${err}`;
      return;
    }
  }

  if (!race) {
    loadingEl.textContent = "Race not found.";
    return;
  }

  renderRace(raceEl, race, initCat);
  loadingEl.style.display = "none";
  raceEl.style.display = "block";
})();
