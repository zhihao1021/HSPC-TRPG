CREATE TABLE IF NOT EXISTS sessions (
    channel_id         BIGINT PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary            TEXT NOT NULL DEFAULT '',
    token_usage        INTEGER NOT NULL DEFAULT 0,
    kind               TEXT NOT NULL DEFAULT 'game',
    chargen_owner_id   BIGINT,
    chargen_channel_id BIGINT
);

CREATE INDEX IF NOT EXISTS idx_sessions_chargen
    ON sessions(chargen_owner_id, chargen_channel_id)
    WHERE kind = 'chargen';

CREATE TABLE IF NOT EXISTS messages (
    uid               BIGINT PRIMARY KEY,
    channel_id        BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    message_id        BIGINT,
    role              TEXT NOT NULL,
    name              TEXT,
    content           TEXT,
    reasoning_content TEXT,
    tool_calls        JSONB,
    tool_call_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id_uid
    ON messages(channel_id, uid);

CREATE TABLE IF NOT EXISTS users (
    uid          BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    level        INTEGER NOT NULL DEFAULT 1,
    hp           INTEGER NOT NULL DEFAULT 10,
    max_hp       INTEGER NOT NULL DEFAULT 10,
    state_str    INTEGER NOT NULL DEFAULT 10,
    state_dex    INTEGER NOT NULL DEFAULT 10,
    state_con    INTEGER NOT NULL DEFAULT 10,
    state_int    INTEGER NOT NULL DEFAULT 10,
    state_wis    INTEGER NOT NULL DEFAULT 10,
    state_cha    INTEGER NOT NULL DEFAULT 10,
    skills       JSONB NOT NULL DEFAULT '[]'::jsonb,
    inventory    JSONB NOT NULL DEFAULT '[]'::jsonb,

    PRIMARY KEY  (uid, channel_id)
);

CREATE TABLE IF NOT EXISTS roster (
    channel_id     BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    suggested      TIMESTAMPTZ NOT NULL,
    revealed       BOOLEAN NOT NULL DEFAULT FALSE,
    revealed_at    TIMESTAMPTZ,

    PRIMARY KEY (channel_id, name)
);
