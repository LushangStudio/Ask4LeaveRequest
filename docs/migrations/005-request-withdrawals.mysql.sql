-- Migration 005: retain student withdrawals and counselor revocations.
-- Run as migration account before deploying this version; preserves old records.

CREATE TABLE IF NOT EXISTS request_withdrawals (
	request_id VARCHAR(36) NOT NULL,
	actor_id VARCHAR(40) NOT NULL,
	actor_name VARCHAR(80) NOT NULL,
	actor_role VARCHAR(20) NOT NULL,
	prior_status VARCHAR(16) NOT NULL,
	reason TEXT NOT NULL,
	at VARCHAR(40) NOT NULL,
	PRIMARY KEY (request_id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id),
	FOREIGN KEY(actor_id) REFERENCES people (id)
);
