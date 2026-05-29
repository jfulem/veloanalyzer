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

export type Trend = "up" | "down" | "flat";

export function computeTrends(
  results: { rider_id: number; date: string; rank: number | null }[],
): Map<number, Trend> {
  // Group ranked results by rider, sort ascending by date
  const byRider = new Map<number, number[]>();
  for (const r of results) {
    if (r.rank == null) continue;
    if (!byRider.has(r.rider_id)) byRider.set(r.rider_id, []);
    byRider.get(r.rider_id)!.push(r.rank);
  }

  const out = new Map<number, Trend>();
  for (const [id, ranks] of byRider) {
    if (ranks.length < 2) continue;
    const half = Math.max(1, Math.floor(ranks.length / 2));
    const recent = ranks.slice(-half);
    const older  = ranks.slice(0, half);
    const avgRecent = recent.reduce((s, v) => s + v, 0) / recent.length;
    const avgOlder  = older.reduce((s, v) => s + v, 0) / older.length;
    const diff = avgOlder - avgRecent; // positive = improved (lower rank = better)
    if (diff > 1.5) out.set(id, "up");
    else if (diff < -1.5) out.set(id, "down");
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
