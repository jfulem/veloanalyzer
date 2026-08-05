# Deployment runbook

```
www.veloanalyzer.com        →  Cloudflare Pages    (static frontend)
www.veloanalyzer.com/api/*  →  Cloudflare Worker   (read API)
                            →  Neon Postgres       (free tier)
GitHub Actions cron         →  daily scrape into Neon
```

**$0/month beyond the domain.** Cloudflare Pages, Workers (100k requests/day),
Neon's free tier and Actions minutes for public repos are all free at this
scale.

The API is served from `/api/*` on the same domain as the site, so the frontend
makes relative requests and there is no CORS preflight anywhere in production.

## Why the scrape runs in Actions

`mtb_analyzer/` uses `requests`, BeautifulSoup and a C-extension fuzzy matcher,
and a cold run makes ~1,800 UCI requests over several minutes with a persistent
9.5 MB file cache. None of that fits a Worker. Actions has the cron, the
minutes and the cache primitive, and ran this exact job for the project's whole
history.

The consequence: **on-demand analysis of a user-submitted URL is not possible
in this architecture.** `main.py` still does it locally from the CLI.

## Why backups barely matter

Postgres holds derived data only. `races.yml` and the UCI/timing sites are the
systems of record — a lost database is rebuilt by re-running the ingest, which
is why Neon's free tier (6-hour PITR) is adequate here.

---

## 1. Accounts and CLI

```bash
npm install -g wrangler
wrangler login
```

Neon is browser-only. No Fly account is needed.

## 2. Neon

Already provisioned. Keep the connection string in a password manager.

> **Rotate the password** if it has ever been pasted somewhere shared: Neon
> console → **Roles** → `neondb_owner` → **Reset password**, then update it in
> steps 3 and 6.

Either endpoint works. The pooled one (`-pooler` in the hostname) is verified
against both psycopg 3 (used by the ingest) and `@neondatabase/serverless`
(used by the Worker).

## 3. Worker

```bash
cd worker
npm ci
npx wrangler deploy
npx wrangler secret put DATABASE_URL     # paste the Neon connection string
```

`wrangler.toml` declares routes on `veloanalyzer.com/api/*` and
`www.veloanalyzer.com/api/*`. Those only bind once the domain is on Cloudflare
DNS (step 5) — deploying earlier is fine, the routes attach when the zone
appears.

**Quote the connection string** if you ever pass it inline. It contains `?` and
`&`; unquoted in zsh the `&` backgrounds the command mid-string and the `?`
fails to glob (`zsh: no matches found`). `wrangler secret put` prompts for it
instead, which sidesteps this.

## 4. Pages project

```bash
cd frontend && npm ci && npm run build && cd ..
wrangler pages project create veloanalyzer --production-branch=main
wrangler pages deploy docs --project-name=veloanalyzer
```

Note the `*.pages.dev` hostname it prints — needed for DNS.

## 5. DNS

**Move the domain's nameservers to Cloudflare first.** Dashboard → *Add a site*
→ `veloanalyzer.com` → Free plan. It shows two nameservers; set those at your
registrar. Propagation is usually under an hour.

This is required, not optional: only Cloudflare's DNS can point the **apex** at
Pages (a bare domain cannot hold a CNAME; Cloudflare fakes it with CNAME
flattening), and Worker routes only work on a zone Cloudflare controls.

| Type | Name | Value | Proxy |
|---|---|---|---|
| `CNAME` | `www` | `veloanalyzer.pages.dev` | Proxied (orange cloud) |
| `CNAME` | `@` | `veloanalyzer.pages.dev` | Proxied (orange cloud) |

Both **must** be proxied — Worker routes only fire on proxied traffic. There is
no `api` record and no Fly IP to point at; the Worker attaches to a path on the
existing hostname.

Then Cloudflare dashboard → **Workers & Pages** → `veloanalyzer` → **Custom
domains** → add `www.veloanalyzer.com` and `veloanalyzer.com`. Certificates are
automatic.

Optionally redirect apex → www (**Rules** → *Redirect Rules*): hostname equals
`veloanalyzer.com` → 301 to `https://www.veloanalyzer.com${uri.path}`.

## 6. GitHub secrets

Repo → **Settings** → **Secrets and variables** → **Actions**:

| Secret | Where to get it |
|---|---|
| `CLOUDFLARE_API_TOKEN` | My Profile → API Tokens → *Edit Cloudflare Workers* template |
| `CLOUDFLARE_ACCOUNT_ID` | Dashboard sidebar, or `wrangler whoami` |
| `DATABASE_URL` | The Neon connection string — used by the ingest cron |

Then remove the old GitHub Pages workflow, which would fight the new one:

```bash
git rm .github/workflows/generate-reports.yml
```

## 7. First ingest

The schema is already migrated and populated. To re-run on demand:
**Actions** → **Ingest** → *Run workflow*. It prints row counts when it
finishes.

A cold cache takes ~10 minutes; warm runs are about a minute. The job has a
45-minute timeout so a slow UCI day doesn't fail it.

## 8. Verify

```bash
curl -s https://www.veloanalyzer.com/api/stats     # {"races":50,"riders":553,"entries":1080}
curl -s https://www.veloanalyzer.com/api/races | jq length
curl -sI https://www.veloanalyzer.com/            | head -1
curl -sI https://www.veloanalyzer.com/races.html  | head -1
curl -sI https://www.veloanalyzer.com/app.html    | head -1
```

Then in a browser: load a race, open a rider card, select two riders for a
head-to-head, and confirm the network tab shows no `data.db` or `.wasm`
request. The `smoke` job in `deploy.yml` runs the first two after every deploy.

## 9. Local development

```bash
cd worker  && npx wrangler dev          # API on :8787, reads worker/.dev.vars
cd frontend && npm run dev              # Vite on :5173, proxies /api → :8787
```

`worker/.dev.vars` holds `DATABASE_URL` locally and is gitignored. The Vite
proxy mirrors production, so dev is same-origin too.

## 10. Rollback

```bash
cd worker && npx wrangler rollback              # previous Worker version
wrangler pages deployment list --project-name=veloanalyzer
# or roll back from the Pages dashboard → Deployments
```

Frontend and API roll back independently. Roll the **frontend** back first if a
deploy breaks the site — it restores service without touching data.

## 11. Ongoing

- **Ingest** runs daily at 12:00 UTC via `.github/workflows/ingest.yml`.
- **Watch for** `! <race>: scraped 0 riders but N entries are already stored` in
  the ingest log. A source URL or category filter has broken — exactly the
  failure that silently emptied eight races before it was caught.
- **Neon free tier** gives 100 CU-hours/month; exceeding it suspends compute
  until the next billing month.
- **Workers free tier** is 100k requests/day. Responses carry
  `Cache-Control: max-age=60`, so Cloudflare's edge absorbs repeat traffic.
- **Rebuild from scratch**: `alembic upgrade head`, then run the Ingest
  workflow.
