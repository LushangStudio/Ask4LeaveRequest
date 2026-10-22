-- New empty MySQL 8 database. Persisted class directory and audit.

CREATE TABLE class_directory (
	id INTEGER NOT NULL AUTO_INCREMENT,
	directory JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	updated VARCHAR(40) NOT NULL,
	PRIMARY KEY (id)
);


CREATE TABLE oauth_states (
	state_hash VARCHAR(64) NOT NULL,
	expires DATETIME NOT NULL,
	PRIMARY KEY (state_hash)
);

CREATE INDEX ix_oauth_states_expires ON oauth_states (expires);


CREATE TABLE people (
	id VARCHAR(40) NOT NULL,
	name VARCHAR(80) NOT NULL,
	`role` VARCHAR(20) NOT NULL,
	counselor VARCHAR(40),
	profile JSON NOT NULL,
	PRIMARY KEY (id)
);


CREATE TABLE counselor_signatures (
	counselor_id VARCHAR(40) NOT NULL,
	version VARCHAR(36) NOT NULL,
	content MEDIUMBLOB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	updated VARCHAR(40) NOT NULL,
	PRIMARY KEY (counselor_id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);


CREATE TABLE demo_sessions (
	token_hash VARCHAR(64) NOT NULL,
	person_id VARCHAR(40) NOT NULL,
	expires DATETIME NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(person_id) REFERENCES people (id)
);


CREATE TABLE directory_audits (
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


CREATE TABLE directory_members (
	person_id VARCHAR(40) NOT NULL,
	PRIMARY KEY (person_id),
	FOREIGN KEY(person_id) REFERENCES people (id)
);


CREATE TABLE leave_requests (
	id VARCHAR(36) NOT NULL,
	student_id VARCHAR(40) NOT NULL,
	counselor_id VARCHAR(40) NOT NULL,
	idempotency_key VARCHAR(80) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	snapshot JSON NOT NULL,
	reason TEXT NOT NULL,
	starts VARCHAR(10) NOT NULL,
	ends VARCHAR(10) NOT NULL,
	layout VARCHAR(16) NOT NULL,
	status VARCHAR(16) NOT NULL,
	file_status VARCHAR(16) NOT NULL,
	generation_error TEXT,
	created VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (student_id, idempotency_key),
	FOREIGN KEY(student_id) REFERENCES people (id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);


CREATE TABLE approval_previews (
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


CREATE TABLE approval_records (
	request_id VARCHAR(36) NOT NULL,
	approver_id VARCHAR(40) NOT NULL,
	approver_name VARCHAR(80) NOT NULL,
	outcome VARCHAR(16) NOT NULL,
	opinion TEXT NOT NULL,
	at VARCHAR(40) NOT NULL,
	PRIMARY KEY (request_id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id),
	FOREIGN KEY(approver_id) REFERENCES people (id)
);


CREATE TABLE generated_documents (
	id VARCHAR(36) NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	position INTEGER NOT NULL,
	name VARCHAR(100) NOT NULL,
	content MEDIUMBLOB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (request_id, position),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id)
);

CREATE INDEX ix_generated_documents_request_id ON generated_documents (request_id);


CREATE TABLE leave_items (
	id VARCHAR(36) NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	position INTEGER NOT NULL,
	kind VARCHAR(20) NOT NULL,
	title VARCHAR(200) NOT NULL,
	day VARCHAR(10) NOT NULL,
	time VARCHAR(120) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id)
);

CREATE INDEX ix_leave_items_request_id ON leave_items (request_id);


CREATE TABLE request_counselors (
	request_id VARCHAR(36) NOT NULL,
	counselor_id VARCHAR(40) NOT NULL,
	PRIMARY KEY (request_id, counselor_id),
	FOREIGN KEY(request_id) REFERENCES leave_requests (id),
	FOREIGN KEY(counselor_id) REFERENCES people (id)
);

CREATE INDEX ix_request_counselors_counselor_id ON request_counselors (counselor_id);


CREATE TABLE request_withdrawals (
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


CREATE TABLE test_login_sessions (
	token_hash VARCHAR(64) NOT NULL,
	secret_digest VARCHAR(64) NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(token_hash) REFERENCES demo_sessions (token_hash) ON DELETE CASCADE
);


CREATE TABLE uis_login_sessions (
	token_hash VARCHAR(64) NOT NULL,
	user_type VARCHAR(80) NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(token_hash) REFERENCES demo_sessions (token_hash) ON DELETE CASCADE
);


CREATE TABLE approval_signatures (
	request_id VARCHAR(36) NOT NULL,
	signature_version VARCHAR(36) NOT NULL,
	content MEDIUMBLOB NOT NULL,
	digest VARCHAR(64) NOT NULL,
	watermark VARCHAR(160) NOT NULL,
	PRIMARY KEY (request_id),
	FOREIGN KEY(request_id) REFERENCES approval_records (request_id)
);
-- Additive migration; run with the migration account before starting this release.
CREATE TABLE IF NOT EXISTS pdf_jobs (
    request_id VARCHAR(36) NOT NULL PRIMARY KEY,
    state VARCHAR(16) NOT NULL,
    token VARCHAR(36) NULL,
    attempts INTEGER NOT NULL,
    available DATETIME NOT NULL,
    lease_until DATETIME NULL,
    INDEX ix_pdf_jobs_state (state),
    INDEX ix_pdf_jobs_available (available),
    FOREIGN KEY (request_id) REFERENCES leave_requests(id)
);
-- Additive DDL only. Apply with the migration account before deploying directory v2.
-- The application migrates the legacy roster and fills these tables transactionally.
CREATE TABLE IF NOT EXISTS directory_classes (
 class_id VARCHAR(36) NOT NULL PRIMARY KEY,
 name VARCHAR(80) NOT NULL,
 grade VARCHAR(20) NOT NULL,
 department VARCHAR(80) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS class_counselors (
 class_id VARCHAR(36) NOT NULL,
 user_id VARCHAR(40) NOT NULL,
 PRIMARY KEY (class_id,user_id),
 FOREIGN KEY (class_id) REFERENCES directory_classes(class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS directory_students (
 user_id VARCHAR(40) NOT NULL PRIMARY KEY,
 major VARCHAR(80) NOT NULL,
 class_id VARCHAR(36) NOT NULL,
 FOREIGN KEY (class_id) REFERENCES directory_classes(class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE request_attachments (
	id VARCHAR(36) NOT NULL, 
	request_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	size INTEGER NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	content MEDIUMBLOB NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (request_id, position), 
	FOREIGN KEY(request_id) REFERENCES leave_requests (id)
);

CREATE INDEX ix_request_attachments_request_id ON request_attachments (request_id);
