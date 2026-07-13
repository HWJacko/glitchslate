CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('telegram', 'strava')),
    external_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    local_date TEXT NOT NULL,
    activity_type TEXT,
    duration_minutes INTEGER NOT NULL,
    intensity TEXT,
    notes TEXT,
    raw_payload TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS daily_state (
    date TEXT PRIMARY KEY,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    streak_days INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
