# Glitchslate

Glitchslate is a local-first workout telemetry wallpaper for macOS. It ingests lightweight workout check-ins from Telegram, optional run data from Strava, scores recent consistency against your own rolling baseline, and renders a dark retro-terminal wallpaper that changes as your physical output changes.

It is intentionally small: a SQLite database, a procedural Pillow renderer, a few sync scripts, and an optional hourly `launchd` runner.

## Why This Exists

Most fitness tools ask for attention. Glitchslate gives attention back.

The goal is not another dashboard, habit app, or social feed. It is an ambient accountability surface: your desktop quietly reflects whether you have been maintaining physical output over the last few days. If you train, the system looks stable. If you drift, the wallpaper degrades into warning states. The feedback loop is visible without opening an app.

### Infrasieve Link Contextualization

Glitchslate was synthesized as a companion project from trend-discovery and duplicate-gating signals in the autonomous pipeline behind [Infrasieve](https://infrasieve.dev).

The upstream signal was not simply "fitness app". The pipeline surfaced a narrower demand pattern: developers and technical operators were building personal automation around chat-native logging, LLM-assisted parsing, local dashboards, and low-friction behavioral nudges. Duplicate-gating filtered out crowded categories like generic habit trackers, hosted wellness SaaS, and ordinary workout journals. What remained was a gap for a local, inspectable companion tool that turns informal activity messages into an always-on system-status artifact.

Technically, that trend created demand for this specific shape of project because the useful primitive is not a full product backend. It is a small bridge between:

- conversational capture, where Telegram is faster than a form;
- LLM normalization, where messy workout text becomes structured workout points;
- rolling local state, where SQLite is enough;
- ambient rendering, where the desktop wallpaper becomes the feedback surface;
- scheduled local execution, where `launchd` is simpler than a hosted worker.

Glitchslate is therefore a deliberately compact proof of that pattern: personal telemetry as local infrastructure, not another cloud account.

## Features

- Telegram workout ingestion using bot polling.
- Optional Hetzner Telegram archive fallback for laptop sleep/backlog gaps.
- LLM workout parsing via OpenAI by default, with Gemini support as an optional parser provider.
- Optional Strava run ingestion.
- Local SQLite persistence with idempotent activity inserts.
- Daily consistency score based on today's workout points against a 30-day baseline.
- Procedural wallpaper rendering with a 30-bar daily activity chart.
- System status labels: `STABLE`, `DRIFTING`, `AT RISK`, `CRITICAL`.
- Optional OpenAI-generated sentient status log rendered on the wallpaper.
- Pseudo-systemd telemetry box based on today's workout volume and inactivity gap.
- Score-dependent edge vignette.
- macOS wallpaper application through `osascript`.
- Optional hourly macOS LaunchAgent.

## How It Works

The main pipeline is `main.py`:

1. Load `.env` and `config.yaml`.
2. Poll Telegram for new messages.
3. Parse workout-like messages into structured activity records.
4. Optionally sync Strava runs.
5. Calculate today's score against the daily baseline target.
6. Render a wallpaper into `assets/`.
7. Apply it as the macOS desktop wallpaper unless `--dry-run` or `--no-apply` is used.

Generated wallpapers and the local database are ignored by Git.

## Scoring Model

Glitchslate scores consistency, not absolute athletic performance.

```text
strength_points = reps * weight_kg * movement_multiplier
running_points = moving_minutes * running_value
today_points = total workout points for the current local calendar day
baseline_daily_points = average daily workout points over the last 30 local calendar days
expected_daily_points = max(min_expected_5_day_points / 5, baseline_daily_points)
score = clamp(round((today_points / expected_daily_points) * 100), 0, 100)
```

For Strava runs, `running_value` is derived from Strava fields already stored in `raw_payload`: `moving_time`, `distance`, `average_speed`, `total_elevation_gain`, and `sport_type`. Pace and elevation adjust a base running value, while minutes remain stored as context.

The chart shows 30 daily bars. Each bar is an actual local calendar day, stacked by run points and other workout points. The latest populated day is labeled, and the best day in the visible window is highlighted.

## Requirements

- macOS for automatic wallpaper application and `launchd` scheduling.
- Python 3.11+ recommended.
- A Telegram bot token and your Telegram user id for chat ingestion.
- An OpenAI API key for the default workout parser and sentient log.
- Optional Strava API credentials for run sync.
- Optional Gemini API key if you choose `WORKOUT_PARSER_PROVIDER=gemini`.

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Fill in the values you need:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
TELEGRAM_DIRECT_SYNC=true
TELEGRAM_ARCHIVE_ENABLED=false
HETZNER_TELEGRAM_SSH=
HETZNER_TELEGRAM_REMOTE_DIR=glitchslate-telegram-inbox
WORKOUT_PARSER_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
GEMINI_API_KEY=
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=
LOCAL_TIMEZONE=Europe/London
GLITCHSLATE_DB_PATH=glitchslate.db
```

Secrets belong in `.env`. Non-secret rendering and scoring preferences live in `config.yaml`.

## Running Manually

Dry-run without persisting score state or applying the wallpaper:

```bash
python3 main.py --dry-run
```

Render and sync data, but do not apply the wallpaper:

```bash
python3 main.py --no-apply
```

Normal run:

```bash
python3 main.py
```

Use a custom resolution:

```bash
python3 main.py --resolution 1920x1080
```

Use a custom database or output directory:

```bash
python3 main.py --db /path/to/glitchslate.db --assets-dir /path/to/assets
```

Replay Telegram from a known update id:

```bash
python3 main.py --telegram-replay-from 123456789
```


## Local Mock Dataset Output

Build a deterministic local-only mock dataset and wallpaper without reading `.env`, calling external APIs, or applying the wallpaper:

```bash
python3 scripts/build_mock_output.py --width 1920 --height 1080
```

By default this writes to:

```text
test_output/mock_dataset/
```

The output root contains:

```text
mock_glitchslate.db      SQLite database with Telegram-like and Strava-like mock activities
assets/                  Rendered mock wallpapers
summary.json             Score, source totals, daily chart points, diagnostics, and rendered paths
```

The mock output is ignored by Git. It is intended for screenshots, renderer checks, documentation, and testing the full visual pipeline with realistic data while keeping real personal activity data local and private.

Use a different root or date if needed:

```bash
python3 scripts/build_mock_output.py --output-root /tmp/glitchslate-demo --date 2026-07-13
```

## Telegram Setup

1. Create a bot with BotFather.
2. Put the token in `TELEGRAM_BOT_TOKEN`.
3. Send your bot a message.
4. Find your Telegram user id using Telegram API tooling or a user-id helper bot.
5. Put that id in `TELEGRAM_ALLOWED_USER_ID`.

Only messages from the allowed user id are processed. Non-workout messages are ignored by the parser.

Example messages:

```text
10kg dumbbells
30 arm curls
30 shoulder press
50 situps
```

```text
45 min easy run
```

## Hetzner Telegram Archive

Telegram bot updates expire if nothing receives them. To preserve backlog while the laptop sleeps, run the lightweight collector on Hetzner. It stores authorized text updates as dated JSONL files and removes files older than 28 days.

On Hetzner, copy this repo or at least the Python files, create `.env`, and run:

```bash
python3 scripts/telegram_archive_collector.py --inbox-dir glitchslate-telegram-inbox --retention-days 28
```

For systemd, use a small service like:

```ini
[Unit]
Description=Glitchslate Telegram archive collector
After=network-online.target

[Service]
WorkingDirectory=/home/glitchslate/glitchslate
ExecStart=/usr/bin/python3 scripts/telegram_archive_collector.py --inbox-dir /home/glitchslate/glitchslate-telegram-inbox --retention-days 28
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

On the laptop, enable the fallback in `config.yaml` or `.env`:

```text
TELEGRAM_ARCHIVE_ENABLED=true
HETZNER_TELEGRAM_SSH=glitchslate@your-hetzner-host
HETZNER_TELEGRAM_REMOTE_DIR=/home/glitchslate/glitchslate-telegram-inbox
```

The laptop SSH-fetches recent archive files, including today when direct Telegram sync is disabled, and relies on Telegram `message_id` idempotency to avoid duplicate inserts. `telegram_archive.blank_lookback_days` defaults to 28 and is capped at the collector retention window.

Avoid running two competing Telegram pollers. Once the Hetzner collector is active, set this on the laptop:

```text
TELEGRAM_DIRECT_SYNC=false
```

## OpenAI and Gemini Parsing

OpenAI is the default parser provider:

```text
WORKOUT_PARSER_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Gemini can be used instead:

```text
WORKOUT_PARSER_PROVIDER=gemini
GEMINI_API_KEY=...
```

The sentient status log currently uses OpenAI. It is skipped during `--dry-run`, generated during normal and `--no-apply` runs, and cached in SQLite by date, score, streak, and today's points.

## Strava Setup

Strava sync is optional. If any Strava credential is missing, the pipeline skips Strava and continues.

Required values:

```text
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=
```

Authorize the app with `activity:read` so `/athlete/activities` can be read. Use `activity:read_all` instead if you want activities whose visibility is set to Only You. Only Strava activities with type `Run` are imported. Tokens refreshed from Strava are persisted in SQLite sync state.

The token shown on the Strava API settings page is usually only scoped to `read`. To create a refresh token with activity scope:

```bash
python3 scripts/strava_oauth.py authorize-url --scope activity:read
```

Open the printed URL, authorize the app, then copy the `code` query parameter from the redirected URL and exchange it:

```bash
python3 scripts/strava_oauth.py exchange-code YOUR_AUTHORIZATION_CODE --update-env
```

Use `--scope activity:read_all` instead if the app should import activities whose visibility is Only You.

## Hourly Local Sync With launchd

Install the hourly LaunchAgent:

```bash
./scripts/install_launchd.sh
```

The generated agent runs once immediately, then every hour:

```text
StartInterval = 3600 seconds
RunAtLoad = true
command = python3 main.py
```

Logs are written to:

```text
logs/launchd.out.log
logs/launchd.err.log
```

If you use a virtual environment or specific Python executable:

```bash
PYTHON_BIN=/path/to/python3 ./scripts/install_launchd.sh
```

Uninstall:

```bash
./scripts/uninstall_launchd.sh
```

This is polling, not push. If the Mac is asleep or offline, Telegram updates are picked up on the next hourly run after wake.

## Repository Layout

```text
main.py              Pipeline entrypoint
telegram_sync.py     Telegram polling and workout parsing
strava_sync.py       Optional Strava run sync
db.py                SQLite persistence and scoring helpers
visual_engine.py     Procedural wallpaper renderer
sentient_log.py      OpenAI status log generation and fallback text
os_sync.py           macOS wallpaper application
schema.sql           SQLite schema
config.py            Config loading and validation
config.yaml          Non-secret defaults
scripts/             launchd helpers and local mock output generator
launchd/             launchd documentation
assets/              Generated wallpapers, ignored except .gitkeep
logs/                launchd logs, ignored except .gitkeep
test_output/         local mock/demo output, ignored except .gitkeep
tests/               Unit tests
```

## Public GitHub Hygiene

The repository is intended to be safe to publish with the included ignore rules:

- `.env` is ignored.
- SQLite databases are ignored.
- Generated wallpaper PNGs are ignored.
- LaunchAgent logs are ignored.
- Local mock output is ignored.
- Python cache files are ignored.

Before publishing, run:

```bash
git status --short
rg -n "(api[_-]?key|token|secret|password|bearer|sk-[A-Za-z0-9])" -g '!*env*' -g '!assets/*.png' -g '!*.db' -g '!*.sqlite' -g '!*.sqlite3'
python3 -m unittest
python3 scripts/build_mock_output.py --width 640 --height 360
```

The search will still show expected environment variable names and test placeholders; investigate anything that looks like a real credential.

## Testing

Run the full test suite:

```bash
python3 -m unittest
```

The tests cover config validation, database idempotency, daily score behavior, Telegram parsing/sync logic, Strava sync logic, renderer smoke output, status bands, vignette selection, sentient-log fallback, and main pipeline dry-run behavior.

## Troubleshooting

### Telegram sync is skipped

Check `.env` contains both:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
```

### OpenAI parsing fails

Check:

```text
OPENAI_API_KEY=
WORKOUT_PARSER_PROVIDER=openai
```

Also confirm dependencies are installed with `python3 -m pip install -r requirements.txt`.

### The wallpaper image changes but the desktop does not

Run with `--no-apply` first and inspect the printed wallpaper command. On macOS, normal runs use `osascript` through `System Events` to set all desktop pictures.

### launchd does not appear to run

Check logs:

```bash
tail -n 100 logs/launchd.out.log
tail -n 100 logs/launchd.err.log
```

Reinstall the agent:

```bash
./scripts/uninstall_launchd.sh
./scripts/install_launchd.sh
```

## Notes

Glitchslate is local-first, but it can call third-party APIs depending on enabled integrations: Telegram, OpenAI, Gemini, and Strava. Activity data, parser payloads, sync offsets, and generated status text are stored in the local SQLite database.
