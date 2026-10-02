-- Run this only if you already created the database before the new Admin/Doctor update.
-- If app.py starts successfully, it adds these columns automatically; do not run duplicate ALTER statements.
USE mediassist_ai;

ALTER TABLE users
  ADD COLUMN age TINYINT UNSIGNED NULL AFTER full_name;

-- Run this statement only if your existing symptoms column is JSON.
ALTER TABLE health_records
  MODIFY symptoms TEXT NOT NULL;

ALTER TABLE health_records
  ADD COLUMN review_status ENUM('pending','reviewed') NOT NULL DEFAULT 'pending' AFTER risk_level,
  ADD COLUMN doctor_note TEXT NULL AFTER review_status,
  ADD COLUMN reviewed_by INT NULL AFTER doctor_note,
  ADD COLUMN reviewed_at TIMESTAMP NULL AFTER reviewed_by;
