# intraday-options

Intraday options intelligence and execution bot with:

- signal scoring and trade gating
- paper/live broker routing
- position lifecycle management
- daily risk controls
- API-based remote control for mobile operations

## Project overview

Core features:

- Bot scan engine in `app/main.py`
- Scheduler runner in `app/runner/bot_runner.py`
- Position monitoring and exits in `app/execution/live_monitor.py`
- Paper broker simulation in `app/broker/paper_broker.py`
- Control API in `app/server/api.py`
- Journaling and risk state in `logs/`

## How to run locally

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment:

```bash
copy .env.example .env
```

4. Run one scan:

```bash
python -m app.main
```

5. Run the bot loop scheduler:

```bash
python -m app.runner.bot_runner
```

## How to run the API server

Start FastAPI control server:

```bash
uvicorn app.server.api:app --host 0.0.0.0 --port 8000
```

Health check:

```text
GET http://localhost:8000/health
```

## How to start/stop bot from mobile

Use your deployed API URL and token:

- Start bot: `POST /start?api_token=TOKEN`
- Stop bot: `POST /stop?api_token=TOKEN`
- Check status: `GET /status?api_token=TOKEN`
- Check position: `GET /position?api_token=TOKEN`

Suggested mobile tools:

- Postman mobile for authenticated GET/POST calls
- iOS Shortcuts with URL + POST actions for one-tap start/stop

## Deployment guide

See full deployment instructions in `DEPLOYMENT_GUIDE.md`.

## Safety note

`ENABLE_TRADING=false` by default. Keep paper mode enabled while validating behavior.

## Project layout

- app/
  - broker/
  - market/
  - strategy/
  - risk/
  - indicators/
  - execution/
  - logs/
  - runner/
  - server/
  - utils/
  - data/
- tests/
