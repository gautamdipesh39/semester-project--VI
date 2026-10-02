# MediAssist AI

An educational symptom-analysis platform built with Flask, Pandas and a **from-scratch Bernoulli Naive Bayes classifier**. It does not use scikit-learn.

> **Safety notice:** This app is a demonstration, not a medical device. It cannot diagnose disease or prescribe medication. Show emergency guidance for high-risk results and always advise a qualified clinician.

## Setup

```bash
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python scripts/clean_data.py
python app.py
```

Open `http://127.0.0.1:5050`. The initial administrator account is `admin@mediassist.local` / `ChangeMe123!`; change it immediately.

## XAMPP MySQL

1. Start **Apache** and **MySQL** in XAMPP.
2. Create your local configuration file: `cp .env.example .env`.
3. In `.env`, keep this URL for the usual XAMPP root user with no password:

   ```env
   DATABASE_URL=mysql+pymysql://root:@127.0.0.1:3306/mediassist_ai
   ```

   If your MySQL root account has a password, use `root:YOUR_PASSWORD@...` instead.
4. Start `python app.py`. It automatically creates the `mediassist_ai` database plus the `users` and `health_records` tables. You may alternatively import `database/schema.sql` in phpMyAdmin.
5. Register a **new** patient account after enabling MySQL. New users and their analyses will appear in phpMyAdmin under `mediassist_ai`.

Without `DATABASE_URL`, the app uses `instance/mediassist.db` as a local SQLite fallback. Existing SQLite records are not automatically copied to MySQL.

## Admin records and analytics

The Admin dashboard can search by patient ID, name, or email. It displays each matching patient's full symptom-analysis history, plus a bar chart of the most reported predicted diseases, analyses by age group, and the most reported diseases from the previous 30 days. Age is collected when a new account is registered so the dashboard can form the age groups.

There are two user dashboards: Patient and Admin. Doctors are managed by Admin as recommendation-directory records; they do not have a public login or dashboard. Admin adds a doctor's name, specialty, hospital, qualification, experience, and contact details, and the system uses those details in patient recommendations.

Patient sign-up collects only full name, email, and password. After account creation, the patient may optionally complete a separate private profile with age, contact, allergies, known conditions, and emergency contact information.

## Hospital and doctor directory

On first startup, the application imports the supplied `Dataset/Specialist_Recommendation_Dataset_Nepal.xlsx` into MySQL. It creates `specialties`, `hospitals`, `hospital_specialties`, `disease_specialties`, and `doctor_profiles` tables. The catalogue currently seeds 23 Nepal hospitals, their available specialties, and disease-to-specialty mappings.

As an administrator, open **Manage directory** from the navigation to add doctors, hospitals, and specialties or deactivate an existing doctor/hospital. Patient analysis results use the disease mapping to show matching doctors and hospitals. A matching doctor must have a `doctor_profiles` entry; create it from **Manage directory** or have the doctor choose a specialization during registration.

## Deploying on Render

This repository includes `render.yaml` and starts with Gunicorn. Push the project to GitHub, then create a new **Blueprint** service in Render and select the repository.

In Render's Environment settings, add:

```text
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE_NAME
DB_SSL=true
ADMIN_EMAIL=your-admin-email@example.com
ADMIN_INITIAL_PASSWORD=a-long-unique-admin-password
```

`DATABASE_URL` must point to a public hosted MySQL-compatible database. TiDB Cloud is compatible: enter its host, port, database, username and password in the Render `DATABASE_URL`, and keep `DB_SSL=true`. If the password has special characters such as `@`, `:`, or `/`, URL-encode it. Render cannot connect to XAMPP/MySQL running only on your Mac. Do not add `.env` to GitHub or paste local database credentials into Render build logs.

Create the database in TiDB Cloud (or your managed MySQL provider) first. Render keeps `CREATE_DATABASE_ON_STARTUP` disabled; this avoids requiring the database user to have global `CREATE DATABASE` permission. Keep your local XAMPP `DATABASE_URL` unchanged in `.env`; it is separate from Render's environment variables.

After deploy, open `/health` to verify the web service and then open `/` for the application. The first startup creates required tables and the initial administrator using the Render environment variables.

## Data

Place CSVs in `data/raw/` and run `python scripts/clean_data.py`. Expected prediction columns are `disease` (or `prognosis`) and symptoms such as `symptom_1`, `symptom_2` or binary symptom columns. The supplied Excel files in `Dataset/` are also read where valid. The script normalizes names, removes duplicates/empty rows, and writes `data/cleaned/disease_training.csv`.

Good public training sources: Kaggle's *Disease Prediction Using Machine Learning* and the UCI Machine Learning Repository. Use appropriately licensed, clinically validated data before any real healthcare use.
