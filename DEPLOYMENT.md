# Deployment runbook

```
www.veloanalyzer.com   →  Cloudflare Worker  (static site + read API on /api/*)
                       →  Neon Postgres      (free tier)
GitHub Actions cron    →  daily scrape into Neon
```

**$0/month beyond the domain.** Workers (100k requests/day), Neon's free tier
and Actions minutes for public repos are all free at this scale.

One Worker serves everything: the Vite build as static assets, and the API on
`/api/*`. That means one deployable, one deploy command, and same-origin
requests with no CORS preflight anywhere in production.

Cloudflare Pages is deliberately **not** used. Its asset-upload API failed
persistently from both the CLI and the dashboard, and Workers static assets
deploy through a different API path with fewer moving parts.

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

## 3. Build and deploy

```bash
cd frontend && npm ci && npm run build && cd ..    # writes docs/
cd worker   && npm ci
npx wrangler deploy                                 # uploads docs/ + the API
npx wrangler secret put DATABASE_URL                # paste the Neon string
```

`wrangler.toml` points `[assets] directory` at `../docs`, so the site and the
API ship together. Deploy again after any frontend change.

**Quote the connection string** if you ever pass it inline. It contains `?` and
`&`; unquoted in zsh the `&` backgrounds the command mid-string and the `?`
fails to glob (`zsh: no matches found`). `wrangler secret put` prompts for it
instead, which sidesteps this.

Verify on the workers.dev URL before any DNS exists — `wrangler deploy` prints it:

```bash
curl -s https://veloanalyzer.<your-subdomain>.workers.dev/api/stats
```

## 4. DNS

**Move the domain's nameservers to Cloudflare.** Dashboard → *Add a site* →
`veloanalyzer.com` → Free plan. It shows two nameservers; set those at your
registrar. Propagation is usually under an hour.

Then re-run `npx wrangler deploy`. `wrangler.toml` declares
`www.veloanalyzer.com` and `veloanalyzer.com` as **custom domains**, so
Cloudflare creates the DNS records and issues the certificates itself — there
is nothing to add by hand.

(A plain Worker *route* would additionally need a proxied placeholder DNS
record for the hostname before it would fire. Custom domains avoid that.)

## 5. GitHub secrets

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

## 6. First ingest

The schema is already migrated and populated. To re-run on demand:
**Actions** → **Ingest** → *Run workflow*. It prints row counts when it
finishes.

A cold cache takes ~10 minutes; warm runs are about a minute. The job has a
45-minute timeout so a slow UCI day doesn't fail it.

## 7. Verify

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

## 8. Local development

```bash
# Whole site + API exactly as production serves it
cd worker && npx wrangler dev           # http://localhost:8787

# Or, for frontend hot-reload:
cd frontend && npm run dev              # Vite on :5173, proxies /api → :8787
```

`worker/.dev.vars` holds `DATABASE_URL` locally and is gitignored. `wrangler
dev` serves `docs/`, so run the frontend build first to see changes there.

## 9. Rollback

```bash
cd worker && npx wrangler rollback     # previous version, site and API together
npx wrangler deployments list
```

Site and API are one deployable now, so a rollback restores both at once. It
never touches data — Neon is unaffected.

## 10. Ongoing

- **Ingest** runs daily at 12:00 UTC via `.github/workflows/ingest.yml`.
- **Watch for** `! <race>: scraped 0 riders but N entries are already stored` in
  the ingest log. A source URL or category filter has broken — exactly the
  failure that silently emptied eight races before it was caught.
- **Neon free tier** gives 100 CU-hours/month; exceeding it suspends compute
  until the next billing month.
- **Workers free tier** is 100k requests/day. API responses carry
  `Cache-Control: max-age=60` and static assets are edge-cached, so repeat
  traffic mostly never reaches the script.
- **Rebuild from scratch**: `alembic upgrade head`, then run the Ingest
  workflow.
