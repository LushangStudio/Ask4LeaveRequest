-- Back up and apply once with the migration account before deploying.
-- Existing rows retain their legacy wording and original date/item semantics.
ALTER TABLE leave_requests ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'legacy';
