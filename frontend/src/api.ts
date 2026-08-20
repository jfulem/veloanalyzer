// Replaces the sql.js layer that downloaded the whole database into the
// browser. The exported names and the Race/Rider/RaceResult shapes are
// unchanged from that version, so the ui/ components did not need touching —
// the functions are simply async now, and keyed by race slug rather than by a
// row id that only meant something inside the baked file.

// Empty by default: the Worker is routed on /api/* of the same domain that
// serves this page, so requests are relative and no CORS preflight happens.
// `vite dev` proxies /api to a local `wrangler dev` (see vite.config.ts).
// Override only to point a preview build at a different API.
const API_BASE = (import.meta.env["VITE_API_BASE"] ?? "").replace(/\/$/, "");

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`${path} → ${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export interface Race {
  id: number;
  slug: string;
  name: string;
  date: string;
  uci_category: string;
  category: string;
}

export interface Rider {
  id: number;
  race_id: number;
  first_name: string;
  last_name: string;
  corrected_name: string;
  country: string;
  birth_year: string;
  start_nr: string;
  uci_id: string;
  uci_rank: number | null;
  uci_points: number | null;
  cp_xco_points: number | null;
  computed_points: number | null;
  result_rank: number | null;
  result_time: string | null;
  team: string;
  category: string;
  match_confidence: number;
  xcodata_slug: string;
  race_name: string;
  /** Date of this rider's most recent point-scoring result (YYYY-MM-DD), or
   *  null if they have never scored. Used server-side as the UCI tie-break
   *  between riders on equal points. */
  last_points_date: string | null;
}

export interface RaceResult {
  id: number;
  rider_id: number;
  xco_race_id: string;
  race_name: string;
  date: string;
  location: string;
  rank: number | null;
  time: string;
  cat: string;
  uci_pts: number | null;
  /** UCI competition class: '1', '2', '3', 'HC', 'CS', 'CN', 'S1'... Empty for
   *  World Cups and World Championships, which carry no class code. */
  race_class: string;
}

export interface RiderListItem {
  id: number;
  first_name: string;
  last_name: string;
  country: string;
  birth_year: string;
  uci_id: string;
  xcodata_slug: string;
  /** All four fields below come from the rider's most recent race_entries row
   *  — the closest thing to a "current" value, since none of these live on
   *  the rider record itself. */
  uci_rank: number | null;
  uci_points: number | null;
  team: string;
  uci_category: string;
  races_count: number;
}

/** Bare identity plus the same "most recent entry" fields as RiderListItem.
 *  Deliberately not the full race-context Rider shape — this is for opening a
 *  profile with no specific race in view. */
export interface RiderDetail {
  id: number;
  uci_id: string;
  first_name: string;
  last_name: string;
  birth_year: string;
  country: string;
  xcodata_slug: string;
  uci_rank: number | null;
  uci_points: number | null;
  team: string;
  uci_category: string;
}

export function getMeta(): Promise<Record<string, string>> {
  return getJson<Record<string, string>>("/api/meta");
}

export function getRaces(): Promise<Race[]> {
  return getJson<Race[]>("/api/races");
}

export function getRiders(slug: string): Promise<Rider[]> {
  return getJson<Rider[]>(`/api/races/${encodeURIComponent(slug)}/entries`);
}

/** Every history row for everyone in the race, in one request. The head-to-head
 *  panel and the form-trend arrows both need the whole field at once. */
export function getResults(slug: string): Promise<RaceResult[]> {
  return getJson<RaceResult[]>(`/api/races/${encodeURIComponent(slug)}/results`);
}

/** Every rider ever tracked, independent of any one race. */
export function getAllRiders(): Promise<RiderListItem[]> {
  return getJson<RiderListItem[]>("/api/riders");
}

export function getRiderDetail(id: number): Promise<RiderDetail> {
  return getJson<RiderDetail>(`/api/riders/${id}`);
}

export function getRiderHistory(id: number): Promise<RaceResult[]> {
  return getJson<RaceResult[]>(`/api/riders/${id}/results`);
}

export interface XcoRaceFinisher {
  rank: number | null;
  first_name: string;
  last_name: string;
  nationality: string;
  race_time: string;
  uci_pts: number | null;
  comp_name: string;
  date: string;
  race_class: string;
}

export function getXcoRaceResults(xcoRaceId: string, category: string): Promise<XcoRaceFinisher[]> {
  return getJson<XcoRaceFinisher[]>(
    `/api/xco-race/${encodeURIComponent(category)}/${encodeURIComponent(xcoRaceId)}`,
  );
}
