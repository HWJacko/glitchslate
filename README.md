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
- LLM normalization, where messy workout text becomes structured minutes;
- rolling local state, where SQLite is enough;
- ambient rendering, where the desktop wallpaper becomes the feedback surface;
- scheduled local execution, where `launchd` is simpler than a hosted worker.

Glitchslate is therefore a deliberately compact proof of that pattern: personal telemetry as local infrastructure, not another cloud account.

## Features

- Telegram workout ingestion using bot polling.
- LLM workout parsing via OpenAI by default, with Gemini support as an optional parser provider.
- Optional Strava run ingestion.
- Local SQLite persistence with idempotent activity inserts.
- Rolling consistency score based on the last 5 local calendar days against a 30-day baseline.
- Procedural wallpaper rendering with a 30-bar rolling 5-day activity chart.
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
5. Calculate the rolling score.
6. Render a wallpaper into `assets/`.
7. Apply it as the macOS desktop wallpaper unless `--dry-run` or `--no-apply` is used.

Generated wallpapers and the local database are ignored by Git.

## Scoring Model

Glitchslate scores consistency, not absolute athletic performance.

```text
recent_minutes = total workout minutes over the last 5 local calendar days
baseline_daily_minutes = average daily workout minutes over the last 30 local calendar days
expected_recent_minutes = max(min_expected_5_day_minutes, baseline_daily_minutes * 5)
score = clamp(round((recent_minutes / expected_recent_minutes) * 100), 0, 100)
```

The chart shows 30 bars. Each bar is a trailing 5-day total ending on that date, so sparse workouts remain visible as they move through the rolling window.

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

The sentient status log currently uses OpenAI. It is skipped during `--dry-run`, generated during normal and `--no-apply` runs, and cached in SQLite by date, score, streak, and today's minutes.

## Strava Setup

Strava sync is optional. If any Strava credential is missing, the pipeline skips Strava and continues.

Required values:

```text
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REFRESH_TOKEN=
```

Only Strava activities with type `Run` are imported. Tokens refreshed from Strava are persisted in SQLite sync state.

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
scripts/             launchd install/uninstall helpers
launchd/             launchd documentation
assets/              Generated wallpapers, ignored except .gitkeep
logs/                launchd logs, ignored except .gitkeep
tests/               Unit tests
```

## Public GitHub Hygiene

The repository is intended to be safe to publish with the included ignore rules:

- `.env` is ignored.
- SQLite databases are ignored.
- Generated wallpaper PNGs are ignored.
- LaunchAgent logs are ignored.
- Python cache files are ignored.

Before publishing, run:

```bash
git status --short
rg -n "(api[_-]?key|token|secret|password|bearer|sk-[A-Za-z0-9])" -g '!*env*' -g '!assets/*.png' -g '!*.db' -g '!*.sqlite' -g '!*.sqlite3'
python3 -m unittest
```

The search will still show expected environment variable names and test placeholders; investigate anything that looks like a real credential.

## Testing

Run the full test suite:

```bash
python3 -m unittest
```

The tests cover config validation, database idempotency, rolling score behavior, Telegram parsing/sync logic, Strava sync logic, renderer smoke output, status bands, vignette selection, sentient-log fallback, and main pipeline dry-run behavior.

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
