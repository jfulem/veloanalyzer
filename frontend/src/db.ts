import initSqlJs, { Database, SqlJsStatic } from "sql.js";

let SQL: SqlJsStatic;
let db: Database;

export async function initDb(wasmUrl: string, dbUrl: string): Promise<void> {
  SQL = await initSqlJs({ locateFile: () => wasmUrl });
  const resp = await fetch(dbUrl, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`Failed to fetch ${dbUrl}: ${resp.status}`);
  const buf = await resp.arrayBuffer();
  db = new SQL.Database(new Uint8Array(buf));
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
  team: string;
  category: string;
  match_confidence: number;
  xcodata_slug: string;
  race_name: string;
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
}

function rowsOf<T>(sql: string, params: (string | number | null)[] = []): T[] {
  const [stmt] = db.exec(sql, params);
  if (!stmt) return [];
  return stmt.values.map((row) => {
    const obj: Record<string, unknown> = {};
    stmt.columns.forEach((col, i) => { obj[col] = row[i] ?? null; });
    return obj as T;
  });
}

export function getMeta(): Record<string, string> {
  const rows = rowsOf<{ key: string; value: string }>("SELECT key, value FROM meta");
  return Object.fromEntries(rows.map((r) => [r.key, r.value]));
}

export function getRaces(): Race[] {
  return rowsOf<Race>("SELECT * FROM races ORDER BY date ASC, name");
}

export function getRiders(raceId: number): Rider[] {
  return rowsOf<Rider>(
    `SELECT * FROM riders WHERE race_id = ?
     ORDER BY uci_rank IS NULL,
              uci_rank,
              COALESCE(cp_xco_points, 0) DESC,
              last_name`,
    [raceId],
  );
}

export function getResults(riderIds: number[]): RaceResult[] {
  if (riderIds.length === 0) return [];
  const placeholders = riderIds.map(() => "?").join(",");
  return rowsOf<RaceResult>(
    `SELECT * FROM race_results WHERE rider_id IN (${placeholders}) ORDER BY date DESC`,
    riderIds,
  );
}
