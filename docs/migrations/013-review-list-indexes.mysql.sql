-- Apply once to an existing MySQL database with the migration account.
-- Additive indexes for date range screening, ordering, and item-date existence checks.
CREATE INDEX ix_leave_requests_ends_starts ON leave_requests (ends, starts);
CREATE INDEX ix_leave_requests_created_id ON leave_requests (created, id);
CREATE INDEX ix_leave_items_request_day ON leave_items (request_id, day);
