-- Migration 002: additive tables only. Back up first; run once with a migration account.
-- Application startup backfills legacy request counselor scope; never backfills signatures.
-- Preserve these tables on rollback. Index statements are intentionally run once.

CREATE TABLE IF NOT EXISTS counselor_signatures (
	counselor_id VARCHAR(40) NOT NULL,
	version VARCHAR(36) NOT NULL,
	content MEDIUMBLOB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	updated VARCHAR(40) NOT NULL,
	PRIMARY KEY (counselor_id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);

CREATE TABLE IF NOT EXISTS directory_members (
	person_id VARCHAR(40) NOT NULL,
	PRIMARY KEY (person_id),
	FOREIGN KEY(person_id) REFERENCES people (id)
);

CREATE TABLE IF NOT EXISTS approval_previews (
	id VARCHAR(36) NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	counselor_id VARCHAR(40) NOT NULL,
	signature_version VARCHAR(36) NOT NULL,
	signature_content MEDIUMBLOB NOT NULL,
	watermark VARCHAR(160) NOT NULL,
	opinion TEXT NOT NULL,
	at VARCHAR(40) NOT NULL,
	expires DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);

CREATE INDEX ix_approval_previews_expires ON approval_previews (expires);

CREATE INDEX ix_approval_previews_request_id ON approval_previews (request_id);

CREATE TABLE IF NOT EXISTS request_counselors (
	request_id VARCHAR(36) NOT NULL,
	counselor_id VARCHAR(40) NOT NULL,
	PRIMARY KEY (request_id, counselor_id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);

CREATE INDEX ix_request_counselors_counselor_id ON request_counselors (counselor_id);

CREATE TABLE IF NOT EXISTS approval_signatures (
	request_id VARCHAR(36) NOT NULL,
	signature_version VARCHAR(36) NOT NULL,
	content MEDIUMBLOB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	watermark VARCHAR(160) NOT NULL,
	PRIMARY KEY (request_id),
	FOREIGN KEY(request_id) REFERENCES approval_records (request_id)
);
