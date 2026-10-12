-- Migration 007: authoritative class directory in the database.
-- Migrate old operator JSON once using app.import_directory before restart.

CREATE TABLE IF NOT EXISTS class_directory (
	id INTEGER NOT NULL AUTO_INCREMENT,
	directory JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	updated VARCHAR(40) NOT NULL,
	PRIMARY KEY (id)
);
