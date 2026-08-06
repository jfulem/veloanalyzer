// Read API. Replaces the FastAPI app that previously ran on Fly; the SQL is a
// straight port, so response shapes are unchanged and the frontend did not move.
//
// Two casts are load-bearing against the Postgres HTTP driver:
//   ::text on DATE   — otherwise dates deserialise as JS Date and serialise as
//                      "2026-06-06T00:00:00.000Z" instead of "2026-06-06"
//   ::int  on count  — otherwise bigint comes back as a string ("42")

import { neon } from "@neondatabase/serverless";

interface Env {
  DATABASE_URL: string;
  /** Optional. Salts the submitter hash so a stored value can't be brute-forced
   *  back to an IP — the IPv4 space is small enough to enumerate unsalted. */
  SUBMIT_SALT?: string;
  /** Optional. When set, enables GET /api/race-requests for the maintainer.
   *  Without it that route stays 404 rather than exposing submissions. */
  ADMIN_TOKEN?: string;
}

// Caps on visitor-submitted text. Generous for real use, small enough that the
// endpoint can't be used to push bulk data into the database.
const MAX_URL = 500;
const MAX_TEXT = 300;
const MAX_NOTE = 1000;
// Per submitter, per hour.
const SUBMIT_LIMIT = 5;

type Sql = ReturnType<typeof neon>;

const CORS = {
  // Production is same-origin (the Worker is routed on /api/* of the Pages
  // domain), so this only matters for `vite dev` against `wrangler dev`.
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(data: unknown, status = 200, maxAge = 60): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      // The data changes once a day; a short edge TTL absorbs bursts without
      // making a fresh ingest invisible for long.
      "Cache-Control": `public, max-age=${maxAge}`,
      ...CORS,
    },
  });
}

const notFound = (detail: string) => json({ detail }, 404, 0);

async function raceExists(sql: Sql, slug: string): Promise<boolean> {
  const rows = (await sql`SELECT 1 FROM races WHERE slug = ${slug}`) as unknown[];
  return rows.length > 0;
}

async function route(url: URL, sql: Sql): Promise<Response | null> {
  const path = url.pathname.replace(/\/+$/, "");
  const parts = path.split("/").filter(Boolean); // ["api", "races", slug, ...]

  if (path === "/health") return json({ status: "ok" }, 200, 0);
  if (parts[0] !== "api") return null;

  // ── /api/meta ───────────────────────────────────────────────────────────
  if (parts.length === 2 && parts[1] === "meta") {
    const rows = (await sql`SELECT key, value FROM meta`) as { key: string; value: string }[];
    return json(Object.fromEntries(rows.map((r) => [r.key, r.value])));
  }

  // ── /api/stats ──────────────────────────────────────────────────────────
  // `riders` counts distinct people, not start-list entries.
  if (parts.length === 2 && parts[1] === "stats") {
    const rows = (await sql`
      SELECT (SELECT count(*) FROM races)::int        AS races,
             (SELECT count(*) FROM riders)::int       AS riders,
             (SELECT count(*) FROM race_entries)::int AS entries
    `) as unknown[];
    return json(rows[0]);
  }

  if (parts[1] === "races") {
    // ── /api/races ────────────────────────────────────────────────────────
    if (parts.length === 2) {
      return json(await sql`
        SELECT id, slug, name, date::text AS date, uci_category, category
        FROM races
        ORDER BY date ASC NULLS LAST, name
      `);
    }

    // ── /api/races/stats ──────────────────────────────────────────────────
    // Must be tested before the slug branch below, or "stats" reads as a slug.
    if (parts.length === 3 && parts[2] === "stats") {
      return json(await sql`
        SELECT r.id, r.slug, r.name, r.date::text AS date, r.uci_category, r.category,
               count(e.id)::int             AS total,
               count(e.uci_rank)::int       AS ranked,
               min(e.uci_rank)::int         AS best,
               round(avg(e.uci_rank))::int  AS avg
        FROM races r
        LEFT JOIN race_entries e ON e.race_id = r.id
        GROUP BY r.id
        ORDER BY r.date ASC NULLS LAST, r.name
      `);
    }

    const slug = decodeURIComponent(parts[2]!);

    // ── /api/races/{slug} ─────────────────────────────────────────────────
    if (parts.length === 3) {
      const rows = (await sql`
        SELECT id, slug, name, date::text AS date, uci_category, category
        FROM races WHERE slug = ${slug}
      `) as unknown[];
      if (rows.length === 0) return notFound(`No race with slug '${slug}'`);
      return json(rows[0]);
    }

    // ── /api/races/{slug}/entries ─────────────────────────────────────────
    // Flattens riders + race_entries into the flat row the table expects. The
    // ORDER BY is kept verbatim from the original client-side query: official
    // result first once a race has run, then UCI rank, then the estimated
    // points fallbacks for unranked riders.
    if (parts.length === 4 && parts[3] === "entries") {
      if (!(await raceExists(sql, slug))) return notFound(`No race with slug '${slug}'`);
      return json(await sql`
        SELECT ri.id                     AS id,
               e.race_id                 AS race_id,
               ri.first_name, ri.last_name,
               e.corrected_name,
               ri.country, ri.birth_year,
               e.start_nr,
               COALESCE(ri.uci_id, '')   AS uci_id,
               e.uci_rank, e.uci_points, e.cp_xco_points, e.computed_points,
               e.result_rank, e.result_time,
               e.team, e.category, e.match_confidence,
               ri.xcodata_slug, e.race_name
        FROM race_entries e
        JOIN riders ri ON ri.id = e.rider_id
        JOIN races  r  ON r.id  = e.race_id
        WHERE r.slug = ${slug}
        ORDER BY (e.result_rank IS NULL), e.result_rank,
                 (e.uci_rank IS NULL), e.uci_rank,
                 COALESCE(e.computed_points, 0) DESC,
                 COALESCE(e.cp_xco_points, 0) DESC,
                 ri.last_name
      `);
    }

    // ── /api/races/{slug}/results ─────────────────────────────────────────
    // Every history row for the whole field in one request: the head-to-head
    // panel and the form-trend arrows both need it at once, and it lets the
    // rider card open from memory.
    if (parts.length === 4 && parts[3] === "results") {
      if (!(await raceExists(sql, slug))) return notFound(`No race with slug '${slug}'`);
      return json(await sql`
        SELECT rr.id, rr.rider_id, rr.xco_race_id, rr.race_name,
               rr.date_raw AS date, rr.location, rr.rank, rr.time, rr.cat, rr.uci_pts, rr.race_class
        FROM rider_results rr
        WHERE rr.rider_id IN (
          SELECT e.rider_id FROM race_entries e
          JOIN races r ON r.id = e.race_id
          WHERE r.slug = ${slug}
        )
        ORDER BY rr.date DESC NULLS LAST
      `);
    }
  }

  if (parts[1] === "riders" && parts.length >= 3) {
    const riderId = Number(parts[2]);
    if (!Number.isInteger(riderId)) return notFound(`Invalid rider id '${parts[2]}'`);

    // ── /api/riders/{id} ──────────────────────────────────────────────────
    if (parts.length === 3) {
      const rows = (await sql`
        SELECT id, uci_id, first_name, last_name, normalized_name,
               birth_year, country, xcodata_slug
        FROM riders WHERE id = ${riderId}
      `) as unknown[];
      if (rows.length === 0) return notFound(`No rider with id ${riderId}`);
      return json(rows[0]);
    }

    // ── /api/riders/{id}/results ──────────────────────────────────────────
    if (parts.length === 4 && parts[3] === "results") {
      return json(await sql`
        SELECT id, rider_id, xco_race_id, race_name,
               date_raw AS date, location, rank, time, cat, uci_pts, race_class
        FROM rider_results
        WHERE rider_id = ${riderId}
        ORDER BY date DESC NULLS LAST
      `);
    }
  }

  return null;
}

/** Stable, non-reversible identifier for a submitter, used only to rate-limit.
 *  Salted because unsalted IPv4 hashes can be enumerated in seconds. */
async function submitterHash(request: Request, env: Env): Promise<string> {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  const data = new TextEncoder().encode(`${env.SUBMIT_SALT ?? "veloanalyzer"}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function clean(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

/** POST /api/race-requests — visitors suggesting a start list to track. */
async function handleRaceRequest(request: Request, env: Env, sql: Sql): Promise<Response> {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return json({ detail: "Expected a JSON body" }, 400, 0);
  }

  // Honeypot: a field hidden from humans by CSS. Bots fill everything in, so a
  // value here means a bot. Accept it with a 200 so it has nothing to retry
  // against, and discard it.
  if (clean(body["website"], 50)) return json({ ok: true }, 200, 0);

  const url = clean(body["url"], MAX_URL);
  if (!url) return json({ detail: "A start list URL is required" }, 400, 0);

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return json({ detail: "That does not look like a valid URL" }, 400, 0);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return json({ detail: "Only http and https links are accepted" }, 400, 0);
  }

  const email = clean(body["email"], MAX_TEXT);
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return json({ detail: "That email address does not look valid" }, 400, 0);
  }

  const hash = await submitterHash(request, env);
  const recent = (await sql`
    SELECT count(*)::int AS n FROM race_requests
    WHERE submitter_hash = ${hash} AND created_at > now() - interval '1 hour'
  `) as { n: number }[];
  if ((recent[0]?.n ?? 0) >= SUBMIT_LIMIT) {
    return json({ detail: "Too many submissions — please try again later" }, 429, 0);
  }

  await sql`
    INSERT INTO race_requests (url, race_name, category, email, note, submitter_hash, status, created_at)
    VALUES (${url}, ${clean(body["race_name"], MAX_TEXT)}, ${clean(body["category"], MAX_TEXT)},
            ${email}, ${clean(body["note"], MAX_NOTE)}, ${hash}, 'new', now())
  `;
  return json({ ok: true }, 201, 0);
}

/** GET /api/race-requests — maintainer only, and only when ADMIN_TOKEN is set. */
async function handleListRequests(request: Request, env: Env, sql: Sql): Promise<Response> {
  const token = env.ADMIN_TOKEN;
  // Without a configured token the route does not exist at all, rather than
  // existing and rejecting — nothing to probe for.
  if (!token) return notFound("No route for /api/race-requests");
  if (request.headers.get("X-Admin-Token") !== token) {
    return json({ detail: "Not found" }, 404, 0);
  }
  return json(await sql`
    SELECT id, url, race_name, category, email, note, status,
           to_char(created_at, 'YYYY-MM-DD HH24:MI') AS created_at
    FROM race_requests ORDER BY created_at DESC LIMIT 200
  `, 200, 0);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    if (request.method === "POST") {
      if (path === "/api/race-requests") {
        try {
          return await handleRaceRequest(request, env, neon(env.DATABASE_URL));
        } catch (err) {
          console.error("race-request failed", err instanceof Error ? err.message : String(err));
          return json({ detail: "Internal error" }, 500, 0);
        }
      }
      return json({ detail: "Method not allowed" }, 405, 0);
    }
    if (request.method !== "GET") {
      return json({ detail: "Method not allowed" }, 405, 0);
    }

    try {
      if (path === "/api/race-requests") {
        return await handleListRequests(request, env, neon(env.DATABASE_URL));
      }
      const resp = await route(url, neon(env.DATABASE_URL));
      if (resp) return resp;
      // Static files are served by the assets binding before the script runs,
      // so anything reaching here is genuinely missing. Only /api/* is routed
      // to the script deliberately (run_worker_first in wrangler.toml); a
      // non-API path here means a mistyped URL, which deserves plain text
      // rather than a JSON error body.
      if (url.pathname.startsWith("/api/")) return notFound(`No route for ${url.pathname}`);
      return new Response("Not found", { status: 404, headers: { "Content-Type": "text/plain" } });
    } catch (err) {
      // Surface the message but never the connection string.
      const message = err instanceof Error ? err.message : String(err);
      console.error("request failed", url.pathname, message);
      return json({ detail: "Internal error" }, 500, 0);
    }
  },
} satisfies ExportedHandler<Env>;
