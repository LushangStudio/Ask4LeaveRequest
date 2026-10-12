-- Migration 003: scoped test-session source and secret digest; no raw credentials.
-- Back up first. Keep the table when rolling back application code.

CREATE TABLE IF NOT EXISTS test_login_sessions (
	token_hash VARCHAR(64) NOT NULL,
	secret_digest VARCHAR(64) NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(token_hash) REFERENCES demo_sessions (token_hash) ON DELETE CASCADE
);
