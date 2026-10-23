-- Additive migration before 1.1.0. Existing terminal revoked requests stay unchanged.
-- Retains prior approval, withdrawal, document digests and signature snapshot.
CREATE TABLE IF NOT EXISTS approval_archives (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL,
    record JSON NOT NULL,
    signature_content MEDIUMBLOB,
    at VARCHAR(40) NOT NULL,
    INDEX ix_approval_archives_request_id (request_id),
    FOREIGN KEY (request_id) REFERENCES leave_requests (id)
);
