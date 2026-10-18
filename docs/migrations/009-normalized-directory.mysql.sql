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
