CREATE TABLE IF NOT EXISTS sessions (
    channel_id   BIGINT PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary      TEXT NOT NULL DEFAULT '',
    last_token_usage INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    uid          BIGINT PRIMARY KEY,
    channel_id   BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    role         TEXT NOT NULL,
    name         TEXT,
    content      TEXT NOT NULL DEFAULT '',
    tool_calls   JSONB,
    tool_call_id TEXT
);

CREATE TABLE IF NOT EXISTS users (
    uid          BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    state_str    INTEGER NOT NULL DEFAULT 0,
    state_dex    INTEGER NOT NULL DEFAULT 0,
    state_con    INTEGER NOT NULL DEFAULT 0,
    state_int    INTEGER NOT NULL DEFAULT 0,
    state_wis    INTEGER NOT NULL DEFAULT 0,
    state_cha    INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (uid, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id_id
    ON messages(channel_id, uid DESC);
