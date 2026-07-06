# Deployment Guide

This guide shows how to deploy the intraday options bot to Render and control it from mobile.

## 1. Push Project to GitHub

1. Open terminal in your project root:
   - `c:\Users\lohit\intraday-options`
2. Verify `.env` is ignored:
   - Ensure `.gitignore` includes `.env`
3. Initialize git if needed:
   - `git init`
4. Add and commit files:
   - `git add .`
   - `git commit -m "Prepare bot for Render deployment"`
5. Create a GitHub repo (via GitHub UI), then connect and push:
   - `git remote add origin https://github.com/<your-username>/<your-repo>.git`
   - `git branch -M main`
   - `git push -u origin main`

## 2. Deploy to Render.com

### Option A: Blueprint deployment (recommended)

1. Sign in to Render.
2. Click `New +` -> `Blueprint`.
3. Connect your GitHub account and select this repository.
4. Render will detect `render.yaml`.
5. Click `Apply` to create the web service.

### Option B: Manual Web Service

1. Sign in to Render.
2. Click `New +` -> `Web Service`.
3. Connect repository.
4. Use these settings:
   - Runtime: Docker
   - Branch: `main`
   - Root Directory: empty (project root)
5. Create the service.

## 3. Required Render Environment Variables

Set these in Render Dashboard -> your service -> `Environment`:

- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_PAPER=true`
- `ENABLE_TRADING=false`
- `SIMULATE_POSITIONS=true`
- `BOT_START_TIME=09:45`
- `BOT_END_TIME=12:00`
- `BOT_LOOP_SECONDS=60`
- `API_TOKEN=<strong-secret-token>`

After setting vars, trigger a redeploy.

## 4. Commands/Endpoints After Deploy

Assume your service URL is:
- `https://my-app-url`

### Health (no auth)

- `GET https://my-app-url/health`

### Authenticated endpoints (token required)

- `GET https://my-app-url/status?api_token=TOKEN`
- `GET https://my-app-url/position?api_token=TOKEN`
- `GET https://my-app-url/risk?api_token=TOKEN`
- `GET https://my-app-url/journal?api_token=TOKEN`
- `GET https://my-app-url/orders?api_token=TOKEN`
- `POST https://my-app-url/start?api_token=TOKEN`
- `POST https://my-app-url/stop?api_token=TOKEN`
- `POST https://my-app-url/scan-once?api_token=TOKEN`

You can also pass token as header:
- `X-API-Token: TOKEN`

## 5. Mobile Usage Instructions

1. Open in your phone browser:
   - `https://my-app-url/status?api_token=TOKEN`
2. Save as bookmark/home-screen shortcut for quick status checks.
3. For `POST /start` and `POST /stop`:
   - Use Postman mobile, or
   - Use iOS Shortcuts with `Get Contents of URL` action:
     - Method: POST
     - URL: `https://my-app-url/start?api_token=TOKEN` (or `/stop`)

## 6. Safety Warnings

- Keep `ENABLE_TRADING=false` by default.
- Paper trade for 30-60 days before considering live trading.
- Never commit `.env`.
- Use a strong `API_TOKEN`.
- Do not expose `API_TOKEN` publicly (screenshots, URLs, chats, repos).

## 7. Troubleshooting

### A) Check Render logs

1. Render Dashboard -> service -> `Logs`.
2. Look for startup/import errors, missing packages, or auth/env issues.

### B) App fails to start due to missing env vars

Symptoms:
- Service crashes or endpoints fail at runtime.

Fix:
1. Verify all required vars are set in Render.
2. Redeploy after changes.

### C) `/health` works but `/status` says unauthorized

Cause:
- Missing or wrong token.

Fix:
1. Ensure `API_TOKEN` is set in Render.
2. Pass `?api_token=TOKEN` in URL, or `X-API-Token` header.
3. Confirm exact token match (case-sensitive).

### D) Bot says idle outside strategy window

Cause:
- Current ET time is outside `BOT_START_TIME` to `BOT_END_TIME`.

Fix:
1. Verify window env vars.
2. Confirm ET timezone assumptions.
3. Use `POST /scan-once` for manual check.

### E) No trades because market is closed

Cause:
- `main.py` market-hours guard blocks trading when market is closed.

Fix:
1. This is expected behavior.
2. Test during market hours, or use logs/journal to verify control flow.

## 8. Start/Run Notes

- API service process is started by Render via Docker/uvicorn.
- Bot loop is controlled via API:
  - `POST /start` to begin scheduler.
  - `POST /stop` to stop scheduler.
- You can run one manual cycle any time with:
  - `POST /scan-once`.

## 9. Local Run (Optional)

If you want to run API locally first:

1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start server:
   - `uvicorn app.server.api:app --host 0.0.0.0 --port 8000`
3. Test:
   - `http://localhost:8000/health`
