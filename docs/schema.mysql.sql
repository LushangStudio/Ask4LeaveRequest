-- Initial schema only. Generated from app/main.py; review before running.

CREATE TABLE people (
	id VARCHAR(40) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	counselor VARCHAR(40), 
	profile JSON NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE demo_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	person_id VARCHAR(40) NOT NULL, 
	expires DATETIME NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(person_id) REFERENCES people (id)
)

;

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
)

;

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
)

;

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
)

;
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
)

;
CREATE INDEX ix_leave_items_request_id ON leave_items (request_id);
