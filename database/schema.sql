CREATE DATABASE IF NOT EXISTS mediassist_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE mediassist_ai;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  age TINYINT UNSIGNED NULL,
  email VARCHAR(150) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('patient','doctor','admin') NOT NULL DEFAULT 'patient',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE health_records (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  symptoms TEXT NOT NULL,
  predicted_disease VARCHAR(120),
  confidence DECIMAL(5,2),
  risk_level ENUM('low','medium','high') DEFAULT 'low',
  review_status ENUM('pending','reviewed') NOT NULL DEFAULT 'pending',
  doctor_note TEXT NULL,
  reviewed_by INT NULL,
  reviewed_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE specialties (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL UNIQUE,
  department VARCHAR(120),
  active TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE hospitals (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(180) NOT NULL UNIQUE,
  province VARCHAR(80),
  district VARCHAR(80),
  city VARCHAR(100),
  address VARCHAR(255),
  hospital_type VARCHAR(100),
  contact VARCHAR(100),
  map_url VARCHAR(500),
  active TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE hospital_specialties (
  hospital_id INT NOT NULL,
  specialty_id INT NOT NULL,
  PRIMARY KEY (hospital_id, specialty_id),
  FOREIGN KEY (hospital_id) REFERENCES hospitals(id) ON DELETE CASCADE,
  FOREIGN KEY (specialty_id) REFERENCES specialties(id) ON DELETE CASCADE
);

CREATE TABLE disease_specialties (
  disease_name VARCHAR(120) NOT NULL PRIMARY KEY,
  specialty_id INT NOT NULL,
  recommendation_reason TEXT,
  FOREIGN KEY (specialty_id) REFERENCES specialties(id)
);

CREATE TABLE doctor_profiles (
  user_id INT NOT NULL PRIMARY KEY,
  specialty_id INT,
  hospital_id INT,
  qualification VARCHAR(180),
  experience_years INT,
  contact VARCHAR(100),
  active TINYINT(1) NOT NULL DEFAULT 1,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (specialty_id) REFERENCES specialties(id),
  FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
);

CREATE TABLE patient_profiles (
  user_id INT NOT NULL PRIMARY KEY,
  gender VARCHAR(30),
  phone VARCHAR(40),
  address VARCHAR(255),
  allergies TEXT,
  medical_conditions TEXT,
  emergency_contact VARCHAR(120),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
