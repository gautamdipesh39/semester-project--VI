# MediAssist AI — Project Overview and Defense Guide

## 1. Project title

**MediAssist AI: AI-Assisted Symptom Analysis and Health Information Platform**

## 2. Problem statement

Patients often cannot describe symptoms using medical language and may not know which specialist to visit. MediAssist AI provides simple multiple-choice symptom selection, estimates the most similar disease pattern from a dataset, gives safety-focused health information, suggests an appropriate specialist, and stores a personal analysis history.

It is an **educational decision-support prototype**. It is not a medical diagnosis tool, a prescription system, or an emergency service.

## 3. Main objectives

1. Make symptom entry easy for non-technical patients using checkboxes.
2. Predict the disease class most associated with the selected symptom pattern.
3. Display a risk level using clear colours: green (low), yellow (medium), and red (high).
4. Provide general medicine/precaution information and specialist guidance.
5. Implement role-based access for Patient, Doctor, and Administrator.
6. Store user accounts and health-analysis history in MySQL through XAMPP.

## 4. Features

| Role / Feature | Description |
|---|---|
| Landing page | Explains the platform and directs users to register or sign in. |
| Patient | Selects multiple symptoms, sees a predicted disease, confidence, risk warning, medicine information, specialist recommendation, and history. |
| Doctor | A reserved, currently blank clinical workspace for future reviewed patient records. |
| Admin | Views registered patients, recent analyses, total analyses, and high-risk flags. |
| Authentication | Passwords are securely hashed before storage. |
| Risk colours | Green = low, yellow = medium, red = high/urgent attention. |

## 5. Technology stack

| Layer | Technology | Reason |
|---|---|---|
| Front end | HTML, CSS, Jinja templates | Simple, responsive, green healthcare-themed interface. |
| Back end | Python Flask | Lightweight framework for routes, forms, sessions, and templates. |
| Data processing | Pandas | Reads Excel/CSV data, cleans records, removes duplicates, and exports clean CSV. |
| Machine learning | Custom Python implementation | Demonstrates how the algorithm works without scikit-learn. |
| Database | MySQL through XAMPP (SQLite fallback) | Stores users and health records. |
| Excel import | openpyxl | Allows Pandas to read `.xlsx` datasets. |

## 6. Dataset and data preparation

The project uses the supplied **Disease Prediction Dataset.xlsx**. It contains approximately 3,000 patient records with 0/1 symptom columns and a `Disease` label.

### Data-cleaning process

The script `scripts/clean_data.py` performs these steps using Pandas:

1. Reads CSV files from `data/raw/` and valid Excel files from `Dataset/`.
2. Converts column names to a consistent format, such as `Chest Pain` → `chest_pain`.
3. Identifies the target column (`disease`, `prognosis`, or `diagnosis`).
4. Identifies binary symptom columns: `1` means present and `0` means absent.
5. Converts every patient's positive symptoms into one list, for example:

   ```text
   Disease: Influenza
   Symptoms: fever | cough | fatigue
   ```

6. Removes incomplete rows and duplicate records.
7. Exports the cleaned data to `data/cleaned/disease_training.csv`.

After processing, the project produced **3,012 cleaned training rows**, **42 disease classes**, and **115 possible symptoms**. The exact number can change if the source data changes.

### Important clarification

`disease_training.csv` is **not** a trained model. It is the cleaned dataset used to train the model. The algorithm trains in memory each time `app.py` starts.

## 7. Algorithm used: Bernoulli Naive Bayes

The project uses a **Bernoulli Naive Bayes classifier**, written from scratch in `services/model.py`. Scikit-learn is not used.

### Why this algorithm?

Bernoulli Naive Bayes is appropriate because every symptom is binary:

- `1` / selected: symptom is present
- `0` / not selected: symptom is absent

It is fast, understandable, works well with many yes/no features, and is ideal for a college project where the algorithm must be explainable.

### What does “Naive” mean?

The algorithm assumes symptoms are independent after the disease is known. This is not perfectly true in medicine—some symptoms are related—but the assumption makes the calculation simple and efficient.

### Training process

For every disease, the model calculates:

1. **Prior probability**: how common that disease is in the training data.

   \[
   P(Disease) = \frac{number\ of\ records\ for\ the\ disease}{total\ records}
   \]

2. **Conditional probability**: how frequently each symptom occurs for that disease.

   \[
   P(Symptom|Disease) = \frac{symptom\ count + \alpha}{disease\ record\ count + 2\alpha}
   \]

3. **Laplace smoothing**: the project uses \(\alpha = 1\). It prevents a probability from becoming zero if a symptom was not observed in a small training group.

4. **Prediction**: for selected and unselected symptoms, it calculates a score for every disease. The disease with the highest normalized score is shown as the result.

Conceptually:

\[
P(D|S_1, S_2,...) \propto P(D) \prod_i P(S_i|D)
\]

The code uses logarithms for numerical stability because multiplying many small probabilities can become too small for a computer to represent accurately.

### Simple example to say in viva

> If the user selects fever and cough, the model checks how often fever and cough occurred for Influenza, Common Cold, and every other disease in the training data. It combines those probabilities with how common each disease is. The disease with the highest probability is returned.

## 8. Prediction and risk flow

```text
Patient selects symptoms
        ↓
Flask receives form data
        ↓
Custom Bernoulli Naive Bayes predicts disease + confidence
        ↓
Risk rules check red-flag symptoms
        ↓
Show disease, general guidance, specialist, and risk colour
        ↓
Store analysis in MySQL health_records table
```

Red-flag symptoms such as chest pain, shortness of breath, swelling, and irregular heartbeat can trigger a **high-risk red warning**. This is a safety rule, separate from the machine-learning confidence.

## 9. Database design

The MySQL schema is in `database/schema.sql`.

### `users` table

| Field | Purpose |
|---|---|
| id | Unique user identifier |
| full_name | User name |
| email | Unique login email |
| password_hash | Hashed password, never plain text |
| role | patient, doctor, or admin |
| created_at | Registration date/time |

### `health_records` table

| Field | Purpose |
|---|---|
| user_id | Connects the record to the patient |
| symptoms | User-selected symptoms |
| predicted_disease | Highest-scoring disease label |
| confidence | Model confidence percentage |
| risk_level | low, medium, or high |
| created_at | Analysis date/time |

## 10. How to demonstrate the project

1. Start MySQL in XAMPP and open phpMyAdmin.
2. Confirm the `mediassist_ai` database and its tables exist.
3. Run the Flask application and open `http://127.0.0.1:5000`.
4. Show the landing page and register a Patient account.
5. Log in as that patient and select multiple symptoms.
6. Submit the analysis and explain the predicted disease, confidence, risk colour, medicine information, and specialist recommendation.
7. Return to the patient dashboard to show saved health history.
8. Open phpMyAdmin and show the newly inserted `users` and `health_records` rows.
9. Log in as administrator to demonstrate the analytics dashboard.

## 11. College presentation / viva defense

### Opening presentation (about one minute)

> Our project is MediAssist AI, an AI-assisted healthcare information platform. The main problem we solve is that patients often do not know medical terms or which specialist they should visit. Our patient interface uses simple symptom checkboxes. The system applies a Bernoulli Naive Bayes model, implemented from scratch without scikit-learn, to compare the selected symptoms with our cleaned disease dataset. It provides a likely disease pattern, a confidence value, risk-based safety guidance, medicine information, specialist recommendations, and a personal health-history dashboard. The system uses Flask for the back end, HTML/CSS for the front end, Pandas for data cleaning, and MySQL through XAMPP for data storage.

### Likely viva questions and strong answers

**Q: Which algorithm did you use?**  
**A:** Bernoulli Naive Bayes. It is designed for binary features, and our symptoms are present or absent. We implemented it from scratch using Python dictionaries, counters, probability formulas, Laplace smoothing, and log probabilities.

**Q: Why did you not use scikit-learn?**  
**A:** The project requirement was to implement the algorithm ourselves. This let us understand the full training and prediction process rather than only calling a library function.

**Q: What is the difference between cleaning and training?**  
**A:** Cleaning uses Pandas to normalize columns, remove duplicates, and transform source data into usable symptom lists. Training reads the cleaned CSV and calculates disease and symptom probabilities. The CSV is data; the learned probability counts in memory are the trained model.

**Q: Why Naive Bayes rather than a neural network?**  
**A:** Our dataset is structured, relatively small, and binary. Naive Bayes is fast, transparent, and easier to explain. A neural network would need more data, more tuning, and would be harder to interpret.

**Q: How do you avoid zero probability?**  
**A:** We use Laplace smoothing with alpha equal to 1. This adds a small value to counts so an unseen symptom does not force the entire disease probability to zero.

**Q: Is confidence the same as medical certainty?**  
**A:** No. It is a relative score from this dataset and model. It must not be treated as a clinical certainty. The application clearly includes a safety disclaimer and recommends professional care.

**Q: How is high risk detected?**  
**A:** The system has safety rules for red-flag symptoms such as chest pain and shortness of breath. These rules can show an urgent red warning even when model confidence is limited.

**Q: How are passwords protected?**  
**A:** Passwords are hashed using Werkzeug before being stored. The database does not store the original password text.

**Q: Where is the data stored?**  
**A:** In MySQL through XAMPP when `DATABASE_URL` is configured in `.env`. Users are stored in `users`; completed analyses are stored in `health_records`. SQLite is only a local fallback for easy development.

## 12. Limitations and ethical considerations

Be honest about these during defense:

- The result is pattern matching, not a clinical diagnosis.
- Training data quality and class balance directly affect predictions.
- Naive Bayes assumes independent symptoms, which is a simplification.
- The medicine section provides general information only; it must not prescribe doses or replace a clinician.
- Real healthcare deployment would require validated clinical datasets, doctor review, security hardening, consent, encryption, audit logs, and regulatory approval.
- The current Doctor portal is intentionally a placeholder; future work can add verified doctor accounts, appointments, and reviewed records.

## 13. Future improvements

1. Add doctor verification and appointment booking.
2. Use clinically validated and larger datasets.
3. Evaluate with train/test splits, accuracy, precision, recall, F1-score, and confusion matrix.
4. Add demographics and duration/severity questions with careful clinical validation.
5. Integrate a medicine and precaution database rather than a small in-code mapping.
6. Add Nepali language support and accessibility improvements.
7. Encrypt sensitive health data and add consent/audit controls.
8. Save the trained model safely with dataset versioning for production.

## 14. Important project files

| File | Purpose |
|---|---|
| `app.py` | Flask routes, authentication, prediction flow, risk logic, database connection. |
| `services/model.py` | From-scratch Bernoulli Naive Bayes classifier. |
| `scripts/clean_data.py` | Pandas data-cleaning and CSV export process. |
| `data/cleaned/disease_training.csv` | Cleaned data used for training. |
| `database/schema.sql` | MySQL tables for XAMPP/phpMyAdmin. |
| `templates/` | HTML UI pages. |
| `static/style.css` | Green theme and risk-colour styling. |

## 15. Final conclusion

MediAssist AI demonstrates a complete small AI web application: data cleaning, custom machine learning, a Flask back end, role-based dashboards, risk-aware UI, and database storage. Its major strength is that the full prediction method is transparent and implemented from scratch. Its correct use is educational health support and symptom organisation—not replacing doctors or emergency care.
