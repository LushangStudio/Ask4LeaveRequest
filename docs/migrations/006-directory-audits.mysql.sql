-- Migration 006: audit administrator roster updates.
-- Apply with migration account before deploying class management.

CREATE TABLE IF NOT EXISTS directory_audits (
	id VARCHAR(36) NOT NULL,
	actor_id VARCHAR(40) NOT NULL,
	actor_name VARCHAR(80) NOT NULL,
	before_digest VARCHAR(64) NOT NULL,
	after_digest VARCHAR(64) NOT NULL,
	counts JSON NOT NULL,
	at VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES people (id)
);
