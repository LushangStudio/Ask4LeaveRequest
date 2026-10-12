-- Migration 004: UIS login source and single-use OAuth state hashes.
-- Back up before applying; indexes are run once.

CREATE TABLE IF NOT EXISTS uis_login_sessions (
	token_hash VARCHAR(64) NOT NULL,
	user_type VARCHAR(80) NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(token_hash) REFERENCES demo_sessions (token_hash) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS oauth_states (
	state_hash VARCHAR(64) NOT NULL,
	expires DATETIME NOT NULL,
	PRIMARY KEY (state_hash)
);

CREATE INDEX ix_oauth_states_expires ON oauth_states (expires);
