CREATE TABLE IF NOT EXISTS discord_user(
    id BIGINT PRIMARY KEY,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS emoji(
    id BIGINT PRIMARY KEY,
    fullname VARCHAR(40) NOT NULL,
    hash TEXT NOT NULL,
    added_by BIGINT NOT NULL REFERENCES discord_user(id)
);

CREATE TABLE IF NOT EXISTS emoji_used(
     emoji_id BIGINT REFERENCES emoji(id) NOT NULL,
     user_id BIGINT REFERENCES discord_user(id) NOT NULL,
     amount INT DEFAULT 0,
     first_used TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user UNIQUE (emoji_id, user_id)
);

CREATE TABLE IF NOT EXISTS emoji_reacted(
     emoji_id BIGINT REFERENCES emoji(id) NOT NULL,
     user_id BIGINT REFERENCES discord_user(id) NOT NULL,
     message_id INT NOT NULL,
     made_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user_message UNIQUE (emoji_id, user_id, message_id)
);

CREATE TABLE IF NOT EXISTS emoji_favourite(
     emoji_id BIGINT REFERENCES emoji(id) NOT NULL,
     user_id BIGINT REFERENCES discord_user(id) NOT NULL,
     made_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
     CONSTRAINT emoji_user_fav UNIQUE (emoji_id, user_id)
);

CREATE TABLE IF NOT EXISTS discord_normal_emojis(
    id SERIAL PRIMARY KEY,
    json_data JSONB NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
