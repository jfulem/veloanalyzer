import { Rider, RaceResult, XcoRaceFinisher, getXcoRaceResults } from "../api.js";
import { flagEmoji, posLabel, tierClass, el, parseResultDate, applyTwemoji,
         rankingWindowStart, stillScoring } from "../utils.js";

type SortCol = "date" | "race" | "cat" | "class" | "rank" | "time" | "pts";
type SortDir = "asc" | "desc";

const ALL_COL_HEADERS: { key: SortCol; label: string }[] = [
  { key: "date",  label: "Date" },
  { key: "race",  label: "Race" },
  { key: "cat",   label: "Cat" },
  { key: "class", label: "Class" },
  { key: "rank",  label: "Pos" },
  { key: "time",  label: "Time" },
  { key: "pts",   label: "Pts" },
];

// Short label for the per-row Class column, plus a full name for its tooltip —
// the codes themselves (especially the French-derived CN/CDM/CM) are not
// self-explanatory on sight.
const RACE_CLASS_INFO: Record<string, [string, string]> = {
  "1":  ["C1", "Class 1"],
  "2":  ["C2", "Class 2"],
  "3":  ["C3", "Class 3"],
  HC:   ["HC", "Hors Classe"],
  CS:   ["CS", "Continental Series"],
  CN:   ["NC", "National Championships"],
  CDM:  ["WC", "World Cup"],
  CM:   ["WCh", "World Championships"],
  CC:   ["CC", "Continental Championships"],
  SHC:  ["SHC", "Stage race — Hors Classe"],
  S1:   ["S1", "Stage race — Class 1"],
  S2:   ["S2", "Stage race — Class 2"],
};

function raceClassShort(cls: string): string {
  return RACE_CLASS_INFO[(cls || "").toUpperCase()]?.[0] ?? "—";
}

function raceClassTitle(cls: string): string {
  return RACE_CLASS_INFO[(cls || "").toUpperCase()]?.[1] ?? "Class not recorded";
}

function sortResults(results: RaceResult[], col: SortCol, dir: SortDir): RaceResult[] {
  return [...results].sort((a, b) => {
    let cmp = 0;
    switch (col) {
      case "date":  cmp = parseResultDate(a.date) - parseResultDate(b.date); break;
      case "race":  cmp = (a.race_name ?? "").localeCompare(b.race_name ?? ""); break;
      case "cat":   cmp = (a.cat ?? "").localeCompare(b.cat ?? ""); break;
      case "class": cmp = raceClassShort(a.race_class).localeCompare(raceClassShort(b.race_class)); break;
      case "rank":  cmp = (a.rank ?? 9999) - (b.rank ?? 9999); break;
      case "time":  cmp = (a.time ?? "").localeCompare(b.time ?? ""); break;
      case "pts":   cmp = (b.uci_pts ?? -1) - (a.uci_pts ?? -1); break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
}

// UCI MTB Rules Part IV, art. 4.16.008: only the best N single-race results
// count toward a rider's rolling ranking total (the rest show with "*" and
// are excluded on UCI's own individual ranking breakdown). Junior one-day
// events cap at 4, other classes at 5 — mirrors compute_points_from_history
// in mtb_analyzer/ranking.py.
// Art. 4.16.008 quotas. These are per bucket, not a single cap across the
// whole history: a rider can count 5 class-1 results *and* 5 class-2 results.
// Mirrors _CLASS_QUOTA / _points_bucket in mtb_analyzer/ranking.py — the two
// must agree or the card contradicts the ingest.
const CLASS_QUOTA: Record<string, number> = { HC: 5, CS: 5, "1": 5, "2": 5, "3": 5 };
// The UCI uses French abbreviations: CM = World Championships, CDM = World Cup,
// CC = Continental Championships, CN = National Championships. All uncapped.
const UNCAPPED_CLASSES = new Set(["CM", "CDM", "CC", "CN"]);
const STAGE_CLASSES = new Set(["SHC", "S1", "S2"]);
const STAGE_QUOTA = 3;
const JUNIOR_SERIES_QUOTA = 4;
const JUNIOR_QUOTA = 4;

const isJuniorSeries = (name: string) => (name || "").toLowerCase().includes("junior series");

/** Which quota bucket a result falls in, or null when it is uncapped.
 *  Uncapped covers World Championships, World Cup rounds, Continental
 *  Championships and National Championships. */
function pointsBucket(cat: string, raceClass: string, raceName: string): string | null {
  const cls = (raceClass || "").toUpperCase();
  // Before the junior split: World Cups and championships are uncapped for
  // juniors too, and checking the junior branch first would sweep a junior's
  // World Cup results into their best-4 quota.
  if (UNCAPPED_CLASSES.has(cls)) return null;
  if (STAGE_CLASSES.has(cls)) return "STAGE";
  // An unclassified event still belongs in a junior bucket — several Junior
  // Series rounds carry no class code at all.
  if (cat === "MJ" || cat === "WJ") return isJuniorSeries(raceName) ? "JS" : "J";
  return cls in CLASS_QUOTA ? cls : null;
}

function bucketQuota(bucket: string): number {
  if (bucket === "STAGE") return STAGE_QUOTA;
  if (bucket === "JS") return JUNIOR_SERIES_QUOTA;
  if (bucket === "J") return JUNIOR_QUOTA;
  return CLASS_QUOTA[bucket] ?? 0;
}

const UNCAPPED_KEY = "__UNCAPPED__";

/** Every scoring result grouped by quota bucket, uncapped results under one
 *  shared key. The single source both countingResultIds and the per-class
 *  summary build on, so a row's highlight and its group's summary line can
 *  never disagree about which bucket it belongs to. */
function groupByBucket(results: RaceResult[]): Map<string, RaceResult[]> {
  const cat = results.find((r) => r.cat)?.cat ?? "";
  const windowStart = rankingWindowStart();
  const groups = new Map<string, RaceResult[]>();
  for (const r of results) {
    if ((r.uci_pts ?? 0) <= 0) continue;
    // Expired results are still listed below — they happened — but the UCI has
    // already subtracted them, so they must not reach a quota or a total.
    if (!stillScoring(r.date, windowStart)) continue;
    const bucket = pointsBucket(cat, r.race_class, r.race_name) ?? UNCAPPED_KEY;
    const list = groups.get(bucket) ?? [];
    list.push(r);
    groups.set(bucket, list);
  }
  return groups;
}

/** The results that actually make up the UCI points total. Everything else is
 *  a real result that simply falls outside its bucket's quota. */
function countingResultIds(results: RaceResult[]): Set<number> {
  const counting = new Set<number>();
  for (const [bucket, list] of groupByBucket(results)) {
    if (bucket === UNCAPPED_KEY) {
      for (const r of list) counting.add(r.id);
      continue;
    }
    const sorted = [...list].sort((a, b) => (b.uci_pts ?? 0) - (a.uci_pts ?? 0));
    for (const r of sorted.slice(0, bucketQuota(bucket))) counting.add(r.id);
  }
  return counting;
}

function bucketLabel(bucket: string): string {
  if (bucket === UNCAPPED_KEY) return "World Cup / Championships";
  const labels: Record<string, string> = {
    HC: "Hors Classe", CS: "Continental Series",
    "1": "Class 1", "2": "Class 2", "3": "Class 3",
    STAGE: "Stage races", J: "Junior one-day", JS: "Junior Series",
  };
  return labels[bucket] ?? bucket;
}

interface BucketSummaryRow {
  label: string;
  scoring: number;
  counting: number;
  quota: number | null;      // null = uncapped
  points: number;
}

/** One row per class group the rider has scored in, points-descending — the
 *  biggest contributor to their total first. */
function summarizeByBucket(results: RaceResult[]): BucketSummaryRow[] {
  const rows: BucketSummaryRow[] = [];
  for (const [bucket, list] of groupByBucket(results)) {
    const uncapped = bucket === UNCAPPED_KEY;
    const quota = uncapped ? null : bucketQuota(bucket);
    const sorted = [...list].sort((a, b) => (b.uci_pts ?? 0) - (a.uci_pts ?? 0));
    const counted = uncapped ? sorted : sorted.slice(0, quota ?? 0);
    rows.push({
      label: bucketLabel(bucket),
      scoring: list.length,
      counting: counted.length,
      quota,
      points: counted.reduce((s, r) => s + (r.uci_pts ?? 0), 0),
    });
  }
  return rows.sort((a, b) => b.points - a.points);
}


function buildPointsChart(results: RaceResult[]): HTMLElement | null {
  const sorted = [...results]
    .filter((r) => r.uci_pts != null)
    .sort((a, b) => parseResultDate(a.date) - parseResultDate(b.date));

  if (sorted.length < 2) return null;

  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag: string, attrs: Record<string, string | number> = {}): Element => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };

  const W = 460, H = 110;
  const PL = 28, PR = 8, PT = 8, PB = 22;
  const CW = W - PL - PR, CH = H - PT - PB;

  const maxVal = Math.max(...sorted.map((r) => r.uci_pts!));
  const yMax   = maxVal > 0 ? Math.ceil(maxVal / 5) * 5 : 10;
  const n      = sorted.length;
  const xOf    = (i: number) => PL + (n > 1 ? (i / (n - 1)) * CW : CW / 2);
  const yOf    = (v: number) => PT + CH - (v / yMax) * CH;

  const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%" });

  // Gridlines + Y labels at 0, mid, max
  for (const frac of [0, 0.5, 1]) {
    const val = frac * yMax;
    const y   = yOf(val);
    svg.appendChild(mk("line", {
      x1: PL, y1: y, x2: W - PR, y2: y,
      stroke: frac === 0 ? "#4a5568" : "#2d3748", "stroke-width": 1,
    }));
    const lbl = mk("text", {
      x: PL - 4, y: y + 4,
      "text-anchor": "end", "font-size": 9, fill: "#718096",
    });
    lbl.textContent = String(Math.round(val));
    svg.appendChild(lbl);
  }

  // Area fill under line
  const areaCoords = [
    `${xOf(0)},${PT + CH}`,
    ...sorted.map((r, i) => `${xOf(i)},${yOf(r.uci_pts!)}`),
    `${xOf(n - 1)},${PT + CH}`,
  ].join(" ");
  svg.appendChild(mk("polygon", { points: areaCoords, fill: "rgba(99,179,237,0.10)" }));

  // Line
  svg.appendChild(mk("polyline", {
    points: sorted.map((r, i) => `${xOf(i)},${yOf(r.uci_pts!)}`).join(" "),
    fill: "none", stroke: "#63b3ed", "stroke-width": 2,
    "stroke-linejoin": "round", "stroke-linecap": "round",
  }));

  // Dots — filled if points scored, hollow-ish if zero
  for (let i = 0; i < n; i++) {
    const r = sorted[i]!;
    const g = mk("g");
    const title = mk("title");
    title.textContent = `${r.race_name} · ${r.date}: ${r.uci_pts} pts`;
    g.appendChild(title);
    g.appendChild(mk("circle", {
      cx: xOf(i), cy: yOf(r.uci_pts!), r: 4,
      fill: (r.uci_pts ?? 0) > 0 ? "#90cdf4" : "#4a5568",
      stroke: "#1a202c", "stroke-width": 1.5,
    }));
    svg.appendChild(g);
  }

  // X axis: labels at first, last and (if many races) midpoint
  const labelIdx = new Set<number>([0, n - 1]);
  if (n > 4) labelIdx.add(Math.round((n - 1) / 2));
  for (const i of labelIdx) {
    const r = sorted[i]!;
    const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
    const parts  = r.date.split(" ");
    const label  = parts.length === 3 ? `${parts[1]} '${parts[2]!.slice(2)}` : r.date;
    const lbl = mk("text", {
      x: xOf(i), y: H - 5,
      "text-anchor": anchor, "font-size": 9, fill: "#718096",
    });
    lbl.textContent = label;
    svg.appendChild(lbl);
  }

  const wrap = el("div", { class: "rc-chart" });
  wrap.appendChild(svg as unknown as HTMLElement);
  return wrap;
}

export function renderRiderCard(
  container: HTMLElement,
  rider: Rider,
  results: RaceResult[],
): void {
  container.innerHTML = "";

  const displayName = rider.corrected_name || `${rider.first_name} ${rider.last_name}`.trim();
  const ranked = results.filter((r) => r.rank != null);
  const bestRank = ranked.length ? Math.min(...ranked.map((r) => r.rank!)) : null;

  // ── Header ─────────────────────────────────────────────────────────────────
  const header = el("div", { class: "rc-header" });

  const nameRow = el("div", { class: "rc-name" });
  nameRow.textContent = `${rider.country ? flagEmoji(rider.country) + " " : ""}${displayName}`;
  header.appendChild(nameRow);

  const metaRow = el("div", { class: "rc-meta" });
  const metaParts: string[] = [];
  if (rider.country) metaParts.push(rider.country);
  if (rider.birth_year) metaParts.push(`Born ${rider.birth_year}`);
  if (rider.team) metaParts.push(rider.team);
  metaRow.textContent = metaParts.join(" · ");
  header.appendChild(metaRow);

  const uciRow = el("div", { class: "rc-uci" });
  const rankSpan = el("span", { class: `rc-rank ${tierClass(rider.uci_rank)}` });
  rankSpan.textContent = rider.uci_rank != null ? `#${rider.uci_rank} UCI` : "Unranked";
  uciRow.appendChild(rankSpan);
  if (rider.uci_points != null) {
    uciRow.appendChild(el("span", { class: "rc-pts" }, ` · ${rider.uci_points} pts`));
  }
  if (rider.xcodata_slug) {
    const xcoLink = el("a", {
      class: "xco-link",
      href: `https://www.xcodata.com${rider.xcodata_slug}`,
      target: "_blank",
    }, " ↗ xcodata");
    uciRow.appendChild(xcoLink);
  }
  header.appendChild(uciRow);
  container.appendChild(header);

  // ── Stats chips ────────────────────────────────────────────────────────────
  if (results.length > 0) {
    // Race counts cover the whole stored history — those are facts about the
    // rider. Anything measured in points follows the ranking window instead,
    // since points are the part that expires.
    const scoringWindow = rankingWindowStart();
    const current    = results.filter((r) => stillScoring(r.date, scoringWindow));
    const totalPts   = current.reduce((s, r) => s + (r.uci_pts ?? 0), 0);
    const finishers  = results.filter((r) => r.rank != null);
    const wins       = finishers.filter((r) => r.rank === 1).length;
    const podiums    = finishers.filter((r) => r.rank! <= 3).length;
    const ptsResults = current.filter((r) => r.uci_pts != null);
    const avgPts     = ptsResults.length
      ? (totalPts / ptsResults.length).toFixed(1)
      : "—";
    const stats = el("div", { class: "rc-stats" });
    for (const [label, value] of [
      ["Starts",  String(results.length)],
      ["Best",    bestRank != null ? posLabel(bestRank) : "—"],
      ["Wins",    String(wins)],
      ["Podiums", String(podiums)],
      ["Avg pts", avgPts],
    ] as [string, string][]) {
      const chip = el("div", { class: "rc-chip" });
      chip.appendChild(el("span", { class: "rc-chip-val" }, value));
      chip.appendChild(el("span", { class: "rc-chip-lbl" }, label));
      stats.appendChild(chip);
    }
    container.appendChild(stats);
  }

  // ── Form chart ─────────────────────────────────────────────────────────────
  const chart = buildPointsChart(results);
  if (chart) container.appendChild(chart);

  // ── Points by class ────────────────────────────────────────────────────────
  // The quota groups the highlighted rows below sum into, spelled out — how
  // many races scored in each, how many of those count, and what they add up
  // to — instead of leaving that arithmetic for the reader to do by eye.
  const bucketRows = summarizeByBucket(results);
  if (bucketRows.length > 0) {
    container.appendChild(el("p", { class: "section-title" }, "Points by class"));
    const bTable = el("table", { class: "h2h-table rc-bucket-table" });
    const bThead = el("thead");
    const bHeadRow = el("tr");
    for (const h of ["Class", "Races", "Counting", "Pts"]) bHeadRow.appendChild(el("th", {}, h));
    bThead.appendChild(bHeadRow);
    bTable.appendChild(bThead);

    const bTbody = el("tbody");
    for (const row of bucketRows) {
      const tr = el("tr");
      tr.appendChild(el("td", {}, row.label));
      tr.appendChild(el("td", { class: "num-cell" }, String(row.scoring)));
      tr.appendChild(el("td", { class: "num-cell" },
        row.quota == null ? "all" : `${row.counting}/${row.quota}`));
      tr.appendChild(el("td", { class: "num-cell", style: "color:#68d391; font-weight:700" },
        String(row.points)));
      bTbody.appendChild(tr);
    }
    bTable.appendChild(bTbody);
    container.appendChild(bTable);
  }

  // ── Race history table ─────────────────────────────────────────────────────
  container.appendChild(el("p", { class: "section-title" },
    `Race history (${results.length} result${results.length !== 1 ? "s" : ""})`));

  if (results.length === 0) {
    container.appendChild(el("p", { class: "h2h-empty" }, "No race history found."));
    return;
  }

  // Sort state
  let sortCol: SortCol = "date";
  let sortDir: SortDir = "desc";

  const hasTimes = results.some((r) => !!r.time);
  const hasPts   = results.some((r) => r.uci_pts != null);
  const hasClass = results.some((r) => !!r.race_class);
  const countingIds = countingResultIds(results);
  const windowStart = rankingWindowStart();
  const hasExpired  = results.some(
    (r) => (r.uci_pts ?? 0) > 0 && !stillScoring(r.date, windowStart));
  const COL_HEADERS = ALL_COL_HEADERS.filter((c) =>
    (c.key !== "time" || hasTimes) && (c.key !== "pts" || hasPts) && (c.key !== "class" || hasClass),
  );

  const table = el("table", { class: "h2h-table" });
  const thead = el("thead");
  const hRow = el("tr");
  thead.appendChild(hRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  table.appendChild(tbody);
  container.appendChild(table);

  function buildHeaders(): void {
    hRow.innerHTML = "";
    for (const { key, label } of COL_HEADERS) {
      const th = el("th", { class: "sortable-th" });
      const isActive = key === sortCol;
      th.textContent = label + (isActive ? (sortDir === "asc" ? " ↑" : " ↓") : "");
      th.style.cursor = "pointer";
      if (isActive) th.style.color = "#90cdf4";
      th.addEventListener("click", () => {
        if (sortCol === key) sortDir = sortDir === "asc" ? "desc" : "asc";
        else { sortCol = key; sortDir = key === "date" ? "desc" : "asc"; }
        buildHeaders();
        buildBody();
      });
      hRow.appendChild(th);
    }
  }

  // Panel shown below the table when the user clicks a race name
  const racePanel = el("div", { class: "rc-race-panel", hidden: "" });
  let activePanelKey = "";

  async function openRacePanel(res: RaceResult): Promise<void> {
    const key = `${res.xco_race_id}|${res.cat}`;
    if (activePanelKey === key) {
      // Toggle off
      racePanel.setAttribute("hidden", "");
      activePanelKey = "";
      return;
    }
    activePanelKey = key;
    racePanel.removeAttribute("hidden");
    racePanel.innerHTML = "<p class='h2h-empty'>Loading…</p>";
    racePanel.scrollIntoView({ behavior: "smooth", block: "nearest" });

    let finishers: XcoRaceFinisher[];
    try {
      finishers = await getXcoRaceResults(res.xco_race_id, res.cat);
    } catch {
      racePanel.innerHTML = "<p class='h2h-empty'>Could not load race results.</p>";
      return;
    }

    // Bail if the user clicked a different race before the fetch finished
    if (activePanelKey !== key) return;

    racePanel.innerHTML = "";
    if (finishers.length === 0) {
      racePanel.appendChild(el("p", { class: "h2h-empty" }, "No results stored yet."));
      return;
    }

    const header = finishers[0]!;
    racePanel.appendChild(el("p", { class: "section-title" },
      `${header.comp_name} — ${res.cat} (${header.date})`));

    const t = el("table", { class: "h2h-table" });
    const th = el("thead");
    const hr = el("tr");
    for (const h of ["Pos", "Name", "NAT", "Time", "Pts"]) hr.appendChild(el("th", {}, h));
    th.appendChild(hr);
    t.appendChild(th);

    const myFirst = rider.first_name.trim().toLowerCase();
    const myLast  = rider.last_name.trim().toLowerCase();
    let myRow: HTMLElement | null = null;

    const tb = el("tbody");
    for (const f of finishers) {
      const isMe = f.first_name.trim().toLowerCase() === myFirst
                && f.last_name.trim().toLowerCase()  === myLast;
      const tr = el("tr", isMe ? { class: "rc-me-row" } : {});
      if (isMe) myRow = tr;
      const posTd = el("td", { class: "num-cell" });
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
    racePanel.appendChild(t);

    // Scroll after the browser has laid out the now-full panel
    requestAnimationFrame(() => {
      (myRow ?? racePanel).scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  function buildBody(): void {
    tbody.innerHTML = "";
    for (const res of sortResults(results, sortCol, sortDir)) {
      const tr = el("tr");
      tr.appendChild(el("td", {}, res.date || "—"));

      // The UCI's own history feed often reuses one generic name across every
      // round of a domestic series (several "Czech Cup" rows with nothing but
      // the date to tell them apart), so the venue goes underneath whenever
      // the feed supplied one.
      const raceTd = el("td", { class: "rc-race-link" });
      raceTd.style.cursor = "pointer";
      raceTd.title = "Click to see full race results";
      raceTd.addEventListener("click", () => openRacePanel(res));
      raceTd.appendChild(el("span", {}, res.race_name || "—"));
      if (res.location) {
        raceTd.appendChild(el("span", { class: "time-label" }, res.location));
      }
      tr.appendChild(raceTd);

      tr.appendChild(el("td", {}, res.cat || "—"));

      if (hasClass) {
        const classTd = el("td", { style: "font-size:.82rem; color:#a0aec0" }, raceClassShort(res.race_class));
        classTd.title = raceClassTitle(res.race_class);
        tr.appendChild(classTd);
      }

      const posTd = el("td", {});
      const posSpan = el("span", {}, posLabel(res.rank));
      if (res.rank === 1) posSpan.style.color = "#f6e05e";
      else if (res.rank != null && res.rank <= 3) posSpan.style.fontWeight = "700";
      posTd.appendChild(posSpan);
      tr.appendChild(posTd);

      if (hasTimes) tr.appendChild(el("td", { style: "font-size:.82rem; color:#a0aec0" }, res.time || "—"));
      if (hasPts) {
        // Three states, because "not in the total" has two quite different
        // causes and conflating them misleads: a result can have aged out of
        // the rolling 12 months, or it can be a current result that simply
        // lost its bucket's best-N cut.
        const counts  = countingIds.has(res.id);
        const expired = !stillScoring(res.date, windowStart);
        const td = el("td", {
          style: counts
            ? "font-size:.82rem; color:#68d391; font-weight:700"
            : expired
              ? "font-size:.82rem; color:#718096; text-decoration:line-through"
              : "font-size:.82rem; color:#718096",
        }, res.uci_pts != null ? String(res.uci_pts) : "—");
        if (res.uci_pts != null && expired) {
          td.title = "Older than 12 months — the UCI has already subtracted "
            + "these points, so they are no longer in the total";
        } else if (res.uci_pts != null && !counts) {
          const cls = res.race_class ? `class ${res.race_class}` : "its class";
          td.title = `Outside this rider's counting results for ${cls}, so not included in the UCI points total`;
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  buildHeaders();
  buildBody();
  container.appendChild(racePanel);

  // Without this the dimming looks like missing data rather than a deliberate
  // distinction.
  // Also shown when nothing counts any more but something expired — otherwise
  // a rider whose every result has aged out gets struck-through points and no
  // explanation for them.
  if (hasPts && (countingIds.size > 0 || hasExpired)) {
    const note = el("p", {
      style: "font-size:.75rem; color:#718096; margin:.6rem 0 0; line-height:1.5",
    });
    const isJunior = ["MJ", "WJ"].includes(results.find((r) => r.cat)?.cat ?? "");
    note.appendChild(el("span", { style: "color:#68d391; font-weight:700" }, "Green"));
    note.appendChild(document.createTextNode(" points count toward the UCI total. "));
    note.appendChild(el("span", { style: "color:#718096" }, "Dimmed"));
    note.appendChild(document.createTextNode(
      " points are real results that fall outside their quota (art. 4.16.008): "
      + (isJunior
          ? "best 4 junior series and best 4 junior one-day results"
          : "best 5 per class for HC, Continental Series and classes 1–3, best 3 across stage races")
      + ". World Cups and championships count without limit.",
    ));
    if (hasExpired) {
      note.appendChild(document.createTextNode(" "));
      note.appendChild(el("span",
        { style: "color:#718096; text-decoration:line-through" }, "Struck-through"));
      note.appendChild(document.createTextNode(
        " points are older than 12 months: the ranking is a rolling window, so"
        + " the UCI has already subtracted them. The races stay listed here.",
      ));
    }
    container.appendChild(note);
  }

  applyTwemoji(container);
}
