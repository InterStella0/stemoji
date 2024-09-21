BEGIN;
CREATE TABLE IF NOT EXISTS discord_user(
    id INTEGER PRIMARY KEY,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS emoji(
    id INTEGER PRIMARY KEY,
    fullname VARCHAR(40) NOT NULL,
    hash TEXT NOT NULL,
    added_by INTEGER NOT NULL REFERENCES discord_user(id)
);

CREATE TABLE IF NOT EXISTS emoji_used(
     emoji_id INTEGER REFERENCES emoji(id) NOT NULL,
     user_id INTEGER REFERENCES discord_user(id) NOT NULL,
     amount INTEGER DEFAULT 0,
     first_used DATETIME DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user UNIQUE (emoji_id, user_id)
);

CREATE TABLE IF NOT EXISTS emoji_reacted(
     emoji_id INTEGER REFERENCES emoji(id) NOT NULL,
     user_id INTEGER REFERENCES discord_user(id) NOT NULL,
     message_id INTEGER NOT NULL,
     made_at DATETIME DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user_message UNIQUE (emoji_id, user_id, message_id)
);

CREATE TABLE IF NOT EXISTS emoji_favourite(
     emoji_id INTEGER REFERENCES emoji(id) NOT NULL,
     user_id INTEGER REFERENCES discord_user(id) NOT NULL,
     made_at DATETIME DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user_fav UNIQUE (emoji_id, user_id)
);

CREATE TABLE IF NOT EXISTS discord_normal_emojis(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    json_data TEXT NOT NULL,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
COMMIT;
