import twemoji from "twemoji";

// IOC 3-letter code → ISO 3166-1 alpha-2 (for flag emoji)
const IOC_TO_ISO2: Record<string, string> = {
  CZE:"CZ", SVK:"SK", GER:"DE", AUT:"AT", POL:"PL", HUN:"HU", SUI:"CH",
  FRA:"FR", ITA:"IT", ESP:"ES", BEL:"BE", NED:"NL", DEN:"DK", NOR:"NO",
  SWE:"SE", FIN:"FI", GBR:"GB", IRL:"IE", POR:"PT", ROM:"RO", BUL:"BG",
  SRB:"RS", CRO:"HR", SLO:"SI", BIH:"BA", MKD:"MK", ALB:"AL", MNE:"ME",
  LVA:"LV", LTU:"LT", EST:"EE", UKR:"UA", RUS:"RU", BLR:"BY", GEO:"GE",
  ARM:"AM", AZE:"AZ", KAZ:"KZ", TUR:"TR", ISR:"IL", RSA:"ZA", AUS:"AU",
  NZL:"NZ", CAN:"CA", USA:"US", BRA:"BR", ARG:"AR", MEX:"MX", COL:"CO",
  CHI:"CL", URU:"UY", ECU:"EC", PER:"PE", VEN:"VE", GRE:"GR", CYP:"CY",
  MLT:"MT", LUX:"LU", AND:"AD", SMR:"SM", MON:"MC", ISL:"IS",
};

export function flagEmoji(country: string): string {
  const iso2 = IOC_TO_ISO2[country] ?? country.slice(0, 2).toUpperCase();
  if (iso2.length !== 2) return "";
  // Regional indicator letters: 0x1F1E6 = 🇦
  const cp = (c: string) => 0x1f1e6 + c.charCodeAt(0) - 65;
  return String.fromCodePoint(cp(iso2[0]!), cp(iso2[1]!));
}

// Windows has no native flag-emoji glyphs (regional indicator pairs render as
// bare letters), so replace flagEmoji() output with Twemoji SVGs after render.
export function applyTwemoji(node: HTMLElement): void {
  try {
    twemoji.parse(node, { folder: "svg", ext: ".svg" });
  } catch {
    // non-fatal — falls back to the native emoji glyph
  }
}

export function rankDisp(rank: number | null): string {
  return rank != null ? `#${rank}` : "—";
}

export function posLabel(rank: number | null): string {
  if (rank == null) return "—";
  const s = ["th", "st", "nd", "rd"];
  const v = rank % 100;
  return `${rank}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
}

export function parseTimeSecs(t: string): number | null {
  if (!t || t === "OVL" || t === "DNF" || t === "DNS") return null;
  const clean = t.replace(/^[+\s]+/, "");
  const parts = clean.split(":").map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return parts[0]! * 3600 + parts[1]! * 60 + parts[2]!;
  if (parts.length === 2) return parts[0]! * 60 + parts[1]!;
  return parts[0]!;
}

export function timeGap(t1: string, t2: string): string {
  const s1 = parseTimeSecs(t1);
  const s2 = parseTimeSecs(t2);
  if (s1 == null || s2 == null) return "";
  const diff = Math.abs(s1 - s2);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  const prefix = s1 > s2 ? "+" : "-";
  return h > 0 ? `${prefix}${h}:${mm}:${ss}` : `${prefix}${mm}:${ss}`;
}

export function tierClass(rank: number | null): string {
  if (rank == null) return "tier-unranked";
  if (rank <= 50) return "tier-top50";
  if (rank <= 200) return "tier-top200";
  return "tier-ranked";
}

const _MONTHS: Record<string, number> = {
  Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12,
};

/** Parse "01 - 02 Apr 2023" or "01 Jun 2024" → Unix ms (uses end date of ranges). Returns 0 on failure. */
export function parseResultDate(s: string): number {
  const hits = [...s.matchAll(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/g)];
  const m = hits[hits.length - 1]; // last match = end date for ranges
  if (!m) return 0;
  const month = _MONTHS[m[2]!] ?? 1;
  return Date.UTC(Number(m[3]), month - 1, Number(m[1]));
}

/** Start of the rolling window a UCI result still scores in.
 *
 *  Whole calendar months: the UCI drops a result on its anniversary (art.
 *  4.16.008 for MTB, C1026 for cyclo-cross). Mirrors ranking_window_start()
 *  in mtb_analyzer/ranking.py — the database deliberately keeps results after
 *  they stop scoring, because a rider's page is a timeline and not just a
 *  points sheet, so the two sides have to agree on where scoring stops.
 */
export function rankingWindowStart(now: Date = new Date(), monthsBack = 12): number {
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const day = d.getUTCDate();
  d.setUTCMonth(d.getUTCMonth() - monthsBack);
  // setUTCMonth overflows a short month (31 Aug minus 6 → 3 Mar), so pull the
  // date back onto the last day of the intended month when that happens.
  if (d.getUTCDate() !== day) d.setUTCDate(0);
  return d.getTime();
}

/** Does this result still contribute UCI points, or has it aged out? */
export function stillScoring(dateRaw: string, windowStart: number): boolean {
  const ms = parseResultDate(dateRaw);
  // A date we could not parse is left counting rather than silently zeroed —
  // dropping points on a formatting quirk would be the worse failure.
  return ms === 0 || ms >= windowStart;
}

export type Trend = "up" | "down" | "flat";

/**
 * Form trend from UCI points earned, comparing a rider's recent half of results
 * against their earlier half.
 *
 * Points rather than finishing positions, because positions are not comparable
 * across races: 54th in a UCI Junior Series field can be a better ride than 6th
 * at a local race, yet averaging raw positions treats the 54 as a collapse and
 * flips the arrow on the strength of one entry. UCI points already account for
 * both where a rider finished and how strong the race was.
 */
export function computeTrends(
  results: { rider_id: number; date: string; rank: number | null; uci_pts: number | null }[],
): Map<number, Trend> {
  // A DNF or DNS says nothing about form, so it is skipped — but a finish that
  // scored nothing is a real data point and counts as zero.
  const byRider = new Map<number, { pts: number; ms: number }[]>();
  for (const r of results) {
    if (r.rank == null) continue;
    if (!byRider.has(r.rider_id)) byRider.set(r.rider_id, []);
    byRider.get(r.rider_id)!.push({ pts: r.uci_pts ?? 0, ms: parseResultDate(r.date) });
  }

  const avg = (xs: number[]): number => xs.reduce((s, v) => s + v, 0) / xs.length;

  const out = new Map<number, Trend>();
  for (const [id, entries] of byRider) {
    const pts = entries.sort((a, b) => a.ms - b.ms).map((e) => e.pts);
    if (pts.length < 2) continue;

    const half = Math.max(1, Math.floor(pts.length / 2));
    const older     = pts.slice(0, half);
    const recent    = pts.slice(-half);
    const avgOlder  = avg(older);
    const avgRecent = avg(recent);
    const diff = avgRecent - avgOlder;    // positive = scoring more = improving

    // Relative threshold. Points scale enormously between a junior domestic
    // race and an Elite World Cup, so any fixed number of points would be
    // noise in one category and unreachable in the other. The floor of 1 stops
    // riders hovering near zero from flapping between arrows.
    const threshold = Math.max(1, Math.max(avgOlder, avgRecent) * 0.2);
    if (diff > threshold) out.set(id, "up");
    else if (diff < -threshold) out.set(id, "down");
    else out.set(id, "flat");
  }
  return out;
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs: Record<string, string> = {}, text = "",
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
  if (text) e.textContent = text;
  return e;
}

export function $<T extends Element>(sel: string, root: ParentNode = document): T {
  return root.querySelector<T>(sel)!;
}

export function $$<T extends Element>(sel: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(sel));
}
