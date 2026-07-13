# Procedural Telemetry Visual Engine

## Goal

Replace the over-engineered theme/asset monument direction with a simpler procedural telemetry wallpaper.

The wallpaper should be a high-resolution dark-mode dashboard canvas that visualizes recent physical consistency as a stylized rolling activity chart. The output should feel like a clean retro-terminal telemetry system rather than a decorative generative scene.

## Decisions

- Keep the rolling consistency score.
- Remove the theme asset renderer and placeholder PNG theme system.
- Keep the renderer procedural.
- Bars should represent rolling 5-day activity totals, not raw daily values.
- Keep the 30-day view, but each of the 30 bars is a trailing 5-day sum ending on that date.
- This avoids sparse charts when the user does not work out every day.
- Keep empty/faint bars so inactivity is visible.
- Combine Telegram and Strava minutes into the same totals.
- Keep compact labels, not labels on every bar if crowded.
- Keep the terminal metadata block.
- Keep secrets in `.env`; use `config.yaml` only for non-secret visual/scoring preferences.

## Visual Direction

Generate a 3840x2160 dark-mode dashboard canvas.

Core visual elements:

- Solid dark background.
- Subtle horizontal grid across the lower half of the screen.
- 30 centered vertical columns.
- Each column is a rounded capsule bar.
- Filled bars use a cyan-to-violet gradient.
- Empty/low bars use a faint slate color.
- Activity volume labels should be clean and minimal.
- Terminal metadata block in the top-left or bottom-right.

Example terminal block:

```text
// GLITCHSLATE TELEMETRY CORE v1.0 //
-------------------------------------------
CURRENT SCORE : [  78 / 100  ]
ACTIVE STREAK : [   5 DAYS   ]
SYSTEM STATUS : [  STABLE    ]
```

## Rolling Bar Semantics

Show 30 bars, oldest on the left and today on the right.

For each bar date `D`:

```text
bar_value = total workout minutes from D-4 through D, inclusive
```

So the chart is a 30-day sequence of trailing 5-day totals.

This means:

- A single workout remains visible in several adjacent bars as it moves through the 5-day window.
- The chart naturally slopes down after inactivity.
- The user does not need a value every day.
- Today's bar matches the recent 5-day total used by the current score.

## Score Model

Keep the rolling score globally.

```text
recent_minutes = total workout minutes over the last 5 local calendar days
baseline_daily_minutes = average daily workout minutes over the last 30 local calendar days
expected_recent_minutes = max(min_expected_5_day_minutes, baseline_daily_minutes * 5)
score = clamp(round((recent_minutes / expected_recent_minutes) * 100), 0, 100)
```

Recommended defaults:

```yaml
scoring:
  recent_window_days: 5
  baseline_window_days: 30
  min_expected_5_day_minutes: 60
```

## Bar Scaling

Recommended scaling:

```text
bar_max = max(expected_recent_minutes, max(bar_values))
bar_height = bar_value / bar_max
```

This keeps the current target visible while still allowing unusually strong periods to fill the chart.

Recommended layout:

- Chart width: centered, around 75-85% of canvas width.
- Chart height: about 800px.
- Column count: 30.
- Column width and gap should be derived from available chart width.
- Minimum nonzero bar height: 24px, so small efforts remain visible.

## Labels

Avoid clutter.

Recommended label behavior:

- Label today's bar.
- Label local peaks.
- Optionally label every 5th bar.
- Use compact text like `20m`, `1h10`, `2h`.
- Do not label every single nonzero bar if it becomes crowded.

## System Status Labels

Recommended score bands:

```text
score >= 80: STABLE
score >= 50: DRIFTING
score >= 20: AT RISK
score < 20:  CRITICAL
```

## Proposed `config.yaml`

```yaml
visual:
  target_resolution: 3840x2160
  bg_color: "#0b0f19"
  grid_color: "#1e293b"
  active_gradient: ["#06b6d4", "#8b5cf6"]
  empty_color: "#1e293b"
  text_color: "#f8fafc"
  muted_text_color: "#94a3b8"
  alert_color: "#ef4444"
  keep_archive_images: false
  archive_retention_hours: 48

scoring:
  recent_window_days: 5
  baseline_window_days: 30
  min_expected_5_day_minutes: 60
```

## Implementation Task List

### 1. Revert Overbuilt Theme Work

- [ ] Remove `themes/` placeholder asset system.
- [ ] Remove theme asset renderer code from `visual_engine.py`.
- [ ] Remove renderer/theme selection from config and CLI.
- [ ] Remove monument/module/debris/crack diagnostics.
- [ ] Remove theme-renderer tests.
- [ ] Keep OpenAI parser support, `--no-apply`, and Telegram replay/dry-run fixes.

### 2. Keep And Simplify Config

- [ ] Keep `config.yaml`, but reduce it to visual colors, archive settings, and scoring windows.
- [ ] Keep `PyYAML` if config loading already uses it.
- [ ] Validate target resolution, colors, archive settings, and scoring windows.
- [ ] Remove theme-specific config fields.

### 3. Rolling Score Support

- [ ] Keep the global rolling 5-day vs 30-day scoring model.
- [ ] Add reusable DB helpers for daily minutes and rolling-window minutes.
- [ ] Expose the 30 chart points as trailing 5-day totals.
- [ ] Keep score diagnostics: `recent_minutes`, `baseline_daily_minutes`, `expected_recent_minutes`.

### 4. Telemetry Renderer

- [ ] Render a dark 3840x2160 canvas.
- [ ] Draw a subtle lower-half horizontal grid.
- [ ] Draw 30 centered rounded capsule bars.
- [ ] Compute each bar as the trailing 5-day total ending on that date.
- [ ] Fill nonzero bars with a cyan-to-violet gradient.
- [ ] Draw empty bars in faint slate.
- [ ] Scale bars against `max(expected_recent_minutes, max(bar_values))`.
- [ ] Add compact labels for today, peaks, and/or every 5th bar.
- [ ] Add terminal metadata block with score, streak, and status.
- [ ] Keep deterministic rendering for the same date and DB state.

### 5. Diagnostics

- [ ] Print chart diagnostics: `bar_count`, `latest_5_day_minutes`, `max_5_day_minutes`, `bar_scale_minutes`, `status`.
- [ ] Remove obsolete theme diagnostics.

### 6. Tests

- [ ] Update scoring tests for rolling model.
- [ ] Add tests for rolling 5-day chart points.
- [ ] Add tests for sparse activity data.
- [ ] Add renderer smoke test for output file creation.
- [ ] Add status-band tests.
- [ ] Run `python3 -m unittest`.

## Open Questions

None currently blocking implementation.
