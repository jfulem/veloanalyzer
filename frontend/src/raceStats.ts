// Shared by the landing page and the race overview, both of which were
// previously rendered ahead of time by scripts/generate_site.py.

// See the note in api.ts — same-origin by default.
const API_BASE = (import.meta.env["VITE_API_BASE"] ?? "").replace(/\/$/, "");

export interface RaceStat {
  id: number;
  slug: string;
  name: string;
  date: string;
  uci_category: string;
  category: string;
  total: number;
  ranked: number;
  best: number | null;
  avg: number | null;
}

export interface SiteStats {
  races: number;
  riders: number;
  entries: number;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`${path} → ${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export const getRaceStats = () => getJson<RaceStat[]>("/api/races/stats");
export const getSiteStats = () => getJson<SiteStats>("/api/stats");
export const getMeta      = () => getJson<Record<string, string>>("/api/meta");

export const UCI_CAT_COLOR: Record<string, string> = {
  ME: "#68d391", MJ: "#90cdf4", WE: "#f6ad55",
  WJ: "#f687b3", MU23: "#76e4f7", WU23: "#b794f4",
};

export const UCI_CAT_LABEL: Record<string, string> = {
  ME: "Men Elite", MJ: "Men Juniors", WE: "Women Elite",
  WJ: "Women Juniors", MU23: "Men U23", WU23: "Women U23",
};

/** Category pill. Returns an element rather than an HTML string so nothing
 *  built from API data is ever interpolated into innerHTML. */
export function catBadge(uciCat: string): HTMLElement {
  const color = UCI_CAT_COLOR[uciCat] ?? "#a0aec0";
  const span = document.createElement("span");
  span.className = "cat-badge";
  span.style.cssText = `background:${color}22; color:${color}; border:1px solid ${color}66`;
  span.textContent = uciCat || "—";
  return span;
}

/** Today at 00:00 UTC, for splitting upcoming from past. */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function el(tag: string, attrs: Record<string, string> = {}, text?: string): HTMLElement {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
