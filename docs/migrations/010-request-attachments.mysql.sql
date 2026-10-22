-- Additive migration. Back up, then apply with the migration account before deploying.
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
