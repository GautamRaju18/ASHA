# Deploying ASHA Sahayak

Architecture: **frontend on Vercel**, **backend on Render**. Vercel serves the
React UI and rewrites every `/api/*` call to the Render backend, so the browser
sees one origin (no CORS headaches) and the FastAPI server runs persistently
(SQLite history works, no serverless timeouts).

```
  Browser ──▶ Vercel (static UI)  ──/api/*──▶  Render (FastAPI + LLM + SQLite)
```

---

## 0. One-time: push this repo to GitHub
Both hosts deploy from a Git repo.

```bash
# from D:\ASHA\ASHA
git add .
git commit -m "Deploy config: Render backend + Vercel frontend"
# create an empty repo on github.com first, then:
git remote add origin https://github.com/<you>/asha-sahayak.git
git branch -M main
git push -u origin main
```

`backend/.env` is gitignored and will **not** be pushed — keys go in the
dashboards (steps 1 & 2).

---

## 1. Backend → Render  (do this first; you need its URL for step 2)

1. https://dashboard.render.com → **New ▸ Blueprint** → connect this GitHub repo.
   Render reads [`render.yaml`](render.yaml) and creates the `asha-sahayak-api`
   web service automatically.
2. When prompted, fill the three secret env vars (they are `sync: false`, so
   they are never stored in the repo):
   - `GEMINI_API_KEY`
   - `OPENROUTER_API_KEY`
   - `GOOGLE_MAPS_API_KEY`
   (Copy the values from your local `backend/.env`.)
3. Click **Apply** / **Deploy**. First build takes a few minutes.
4. When live, note the URL, e.g. `https://asha-sahayak-api.onrender.com`.
   Verify it: open `…/api/health` — you should see `{"status":"ok",...}`.

> Free tier note: the instance **sleeps after ~15 min idle** and takes ~30–50s to
> wake on the next request. SQLite history persists while warm but resets on
> redeploy/sleep. For durable history later, add a Render paid disk or Postgres.

---

## 2. Frontend → Vercel

1. Edit [`frontend/vercel.json`](frontend/vercel.json): replace the
   `destination` host with **your actual Render URL** from step 1.4 (only change
   the host; keep `/api/:path*`). Commit & push.
2. https://vercel.com/new → import this GitHub repo.
   - **Root Directory:** `frontend`
   - Framework preset: **Vite** (auto-detected)
   - Build command `npm run build`, output `dist` (auto-detected)
3. **Deploy.** Vercel gives you a URL like `https://asha-sahayak.vercel.app`.

That's it — open the Vercel URL, sign in, and run a triage. Voice typing needs
**Google Chrome** (Brave blocks the Web Speech service).

---

## Updating later
Push to `main` → both Render and Vercel auto-redeploy. To change a key, edit it
in the Render dashboard (not the repo).
