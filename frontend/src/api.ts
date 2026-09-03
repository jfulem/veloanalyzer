import { apiQuery } from "./discipline.js";

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

// Every read is scoped to the active discipline. Routes addressed by race slug
// or rider id ignore the parameter where the row itself already settles the
// question — see the Worker — so passing it everywhere is safe and keeps the
// call sites from having to remember which is which.
async function getJson<T>(path: string): Promise<T> {
  const url = `${API_BASE}${apiQuery(path)}`;
  const resp = await fetch(url);
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
  /** 'XCO' or 'CX'. */
  discipline: string;
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
  /** UCI competition class. MTB writes bare digits ('1', '2', '3') plus 'HC',
   *  'CS', 'S1'...; cyclo-cross writes 'C1', 'C2', 'CMM'. Both use 'CN' for a
   *  national championship, and both leave it empty for World Cups and World
   *  Championships, which carry no class code. */
  race_class: string;
  discipline?: string;
}

export interface RiderListItem {
  id: number;
  first_name: string;
  last_name: string;
  country: string;
  birth_year: string;
  uci_id: string;
  xcodata_slug: string;
  /** rank/points/category prefer the official UCI ranking (refreshed every
   *  ingest) over the rider's most recent race_entries snapshot, which is
   *  only as fresh as whenever that one start list was last scraped. team
   *  prefers race_entries — who they're actually registered with for a
   *  specific race — falling back to the ranking feed's team otherwise. A
   *  rider who has never appeared on a tracked start list still gets a row
   *  here if the UCI ranks them (races_count is then 0). */
  uci_rank: number | null;
  uci_points: number | null;
  team: string;
  uci_category: string;
  discipline: string | null;
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
  discipline: string | null;
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

/** One competition+category in the UCI archive (browse granularity, not
 *  per-finisher) — every past race the sweeps found, independent of whether
 *  it's tracked in races.yml. */
export interface UciArchiveRace {
  xco_race_id: string;
  category: string;
  comp_name: string;
  date: string;
  race_class: string;
  venue: string;
  country: string;
  discipline: string;
  finishers: number;
}

export function getUciArchive(): Promise<UciArchiveRace[]> {
  return getJson<UciArchiveRace[]>("/api/xco-races");
}
