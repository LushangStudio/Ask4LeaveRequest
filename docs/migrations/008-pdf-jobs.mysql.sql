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
