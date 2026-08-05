# Deployment runbook

```
www.veloanalyzer.com  →  Cloudflare Pages   (static frontend, free)
api.veloanalyzer.com  →  Fly.io Machine     (FastAPI + daily ingest, ~$3.50/mo)
                      →  Neon Postgres      (free tier)
```

Roughly **$3.50/mo plus the domain**. The database holds derived data only —
`races.yml` and the UCI/timing sites are the systems of record — so a lost
database is rebuilt by re-running the ingest.

---

The site has three pages, all built by Vite and all rendered from the API:
`index.html` (landing), `races.html` (race overview) and `app.html` (start-list
viewer). Nothing needs a database at build time.

---

## 1. Accounts and CLI

```bash
# Fly
curl -L https://fly.io/install.sh | sh
fly auth login

# Cloudflare (Wrangler)
npm install -g wrangler
wrangler login
```

Neon is browser-only — no CLI needed.

**Add a payment method to Fly before deploying** (<https://fly.io/trial>).
Trial accounts cap machines at 5 minutes of runtime, then stop them with
`exit_code=0, oom_killed=false, requested_stop=true` — indistinguishable from
idle autostop unless you read `fly logs`, which says plainly:

```
Trial machine stopping. To run for longer than 5m0s, add a credit card ...
```

This app cannot work on a trial account at all. The daily ingest runs via
APScheduler inside the API process, so a machine stopped after five minutes
never reaches 12:00 UTC and the data silently goes stale with no error
anywhere.

## 2. Neon

Already done. The connection string is in use; keep it in a password manager.

> **Rotate the current password.** It was pasted into a chat transcript.
> Neon console → your project → **Roles** → `neondb_owner` → **Reset password**,
> then update it in step 4 and in your local shell.

## 3. Fly app and volume

From the repo root (`fly.toml` is already committed, so **use `deploy`, never
`launch`** — `launch` re-runs the framework scanner that cannot detect this
project):

```bash
fly apps create veloanalyzer

# 1 GB is ample: the cache is ~10 MB today and grows slowly on a rolling
# 12-month window. Must be in the same region as primary_region in fly.toml.
fly volumes create mtb_cache --region ams --size 1
```

## 4. Secrets

**Quote the whole argument.** The URL contains `?` and `&`; unquoted in zsh the
`&` backgrounds the command mid-string and the `?` fails to glob
(`zsh: no matches found`).

```bash
fly secrets set 'DATABASE_URL=postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require&channel_binding=require'
```

Either Neon endpoint works. The pooled one (`-pooler` in the hostname) is
verified against psycopg 3's automatic prepared statements, which is the thing
that classically breaks under transaction pooling.

Confirm it took:

```bash
fly secrets list                  # shows names and digests, never values
```

Everything non-secret (`MTB_CACHE_DIR`, `INGEST_HOUR`, `CORS_ORIGINS`) is in
`fly.toml` under `[env]`.

## 5. First deploy

```bash
fly deploy
fly logs          # expect: "Scheduler started — daily ingest at 12:00 UTC"
fly status
```

`fly.toml` has `release_command = "alembic upgrade head"`, so migrations run in
a temporary machine first — a failed migration aborts the deploy rather than
leaving code and schema out of step.

Populate the database without waiting for 12:00 UTC. **Run it detached** — on a
cold volume the ingest downloads ~1,800 UCI event files with rate-limiting
sleeps and prints nothing for 10+ minutes, and `fly ssh console` drops the
session, killing the job (`exited without exit status or exit signal`):

```bash
fly ssh console -C "sh -c 'cd /app && setsid /usr/local/bin/docker-entrypoint.sh .venv/bin/python scripts/ingest.py > /data/ingest.log 2>&1 < /dev/null & echo started'"

# Check progress whenever — the log lives on the volume
fly ssh console -C "tail -n 30 /data/ingest.log"
```

Going through `docker-entrypoint.sh` drops to the `velo` user. Running the
ingest as root would leave root-owned files in `/data/.mtb_cache` that the
scheduled ingest — which runs as `velo` inside uvicorn — could not overwrite.

Only the first run is slow. Later runs reuse the volume, which is the whole
reason the machine stays always-on.

## 6. Cloudflare Pages project

```bash
cd frontend && VITE_API_BASE=https://api.veloanalyzer.com npm run build && cd ..
wrangler pages project create veloanalyzer --production-branch=main
wrangler pages deploy docs --project-name=veloanalyzer
```

Note the `*.pages.dev` hostname it prints — you need it for DNS.

## 7. DNS

**Move the domain's nameservers to Cloudflare first.** In the Cloudflare
dashboard: *Add a site* → `veloanalyzer.com` → Free plan. It shows two
nameservers; set those at your registrar, replacing what is there. Propagation
is usually under an hour.

This is worth doing even though Pages works with an external CNAME: only
Cloudflare's DNS can point the **apex** at Pages, because a bare domain cannot
legally hold a CNAME and Cloudflare fakes it with CNAME flattening.

Get the Fly addresses:

```bash
fly ips list          # note the v4 and v6 addresses
```

Then create these records (Cloudflare dashboard → **DNS** → *Add record*):

| Type | Name | Value | Proxy |
|---|---|---|---|
| `A` | `api` | Fly IPv4 from `fly ips list` | **DNS only** (grey cloud) |
| `AAAA` | `api` | Fly IPv6 from `fly ips list` | **DNS only** (grey cloud) |
| `CNAME` | `www` | `veloanalyzer.pages.dev` | Proxied (orange cloud) |
| `CNAME` | `@` | `veloanalyzer.pages.dev` | Proxied (orange cloud) |

**`api` must be grey-clouded.** Fly issues and renews its own Let's Encrypt
certificate, and proxying through Cloudflare puts a second TLS terminator in
front of it — which breaks certificate issuance until Cloudflare is set to Full
(strict). Leave it DNS-only; Fly handles TLS.

Attach the domains:

```bash
fly certs add api.veloanalyzer.com
fly certs show api.veloanalyzer.com     # wait for "Certificate Authority: Let's Encrypt"
```

For the frontend, Cloudflare dashboard → **Workers & Pages** → `veloanalyzer` →
**Custom domains** → add `www.veloanalyzer.com` and `veloanalyzer.com`. Pages
provisions its own certificate automatically.

Optionally redirect apex → www (Cloudflare → **Rules** → *Redirect Rules*):
hostname equals `veloanalyzer.com` → 301 to
`https://www.veloanalyzer.com${uri.path}`.

## 8. GitHub secrets

Repo → **Settings** → **Secrets and variables** → **Actions**:

| Secret | Where to get it |
|---|---|
| `FLY_API_TOKEN` | `fly tokens create deploy -x 999999h` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard sidebar, or `wrangler whoami` |
| `CLOUDFLARE_API_TOKEN` | My Profile → API Tokens → *Edit Cloudflare Workers* template |

Then delete the old workflow, which still deploys to GitHub Pages and would
fight the new one:

```bash
git rm .github/workflows/generate-reports.yml
```

## 9. Verify

```bash
curl -s https://api.veloanalyzer.com/health
curl -s https://api.veloanalyzer.com/api/races | jq length          # expect 50
curl -s https://api.veloanalyzer.com/api/meta                       # generated_at
curl -s https://api.veloanalyzer.com/api/stats                      # races/riders/entries
curl -sI https://www.veloanalyzer.com/ | head -1                    # expect 200
curl -sI https://www.veloanalyzer.com/races.html | head -1          # expect 200
curl -sI https://www.veloanalyzer.com/app.html | head -1            # expect 200

# Compression is doing its job — should be ~10x smaller than raw
curl -s -H 'Accept-Encoding: gzip' \
  https://api.veloanalyzer.com/api/races/as-uci-c1-2026-mj/results | wc -c
```

Then in a browser: load a race, open a rider card, select two riders for a
head-to-head, and confirm the network tab shows **no** `data.db` or `.wasm`
request.

The `smoke` job in `.github/workflows/deploy.yml` runs the first four of these
after every deploy to `main`.

## 10. Rollback

```bash
fly releases                 # list
fly deploy --image <previous-image-ref>

wrangler pages deployment list --project-name=veloanalyzer
# Or roll back from the Pages dashboard → Deployments → "Rollback to this"
```

Frontend and API roll back independently. Because the frontend is built against
a specific API shape, roll the **frontend** back first if a deploy breaks the
site — that restores service without touching data.

## 11. Ongoing

- **Ingest** runs daily at 12:00 UTC inside the API machine. Force one with
  `fly ssh console -C "/app/.venv/bin/python scripts/ingest.py"`.
- **Watch for** `! <race>: scraped 0 riders but N entries are already stored` in
  `fly logs`. That means a source URL or category filter has broken — exactly
  the failure that silently emptied eight races before it was caught.
- **Neon free tier gives 100 CU-hours/month.** Exceeding it suspends compute
  until the next billing month. Check the Neon dashboard occasionally.
- **Base image updates**: redeploy periodically (`fly deploy`) to pick up
  security patches in `python:3.12-slim`.
- **Backups** are deliberately minimal — the database is derived. To rebuild
  from scratch: `alembic upgrade head` then run the ingest.
