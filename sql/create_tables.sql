CREATE TABLE IF NOT EXISTS sessions (
    channel_id   BIGINT PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary      TEXT NOT NULL DEFAULT '',
    last_token_usage INTEGER NOT NULL DEFAULT 0,
    -- 'game' = 一般遊戲 session;'chargen' = 私訊創角的臨時 session
    kind            TEXT NOT NULL DEFAULT 'game',
    owner_user_id   BIGINT,   -- chargen 專用:這個創角流程屬於哪位玩家
    game_channel_id BIGINT    -- chargen 專用:對應的遊戲頻道(角色最終寫入此頻道)
);

CREATE INDEX IF NOT EXISTS idx_sessions_chargen
    ON sessions(owner_user_id, game_channel_id) WHERE kind = 'chargen';

CREATE TABLE IF NOT EXISTS messages (
    uid          BIGINT PRIMARY KEY,
    channel_id   BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    message_id   BIGINT,  -- 玩家訊息對應的 Discord Message ID(其他角色為 NULL)
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

    PRIMARY KEY (uid, channel_id)
);

-- 晉級名單(每個頻道的 session 各自擁有一份,於 /start 時由 JSON 種入)
CREATE TABLE IF NOT EXISTS roster (
    channel_id     BIGINT NOT NULL REFERENCES sessions(channel_id) ON DELETE CASCADE,
    idx            INTEGER NOT NULL,
    name           TEXT NOT NULL,
    suggested_date DATE NOT NULL,
    revealed       BOOLEAN NOT NULL DEFAULT FALSE,
    revealed_at    TIMESTAMPTZ,

    PRIMARY KEY (channel_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_id_id
    ON messages(channel_id, uid DESC);

CREATE INDEX IF NOT EXISTS idx_roster_channel
    ON roster(channel_id, suggested_date);
