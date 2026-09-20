# PDF Weave

A beautiful, responsive **PDF merger** built with Flask — dark-mode UI, drag & drop,
per-file **page ranges**, and full authentication powered by **Supabase**
(Backend-as-a-Service): email/password sign-up **and** "Continue with Google".

Production-ready: Waitress / gunicorn server, CSRF + security headers, rate-limited
auth, health checks, structured error pages, a one-click **Render Blueprint**
(`render.yaml`), and a drop-in **Cloudflare Tunnel** deployment.

## Run it (development)

```bash
python -m venv .venv                 # only once
.venv\Scripts\activate               # Windows (or `source .venv/bin/activate` on macOS/Linux)
pip install -r requirements.txt      # only once
python app.py                        # -> http://127.0.0.1:5001
```

## Connecting Supabase

```bash
copy .env.example .env               # Windows  (macOS/Linux: cp .env.example .env)
```

1. **Create a project** at https://supabase.com/dashboard
2. **Copy the API keys**: Project Settings → API → copy the **Project URL**
   and the **anon public key**
3. Paste both values into `.env` (they're git-ignored — never commit them)
4. Restart `python app.py`

> Set a real `SECRET_KEY` too (`python -c "import secrets; print(secrets.token_hex(32))"`).

### Email/password sign-up

Works out of the box. Supabase confirms email addresses by default — if you want
instant logins during development, turn it off in
**Authentication → Providers → Email → uncheck "Confirm email"**.

### "Continue with Google"

1. In Supabase: **Authentication → URL Configuration** →
   - set **Site URL** to `http://127.0.0.1:5001`
   - add **Redirect URLs**: `http://127.0.0.1:5001/**`
2. Enable **Authentication → Providers → Google**
3. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an **OAuth client ID** (type: Web application) and set the
   **Authorized redirect URI** to
   `https://<YOUR-PROJECT-REF>.supabase.co/auth/v1/callback`
4. Paste the Google **Client ID** and **Client Secret** into the Supabase provider,
   then **Save**

The Google button always shows the account chooser (`prompt=select_account`).

## Features

- Responsive dark-mode UI with a sticky, glassy navbar: brand, **Home / About** links,
  and a user avatar dropdown (name, email, log out)
- **Welcome message** — a personalized "Welcome back, NAME!" toast + hero greeting
  right after signing in (email, Google, or new account)
- Drag & drop + click-to-browse PDF upload (max 10 files, 50 MB each request)
- Reorder / remove / clear all files
- **Per-file page ranges** — merge only the pages you want from each PDF
  (e.g. `2-5`, `1,3,8`, `10-12`; empty = all pages)
- Merge engine powered by **pypdf**; after merging you land on a **Thank-you page**
  with the merged PDF previewed inline and a **Download button** (files are kept
  briefly, then deleted automatically)
- **About page** (`/about`) — what PDF Weave is, how it works, and the tech behind it
- Auth via **Supabase**: email/password + Google OAuth
- Session tokens live in the Flask session cookie (auto-refreshed near expiry)
- **Production hardening**:
  - CSRF protection on every state-changing request (Flask-WTF)
  - Rate-limited login/signup endpoints (flask-limiter)
  - Security headers: CSP, `X-Frame-Options: DENY`, `nosniff`, HSTS, Permissions-Policy
  - `ProxyFix` for Cloudflare / nginx headers
  - Secure-cookie-only over HTTPS, 30-day sessions
  - Enforced `SECRET_KEY` + `https:// SITE_URL` when `ENV=production`
  - `/api/health` health check, friendly 404/413/500 + CSRF error pages
  - Rotating file logging (`LOG_FILE`)
- `GET /api/me` — JSON describing the current session

## Run it (production)

### Production environment file

A ready-to-use `.env.production` was generated for you (git-ignored — never commit
it). It contains a **real, random `SECRET_KEY`** plus your `ENV=production` settings.
Tell the app to load it with the `ENV_FILE` variable:

```bash
ENV_FILE=.env.production python app.py        # Windows: $env:ENV_FILE='.env.production'
```

The only value you must change before deploying is `SITE_URL` — replace
`https://your-domain.com` with your real URL (e.g. `https://pdfweave.onrender.com`
on Render).

### Deploy on Render (free)

The repo ships with `render.yaml`, a Render **Blueprint** that pre-configures the
free web service (Python 3, `pip install -r requirements.txt`, gunicorn). Steps:

1. Sign up at https://render.com with **Sign in with GitHub**.
2. **New → Blueprint** → connect the `sayamuddinshams/pdf-merger` repo.
3. In the service's **Environment** tab, set the four manual vars:
   `SITE_URL=https://pdfweave.onrender.com`, a fresh `SECRET_KEY`
   (`python -c "import secrets; print(secrets.token_hex(32))"`), and your
   `SUPABASE_URL` / `SUPABASE_ANON_KEY` from the local `.env`.
4. **Manual Deploy → Deploy latest commit**, then add
   `https://pdfweave.onrender.com/**` to
   **Supabase → Authentication → URL Configuration → Redirect URLs**.

Free tier notes: the instance spins down after 15 min idle (first visit after a
sleep takes ~1 min; an UptimeRobot ping every 5 min keeps it warm), and the disk is
ephemeral — merged files are deleted after their 30-minute TTL anyway.

### Option A — Windows host (Waitress)

```bash
python serve.py          # Waitress on 0.0.0.0:5001 (respects $env:PORT)
```

### Option B — Linux / Docker (gunicorn)

```bash
docker build -t pdfweave .
docker run -d -p 8000:8000 \
  --env-file .env \
  -e ENV=production \
  -e SITE_URL=https://pdfweave.onrender.com \
  pdfweave
```

### Both options

- `ENV=production`, a **strong `SECRET_KEY`**, and an **https `SITE_URL`** are required.
- Put a real `SUPABASE_URL` / `SUPABASE_ANON_KEY` in the environment.

## Deploy on Cloudflare (free tunnel)

Cloudflare can't run Python, so Cloudflare sits **in front of** your Flask app via
a free `cloudflared` tunnel — your domain (HTTPS, edge caching, DDoS protection)
points at the app, wherever it runs.

1. Sign up at https://dash.cloudflare.com and add your domain (free plan).
2. Install `cloudflared` from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
3. Create a tunnel:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create pdfweave      # -> gives you a tunnel UUID
   ```
4. Copy `deploy/cloudflared-config.yml.example` to `cloudflared/config.yml`,
   fill in the tunnel UUID, your Cloudflare API token, and the app address.
5. Add the DNS records (CNAME `your-domain.com` → `<UUID>.cfargotunnel.com`, proxied).
6. Add a Cloudflare API token with **Zone.DNS:Edit** permission for that zone.
7. Run the app and the tunnel:
   ```bash
   python serve.py                          # app on 0.0.0.0:5001
   cloudflared tunnel --config cloudflared/config.yml run pdfweave
   ```
8. In Supabase (**Authentication → URL Configuration → Redirect URLs**)
   add `https://your-domain.com/**` so Google sign-in works on the real domain.
9. Set `SITE_URL=https://your-domain.com`, `ENV=production` and the production
   `SECRET_KEY`, then restart.

Login, Google OAuth, page-range merging and the download all work through the tunnel.

## Supabase CLI

The [Supabase CLI](https://supabase.com/docs/guides/cli) is installed — check it with
`supabase --version`. Use it to link the project to your cloud project (good for
local dev DBs and migrations later):

```bash
supabase login                       # one-time browser auth
supabase link --project-ref YOUR-PROJECT-REF
```

## API

| Endpoint | Method | Auth | Description |
| --- | --- | --- | --- |
| `/api/health` | GET | no | Health check for load balancers / tunnel |
| `/api/me` | GET | no | `{authenticated, user}` for the frontend |
| `/api/merge` | POST | **yes** | Multipart `files[]` + parallel `pages[]` → `{ok, token, thankyouUrl, downloadUrl}` |
| `/thankyou/<token>` | GET | **yes** | Thank-you page: merged PDF preview + download button |
| `/preview/<token>` | GET | **yes** | The merged PDF streamed inline (for the iframe) |
| `/download/<token>` | GET | **yes** | Downloads the merged PDF as `merged.pdf` |
| `/login`, `/signup` | GET/POST | — | Email/password auth |
| `/login/google`, `/auth/callback` | GET | — | Google OAuth (PKCE) |

`/api/merge` succeeds with `{ "ok": true, "token": ..., "thankyouUrl": ..., "downloadUrl": ... }`,
or fails with `{ "ok": false, "error": "..." }` (400/401/413/500).
Merged files live in `uploads/merged/` for 30 minutes, then are cleaned up.

## Project layout

```
pdf-merger/
├── app.py              # config, hardening, routes, /api/merge (pypdf engine)
├── auth.py             # Supabase auth, rate limits, Google OAuth
├── serve.py            # Waitress production server (Windows)
├── wsgi.py             # gunicorn entry point (Linux / Docker)
├── Dockerfile          # production image (gunicorn)
├── LICENSE             # MIT
├── requirements.txt
├── .env.example        # dev template
├── .env.production.example
├── .env.production     # your real production env (git-ignored, generated)
├── deploy/             # cloudflared tunnel config example
└── templates/          # base.html, index.html, about.html, login.html,
                        # signup.html, thankyou.html, error.html
```