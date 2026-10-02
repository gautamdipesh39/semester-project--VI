from pathlib import Path
import os
import csv
import sqlite3
import re
import ssl
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
import pymysql
import pandas as pd
from werkzeug.security import check_password_hash, generate_password_hash
from services.model import SymptomNaiveBayes
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-your-env-before-deployment')
app.config['DATABASE'] = ROOT / 'instance' / 'mediassist.db'
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL', '')

MEDICINES = {
    'Common Cold': ('Supportive care only', 'Rest, fluids and saline nasal rinse. Ask a pharmacist/doctor before medicine.'),
    'Influenza': ('Supportive care only', 'Rest and fluids. A clinician can determine whether antivirals are appropriate.'),
    'Migraine': ('Discuss with a clinician', 'A clinician/pharmacist can advise safe pain relief based on your history.'),
    'Gastroenteritis': ('Oral rehydration', 'Small frequent sips of oral rehydration solution; seek care for dehydration.'),
    'Allergic Reaction': ('Urgent review if severe', 'Avoid the suspected trigger. Swelling of face/throat or breathing trouble is an emergency.'),
    'Heart Concern': ('Emergency assessment', 'Chest pain or breathing difficulty needs urgent emergency evaluation.'),
}
SPECIALISTS = {'Heart Concern': 'Cardiologist', 'Migraine': 'Neurologist', 'Allergic Reaction': 'Allergist / Immunologist', 'Gastroenteritis': 'Gastroenterologist', 'Influenza': 'General Physician', 'Common Cold': 'General Physician'}
RED_FLAGS = {'chest_pain', 'shortness_of_breath', 'swelling', 'irregular_heartbeat'}

def db():
    if 'db' not in g:
        database_url = app.config['DATABASE_URL']
        if database_url.startswith('mysql'):
            parsed = urlparse(database_url)
            database_name = parsed.path.lstrip('/') or 'mediassist_ai'
            query_params = parse_qs(parsed.query)
            if not re.fullmatch(r'[A-Za-z0-9_]+', database_name):
                raise RuntimeError('DATABASE_URL contains an invalid database name.')
            connection_args = dict(host=parsed.hostname or '127.0.0.1', port=parsed.port or 3306,
                                   user=unquote(parsed.username or 'root'), password=unquote(parsed.password or ''),
                                   charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=False)
            ssl_mode = query_params.get('ssl-mode', query_params.get('ssl_mode', ['']))[0].upper()
            is_tidb = (parsed.hostname or '').endswith('.tidbcloud.com')
            if os.getenv('DB_SSL', '').lower() == 'true' or is_tidb or ssl_mode in {'REQUIRED', 'VERIFY_CA', 'VERIFY_IDENTITY'}:
                connection_args['ssl'] = ssl.create_default_context()
            # Local XAMPP can create a database; hosted Render databases are normally pre-created.
            if os.getenv('CREATE_DATABASE_ON_STARTUP', '').lower() == 'true':
                bootstrap = pymysql.connect(**connection_args)
                try:
                    with bootstrap.cursor() as cursor:
                        cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
                    bootstrap.commit()
                finally:
                    bootstrap.close()
            g.db = pymysql.connect(database=database_name, **connection_args)
        else:
            app.config['DATABASE'].parent.mkdir(exist_ok=True)
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
    return g.db

def using_mysql():
    return app.config['DATABASE_URL'].startswith('mysql')

def query(sql, params=()):
    """Execute parameterised SQL for either XAMPP MySQL or local SQLite."""
    connection = db()
    if isinstance(connection, sqlite3.Connection):
        return connection.execute(sql, params)
    cursor = connection.cursor()
    cursor.execute(sql.replace('?', '%s'), params)
    return cursor

def insert_ignore(sql, params=()):
    """Insert a catalogue row once on both SQLite and MySQL."""
    if using_mysql():
        return query(sql.replace('INSERT INTO', 'INSERT IGNORE INTO', 1), params)
    return query(sql.replace('INSERT INTO', 'INSERT OR IGNORE INTO', 1), params)

@app.teardown_appcontext
def close_db(_):
    connection = g.pop('db', None)
    if connection: connection.close()

def initialize_db():
    con = db()
    if using_mysql():
        query('''CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(120) NOT NULL, age TINYINT UNSIGNED NULL, email VARCHAR(150) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL, role ENUM('patient','doctor','admin') NOT NULL DEFAULT 'patient', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        query('''CREATE TABLE IF NOT EXISTS health_records (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, symptoms TEXT NOT NULL, predicted_disease VARCHAR(120), confidence DECIMAL(5,2), risk_level ENUM('low','medium','high') DEFAULT 'low', review_status ENUM('pending','reviewed') NOT NULL DEFAULT 'pending', doctor_note TEXT NULL, reviewed_by INT NULL, reviewed_at TIMESTAMP NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)''')
        columns = {row['Field'] for row in query('SHOW COLUMNS FROM users').fetchall()}
        if 'age' not in columns:
            query('ALTER TABLE users ADD COLUMN age TINYINT UNSIGNED NULL AFTER full_name')
        record_columns = {row['Field']: row['Type'].lower() for row in query('SHOW COLUMNS FROM health_records').fetchall()}
        if record_columns.get('symptoms') == 'json':
            query('ALTER TABLE health_records MODIFY symptoms TEXT NOT NULL')
        mysql_additions = {'review_status': "ENUM('pending','reviewed') NOT NULL DEFAULT 'pending'", 'doctor_note': 'TEXT NULL', 'reviewed_by': 'INT NULL', 'reviewed_at': 'TIMESTAMP NULL'}
        for name, definition in mysql_additions.items():
            if name not in record_columns:
                query(f'ALTER TABLE health_records ADD COLUMN {name} {definition}')
    else:
        con.executescript('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, age INTEGER, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS health_records (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, symptoms TEXT NOT NULL, predicted_disease TEXT, confidence REAL, risk_level TEXT, review_status TEXT NOT NULL DEFAULT 'pending', doctor_note TEXT, reviewed_by INTEGER, reviewed_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
        columns = {row['name'] for row in con.execute('PRAGMA table_info(users)').fetchall()}
        if 'age' not in columns:
            con.execute('ALTER TABLE users ADD COLUMN age INTEGER')
        record_columns = {row['name'] for row in con.execute('PRAGMA table_info(health_records)').fetchall()}
        sqlite_additions = {'review_status': "TEXT NOT NULL DEFAULT 'pending'", 'doctor_note': 'TEXT', 'reviewed_by': 'INTEGER', 'reviewed_at': 'TEXT'}
        for name, definition in sqlite_additions.items():
            if name not in record_columns:
                con.execute(f'ALTER TABLE health_records ADD COLUMN {name} {definition}')
    create_catalog_tables()
    admin_email = os.getenv('ADMIN_EMAIL', 'admin@mediassist.local').lower()
    admin_password = os.getenv('ADMIN_INITIAL_PASSWORD', 'ChangeMe123!')
    if not query('SELECT 1 FROM users WHERE email = ?', (admin_email,)).fetchone():
        query('INSERT INTO users (full_name,age,email,password_hash,role) VALUES (?,?,?,?,?)', ('System Administrator', None, admin_email, generate_password_hash(admin_password), 'admin'))
    con.commit()
    seed_catalog_if_empty()
    seed_verified_directory_if_empty()

def create_catalog_tables():
    id_type = 'INT AUTO_INCREMENT PRIMARY KEY' if using_mysql() else 'INTEGER PRIMARY KEY'
    active_type = 'TINYINT(1) NOT NULL DEFAULT 1' if using_mysql() else 'INTEGER NOT NULL DEFAULT 1'
    query(f'''CREATE TABLE IF NOT EXISTS specialties (id {id_type}, name VARCHAR(120) NOT NULL UNIQUE, department VARCHAR(120), active {active_type})''')
    query(f'''CREATE TABLE IF NOT EXISTS hospitals (id {id_type}, name VARCHAR(180) NOT NULL UNIQUE, province VARCHAR(80), district VARCHAR(80), city VARCHAR(100), address VARCHAR(255), hospital_type VARCHAR(100), contact VARCHAR(100), map_url VARCHAR(500), active {active_type})''')
    query(f'''CREATE TABLE IF NOT EXISTS hospital_specialties (hospital_id INT NOT NULL, specialty_id INT NOT NULL, PRIMARY KEY (hospital_id, specialty_id))''')
    query(f'''CREATE TABLE IF NOT EXISTS disease_specialties (disease_name VARCHAR(120) NOT NULL PRIMARY KEY, specialty_id INT NOT NULL, recommendation_reason TEXT)''')
    query(f'''CREATE TABLE IF NOT EXISTS doctor_profiles (user_id INT NOT NULL PRIMARY KEY, specialty_id INT, hospital_id INT, qualification VARCHAR(180), experience_years INT, contact VARCHAR(100), active {active_type})''')
    query(f'''CREATE TABLE IF NOT EXISTS patient_profiles (user_id INT NOT NULL PRIMARY KEY, gender VARCHAR(30), phone VARCHAR(40), address VARCHAR(255), allergies TEXT, medical_conditions TEXT, emergency_contact VARCHAR(120))''')
    if using_mysql():
        hospital_columns = {row['Field'] for row in query('SHOW COLUMNS FROM hospitals').fetchall()}
        if 'map_url' not in hospital_columns:
            query('ALTER TABLE hospitals ADD COLUMN map_url VARCHAR(500) NULL AFTER contact')
    else:
        hospital_columns = {row['name'] for row in query('PRAGMA table_info(hospitals)').fetchall()}
        if 'map_url' not in hospital_columns:
            query('ALTER TABLE hospitals ADD COLUMN map_url TEXT')

def seed_catalog_if_empty():
    """Imports the supplied Nepal specialist workbook only when the database catalogue is empty."""
    if query('SELECT id FROM hospitals LIMIT 1').fetchone():
        return
    source = ROOT / 'Dataset' / 'Specialist_Recommendation_Dataset_Nepal.xlsx'
    if not source.exists():
        return
    data = pd.read_excel(source).fillna('')
    specialty_ids, hospital_ids = {}, {}
    for _, row in data.iterrows():
        specialty = str(row['Specialist_Name']).strip()
        department = str(row['Department']).strip()
        hospital = str(row['Hospital_Name']).strip()
        location = str(row['Location']).strip()
        insert_ignore('INSERT INTO specialties (name, department) VALUES (?,?)', (specialty, department))
        specialty_row = query('SELECT id FROM specialties WHERE name=?', (specialty,)).fetchone(); specialty_id = specialty_row['id']
        specialty_ids[specialty] = specialty_id
        insert_ignore('INSERT INTO hospitals (name, city, address, hospital_type) VALUES (?,?,?,?)', (hospital, location, location, str(row['Hospital_Type']).strip()))
        hospital_row = query('SELECT id FROM hospitals WHERE name=?', (hospital,)).fetchone(); hospital_id = hospital_row['id']
        hospital_ids[hospital] = hospital_id
        insert_ignore('INSERT INTO hospital_specialties (hospital_id,specialty_id) VALUES (?,?)', (hospital_id, specialty_id))
        insert_ignore('INSERT INTO disease_specialties (disease_name,specialty_id,recommendation_reason) VALUES (?,?,?)', (str(row['Disease_Name']).strip(), specialty_id, str(row['Recommendation_Reason']).strip()))
    db().commit()

def seed_verified_directory_if_empty():
    """Seeds public hospital-directory records from the cited HAMS Hospital pages."""
    # Remove the old project demonstration rows, but never remove Admin-created entries.
    sample_rows = query('SELECT id FROM users WHERE email LIKE ?', ('demo.%@directory.local',)).fetchall()
    for row in sample_rows:
        query('DELETE FROM doctor_profiles WHERE user_id=?', (row['id'],))
        query('DELETE FROM users WHERE id=?', (row['id'],))
    cardiology = query('SELECT id FROM specialties WHERE name=?', ('Cardiologist',)).fetchone()
    if not cardiology:
        return
    insert_ignore('INSERT INTO hospitals (name,city,address,hospital_type,contact,map_url) VALUES (?,?,?,?,?,?)', ('HAMS Hospital', 'Kathmandu', 'Mandikhatar Road, Dhumbarahi, Kathmandu', 'Private Hospital', '01-4377404 / 01-4377704', 'https://www.google.com/maps/search/?api=1&query=HAMS+Hospital+Dhumbarahi+Kathmandu'))
    hospital = query('SELECT id FROM hospitals WHERE name=?', ('HAMS Hospital',)).fetchone()
    insert_ignore('INSERT INTO hospital_specialties (hospital_id,specialty_id) VALUES (?,?)', (hospital['id'], cardiology['id']))
    doctors = [
        ('Dr. Roshan Raut', 'roshan.raut@directory.local', 'MBBS; MD in Internal Medicine & Cardiology; Fellowship in Cardiac Electrophysiology', 0),
        ('Dr. Mukunda Sharma', 'mukunda.sharma@directory.local', 'MBBS; MD in Cardiovascular Medicine; Consultant Cardiologist & Electrophysiology Specialist', 12),
        ('Dr. Yadav Deo Bhatta', 'yadav.bhatta@directory.local', 'MD, Internal Medicine; DM, Cardiology', 0),
    ]
    for name, email, qualification, experience in doctors:
        insert_ignore('INSERT INTO users (full_name,age,email,password_hash,role) VALUES (?,?,?,?,?)', (name, None, email, generate_password_hash(os.urandom(16).hex()), 'doctor'))
        doctor = query('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        insert_ignore('INSERT INTO doctor_profiles (user_id,specialty_id,hospital_id,qualification,experience_years,contact) VALUES (?,?,?,?,?,?)', (doctor['id'], cardiology['id'], hospital['id'], qualification, experience, 'HAMS Hospital: 01-4377404 / 01-4377704'))
    # Grande International Hospital publicly lists these cardiology consultants.
    grande = query('SELECT id FROM hospitals WHERE name=?', ('Grande International Hospital',)).fetchone()
    if grande:
        query('UPDATE hospitals SET address=?,contact=?,map_url=? WHERE id=?', ('Dhapasi, Kathmandu', '9801202550 / 01-5159266', 'https://www.google.com/maps/search/?api=1&query=Grande+International+Hospital+Dhapasi+Kathmandu', grande['id']))
        insert_ignore('INSERT INTO hospital_specialties (hospital_id,specialty_id) VALUES (?,?)', (grande['id'], cardiology['id']))
        grande_doctors = [
            ('Dr. Naresh Maharjan', 'naresh.maharjan@directory.local', 'MBBS; MD (Cardiology); Consultant Cardiologist'),
            ('Dr. Milan Prakash Shrestha', 'milan.shrestha@directory.local', 'Consultant Cardiologist'),
            ('Prof. Dr. Chandra Mani Adhikari', 'chandra.adhikari@directory.local', 'Consultant Interventional Cardiologist'),
            ('Dr. Bhawani Manandhar', 'bhawani.manandhar@directory.local', 'Consultant Cardiologist'),
            ('Asst. Prof. Dr. Surya Devkota', 'surya.devkota@directory.local', 'Consultant Interventional Cardiologist'),
        ]
        for name, email, qualification in grande_doctors:
            insert_ignore('INSERT INTO users (full_name,age,email,password_hash,role) VALUES (?,?,?,?,?)', (name, None, email, generate_password_hash(os.urandom(16).hex()), 'doctor'))
            doctor = query('SELECT id FROM users WHERE email=?', (email,)).fetchone()
            insert_ignore('INSERT INTO doctor_profiles (user_id,specialty_id,hospital_id,qualification,experience_years,contact) VALUES (?,?,?,?,?,?)', (doctor['id'], cardiology['id'], grande['id'], qualification, 0, 'Grande International Hospital: 9801202550 / 01-5159266'))
    db().commit()

def current_user():
    if 'user_id' not in session: return None
    return query('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()

def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user: return redirect(url_for('login'))
            if user['role'] not in roles:
                flash('You do not have access to that area.', 'error'); return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def load_model():
    path = ROOT / 'data' / 'cleaned' / 'disease_training.csv'
    if not path.exists(): path = ROOT / 'data' / 'raw' / 'sample_training.csv'
    samples = []
    with path.open() as file:
        for row in csv.DictReader(file):
            symptoms = row.get('symptoms', '').split('|') if 'symptoms' in row else [v for k,v in row.items() if k.startswith('symptom') and v]
            samples.append(({s.strip().lower().replace(' ', '_') for s in symptoms if s}, row['disease']))
    return SymptomNaiveBayes().fit(samples)

def recommendations_for(disease):
    mapping = query('''SELECT ds.recommendation_reason, s.id AS specialty_id, s.name AS specialty, s.department
                       FROM disease_specialties ds JOIN specialties s ON s.id=ds.specialty_id
                       WHERE LOWER(ds.disease_name)=LOWER(?) AND s.active=1''', (disease,)).fetchone()
    if not mapping:
        return None, [], [], ''
    doctors = query('''SELECT u.full_name, dp.qualification, dp.experience_years, dp.contact, h.name AS hospital_name, h.city
                       FROM doctor_profiles dp JOIN users u ON u.id=dp.user_id
                       LEFT JOIN hospitals h ON h.id=dp.hospital_id
                       WHERE dp.specialty_id=? AND dp.active=1 AND u.role='doctor' LIMIT 5''', (mapping['specialty_id'],)).fetchall()
    hospitals = query('''SELECT h.id, h.name, h.city, h.district, h.address, h.hospital_type, h.contact
                         FROM hospitals h JOIN hospital_specialties hs ON hs.hospital_id=h.id
                         WHERE hs.specialty_id=? AND h.active=1 ORDER BY h.name LIMIT 8''', (mapping['specialty_id'],)).fetchall()
    return mapping['specialty'], doctors, hospitals, mapping['recommendation_reason'] or ''

MODEL = load_model()
ALL_SYMPTOMS = sorted(MODEL.features)

@app.context_processor
def inject_user(): return {'user': current_user()}

@app.route('/')
def index(): return render_template('landing.html')

@app.get('/health')
def health():
    """Lightweight Render health check that does not expose user or database data."""
    return {'status': 'ok'}, 200

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name, email, password, role = request.form['name'].strip(), request.form['email'].lower().strip(), request.form['password'], request.form['role']
        if role != 'patient' or len(password) < 8 or not name:
            flash('Enter your name and a password of at least 8 characters.', 'error')
        else:
            try:
                query('INSERT INTO users (full_name,age,email,password_hash,role) VALUES (?,?,?,?,?)', (name,None,email,generate_password_hash(password),role)); db().commit()
                user = query('SELECT id FROM users WHERE email=?', (email,)).fetchone()
                session['user_id'] = user['id']
                flash('Account created. Complete your optional health profile when ready.', 'success'); return redirect(url_for('patient_profile'))
            except (sqlite3.IntegrityError, pymysql.err.IntegrityError): flash('That email is already registered.', 'error')
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        user = query('SELECT * FROM users WHERE email=?', (request.form['email'].lower().strip(),)).fetchone()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            if user['role'] == 'doctor':
                flash('Doctors are managed as recommendations by the Admin and do not have a login dashboard.', 'error')
                return render_template('auth.html', mode='login')
            session['user_id'] = user['id']; return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('auth.html', mode='login')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

@app.route('/dashboard')
@role_required('patient','admin')
def dashboard():
    user = current_user()
    if user['role'] == 'admin': return redirect(url_for('admin_dashboard'))
    records = query('SELECT * FROM health_records WHERE user_id=? ORDER BY created_at DESC', (user['id'],)).fetchall()
    patient_stats = {'analyses': len(records), 'high': sum(record['risk_level'] == 'high' for record in records), 'latest': records[0]['predicted_disease'] if records else 'No analysis yet'}
    return render_template('patient.html', symptoms=ALL_SYMPTOMS, records=records, patient_stats=patient_stats)

@app.route('/profile', methods=['GET', 'POST'])
@role_required('patient')
def patient_profile():
    user = current_user()
    profile = query('SELECT * FROM patient_profiles WHERE user_id=?', (user['id'],)).fetchone()
    if request.method == 'POST':
        age_text = request.form.get('age', '').strip()
        age = int(age_text) if age_text.isdigit() and 1 <= int(age_text) <= 120 else None
        query('UPDATE users SET age=? WHERE id=?', (age, user['id']))
        values = (user['id'], request.form.get('gender','').strip(), request.form.get('phone','').strip(), request.form.get('address','').strip(), request.form.get('allergies','').strip(), request.form.get('medical_conditions','').strip(), request.form.get('emergency_contact','').strip())
        if profile:
            query('UPDATE patient_profiles SET gender=?,phone=?,address=?,allergies=?,medical_conditions=?,emergency_contact=? WHERE user_id=?', values[1:] + (user['id'],))
        else:
            query('INSERT INTO patient_profiles (user_id,gender,phone,address,allergies,medical_conditions,emergency_contact) VALUES (?,?,?,?,?,?,?)', values)
        db().commit(); flash('Your health profile has been saved.', 'success'); return redirect(url_for('dashboard'))
    return render_template('profile.html', profile=profile)

@app.route('/analyze', methods=['POST'])
@role_required('patient')
def analyze():
    symptoms = request.form.getlist('symptoms')
    if not symptoms: flash('Select at least one symptom.', 'error'); return redirect(url_for('dashboard'))
    ranked_results = MODEL.predict_proba(symptoms)[:3]
    result = ranked_results[0]
    disease, confidence = result[0], round(result[1] * 100, 1)
    high = bool(RED_FLAGS.intersection(symptoms)) or disease == 'Heart Concern'
    risk = 'high' if high else ('medium' if confidence >= 55 else 'low')
    query('INSERT INTO health_records (user_id,symptoms,predicted_disease,confidence,risk_level) VALUES (?,?,?,?,?)', (current_user()['id'], ', '.join(symptoms), disease, confidence, risk)); db().commit()
    specialty, doctors, hospitals, reason = recommendations_for(disease)
    possible_diseases = [{'name': name, 'confidence': round(score * 100, 1)} for name, score in ranked_results]
    return render_template('result.html', disease=disease, confidence=confidence, risk=risk, symptoms=symptoms, medicine=MEDICINES.get(disease, ('Clinical review recommended','Please discuss any treatment with a licensed professional.')), specialist=specialty or SPECIALISTS.get(disease, 'General Physician'), doctors=doctors, hospitals=hospitals, reason=reason, possible_diseases=possible_diseases)

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    search = request.args.get('search', '').strip()
    patient_id = int(search) if search.isdigit() else -1
    patients = query("SELECT * FROM users WHERE role='patient' ORDER BY created_at DESC").fetchall()
    records = query('''SELECT h.*, u.full_name, u.email, u.age
                       FROM health_records h JOIN users u ON h.user_id=u.id
                       ORDER BY h.created_at DESC''').fetchall()
    if search:
        lowered = search.lower()
        filtered_patients = [p for p in patients if p['id'] == patient_id or lowered in p['full_name'].lower() or lowered in p['email'].lower()]
        matched_ids = {p['id'] for p in filtered_patients}
        records = [r for r in records if r['user_id'] in matched_ids]
        patients = filtered_patients

    age_groups = {'Under 18': 0, '18–35': 0, '36–55': 0, '56+': 0, 'Not recorded': 0}
    disease_counts, recent_disease_counts = Counter(), Counter()
    recent_cutoff = datetime.now() - timedelta(days=30)
    for record in records:
        disease_counts[record['predicted_disease']] += 1
        age = record['age']
        if age is None: group = 'Not recorded'
        elif age < 18: group = 'Under 18'
        elif age <= 35: group = '18–35'
        elif age <= 55: group = '36–55'
        else: group = '56+'
        age_groups[group] += 1
        try:
            created = record['created_at'] if isinstance(record['created_at'], datetime) else datetime.fromisoformat(str(record['created_at']))
            if created >= recent_cutoff: recent_disease_counts[record['predicted_disease']] += 1
        except ValueError:
            pass
    chart_max = max(disease_counts.values(), default=1)
    analytics = [{'disease': disease, 'count': count, 'width': max(6, round(count / chart_max * 100))} for disease, count in disease_counts.most_common(7)]
    stats = {'patients': len(query("SELECT id FROM users WHERE role='patient'").fetchall()), 'analyses': len(query('SELECT id FROM health_records').fetchall()), 'high': len(query("SELECT id FROM health_records WHERE risk_level='high'").fetchall())}
    return render_template('admin.html', patients=patients, records=records, stats=stats, search=search,
                           analytics=analytics, age_groups=age_groups, recent_diseases=recent_disease_counts.most_common(5))

@app.route('/admin/patient/<int:patient_id>')
@role_required('admin')
def admin_patient_profile(patient_id):
    patient = query('''SELECT u.*, p.gender,p.phone,p.address,p.allergies,p.medical_conditions,p.emergency_contact
                       FROM users u LEFT JOIN patient_profiles p ON p.user_id=u.id
                       WHERE u.id=? AND u.role='patient' ''', (patient_id,)).fetchone()
    if not patient:
        abort(404)
    records = query('''SELECT h.*, reviewer.full_name AS reviewer_name
                       FROM health_records h LEFT JOIN users reviewer ON h.reviewed_by=reviewer.id
                       WHERE h.user_id=? ORDER BY h.created_at DESC''', (patient_id,)).fetchall()
    profile_stats = {'analyses': len(records), 'high': sum(r['risk_level'] == 'high' for r in records),
                     'reviewed': sum(r['review_status'] == 'reviewed' for r in records)}
    return render_template('patient_profile.html', patient=patient, records=records, profile_stats=profile_stats)

@app.route('/admin/catalog', methods=['GET', 'POST'])
@role_required('admin')
def admin_catalog():
    if request.method == 'POST':
        kind = request.form.get('kind')
        try:
            if kind == 'specialty':
                insert_ignore('INSERT INTO specialties (name,department) VALUES (?,?)', (request.form['name'].strip(), request.form.get('department', '').strip()))
            elif kind == 'hospital':
                insert_ignore('INSERT INTO hospitals (name,province,district,city,address,hospital_type,contact,map_url) VALUES (?,?,?,?,?,?,?,?)', tuple(request.form.get(key, '').strip() for key in ('name','province','district','city','address','hospital_type','contact','map_url')))
                hospital = query('SELECT id FROM hospitals WHERE name=?', (request.form['name'].strip(),)).fetchone()
                for specialty_id in request.form.getlist('specialty_ids'):
                    insert_ignore('INSERT INTO hospital_specialties (hospital_id,specialty_id) VALUES (?,?)', (hospital['id'], int(specialty_id)))
            elif kind == 'doctor':
                email = request.form['email'].strip().lower()
                # Directory doctors are created by Admin and do not have a patient-facing login.
                insert_ignore('INSERT INTO users (full_name,age,email,password_hash,role) VALUES (?,?,?,?,?)', (request.form['name'].strip(), None, email, generate_password_hash(os.urandom(24).hex()), 'doctor'))
                doctor = query('SELECT id FROM users WHERE email=?', (email,)).fetchone()
                insert_ignore('INSERT INTO doctor_profiles (user_id,specialty_id,hospital_id,qualification,experience_years,contact) VALUES (?,?,?,?,?,?)', (doctor['id'], int(request.form['specialty_id']), int(request.form['hospital_id']) if request.form.get('hospital_id') else None, request.form.get('qualification','').strip(), int(request.form.get('experience_years') or 0), request.form.get('contact','').strip()))
            db().commit(); flash('Catalogue record saved.', 'success')
        except (ValueError, KeyError, sqlite3.IntegrityError, pymysql.err.IntegrityError):
            db().rollback(); flash('Could not save this record. Check required fields and unique email/name.', 'error')
        return redirect(url_for('admin_catalog'))
    specialties = query('SELECT * FROM specialties ORDER BY name').fetchall()
    hospitals = query('SELECT * FROM hospitals ORDER BY name').fetchall()
    doctors = query('''SELECT u.*, s.name AS specialty, h.name AS hospital_name, dp.active FROM users u JOIN doctor_profiles dp ON dp.user_id=u.id LEFT JOIN specialties s ON s.id=dp.specialty_id LEFT JOIN hospitals h ON h.id=dp.hospital_id WHERE u.role='doctor' ORDER BY u.full_name''').fetchall()
    service_rows = query('''SELECT hs.hospital_id, s.name FROM hospital_specialties hs JOIN specialties s ON s.id=hs.specialty_id ORDER BY s.name''').fetchall()
    hospital_services = {}
    for row in service_rows:
        hospital_services.setdefault(row['hospital_id'], []).append(row['name'])
    specialty_usage = {row['id']: {'hospitals': 0, 'doctors': 0, 'diseases': 0} for row in specialties}
    for row in query('SELECT specialty_id, COUNT(*) AS total FROM hospital_specialties GROUP BY specialty_id').fetchall(): specialty_usage[row['specialty_id']]['hospitals'] = row['total']
    for row in query('SELECT specialty_id, COUNT(*) AS total FROM doctor_profiles GROUP BY specialty_id').fetchall():
        if row['specialty_id'] in specialty_usage: specialty_usage[row['specialty_id']]['doctors'] = row['total']
    for row in query('SELECT specialty_id, COUNT(*) AS total FROM disease_specialties GROUP BY specialty_id').fetchall(): specialty_usage[row['specialty_id']]['diseases'] = row['total']
    return render_template('admin_catalog.html', specialties=specialties, hospitals=hospitals, doctors=doctors, hospital_services=hospital_services, specialty_usage=specialty_usage)

@app.route('/admin/specialty/<int:specialty_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def admin_edit_specialty(specialty_id):
    specialty = query('SELECT * FROM specialties WHERE id=?', (specialty_id,)).fetchone()
    if not specialty: abort(404)
    if request.method == 'POST':
        query('UPDATE specialties SET name=?,department=? WHERE id=?', (request.form['name'].strip(), request.form.get('department','').strip(), specialty_id))
        db().commit(); flash('Medical field updated.', 'success'); return redirect(url_for('admin_catalog'))
    return render_template('edit_specialty.html', specialty=specialty)

@app.route('/admin/hospital/<int:hospital_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def admin_edit_hospital(hospital_id):
    hospital = query('SELECT * FROM hospitals WHERE id=?', (hospital_id,)).fetchone()
    if not hospital: abort(404)
    specialties = query('SELECT * FROM specialties WHERE active=1 ORDER BY name').fetchall()
    selected = {row['specialty_id'] for row in query('SELECT specialty_id FROM hospital_specialties WHERE hospital_id=?', (hospital_id,)).fetchall()}
    if request.method == 'POST':
        values = tuple(request.form.get(key, '').strip() for key in ('name','province','district','city','address','hospital_type','contact','map_url')) + (hospital_id,)
        query('UPDATE hospitals SET name=?,province=?,district=?,city=?,address=?,hospital_type=?,contact=?,map_url=? WHERE id=?', values)
        query('DELETE FROM hospital_specialties WHERE hospital_id=?', (hospital_id,))
        for specialty_id in request.form.getlist('specialty_ids'):
            insert_ignore('INSERT INTO hospital_specialties (hospital_id,specialty_id) VALUES (?,?)', (hospital_id, int(specialty_id)))
        db().commit(); flash('Hospital details updated.', 'success'); return redirect(url_for('admin_catalog'))
    return render_template('edit_hospital.html', hospital=hospital, specialties=specialties, selected=selected)

@app.route('/admin/doctor/<int:doctor_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def admin_edit_doctor(doctor_id):
    doctor = query('''SELECT u.*, dp.specialty_id,dp.hospital_id,dp.qualification,dp.experience_years,dp.contact
                      FROM users u JOIN doctor_profiles dp ON dp.user_id=u.id WHERE u.id=? AND u.role='doctor' ''', (doctor_id,)).fetchone()
    if not doctor: abort(404)
    specialties = query('SELECT * FROM specialties WHERE active=1 ORDER BY name').fetchall()
    hospitals = query('SELECT * FROM hospitals WHERE active=1 ORDER BY name').fetchall()
    if request.method == 'POST':
        query('UPDATE users SET full_name=?,email=? WHERE id=?', (request.form['name'].strip(), request.form['email'].strip().lower(), doctor_id))
        query('UPDATE doctor_profiles SET specialty_id=?,hospital_id=?,qualification=?,experience_years=?,contact=? WHERE user_id=?', (int(request.form['specialty_id']), int(request.form['hospital_id']) if request.form.get('hospital_id') else None, request.form.get('qualification','').strip(), int(request.form.get('experience_years') or 0), request.form.get('contact','').strip(), doctor_id))
        db().commit(); flash('Doctor details updated.', 'success'); return redirect(url_for('admin_catalog'))
    return render_template('edit_doctor.html', doctor=doctor, specialties=specialties, hospitals=hospitals)

@app.route('/hospital/<int:hospital_id>/map')
def hospital_map(hospital_id):
    hospital = query('SELECT name,city,address,map_url FROM hospitals WHERE id=? AND active=1', (hospital_id,)).fetchone()
    if not hospital: abort(404)
    if hospital['map_url']:
        return redirect(hospital['map_url'])
    location = ' '.join(part for part in (hospital['name'], hospital['address'], hospital['city'], 'Nepal') if part)
    return redirect('https://www.google.com/maps/search/?api=1&query=' + quote_plus(location))

@app.route('/admin/toggle/<string:kind>/<int:record_id>', methods=['POST'])
@role_required('admin')
def admin_toggle(kind, record_id):
    allowed = {'hospital': ('hospitals', 'id'), 'doctor': ('doctor_profiles', 'user_id'), 'specialty': ('specialties', 'id')}
    if kind not in allowed: abort(404)
    table, column = allowed[kind]
    query(f'UPDATE {table} SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE {column}=?', (record_id,)); db().commit()
    flash(f'{kind.title()} status updated.', 'success')
    return redirect(url_for('admin_catalog'))

@app.route('/admin/delete/<string:kind>/<int:record_id>', methods=['POST'])
@role_required('admin')
def admin_delete(kind, record_id):
    if kind == 'doctor':
        query('DELETE FROM doctor_profiles WHERE user_id=?', (record_id,))
        query("DELETE FROM users WHERE id=? AND role='doctor'", (record_id,))
    elif kind == 'hospital':
        query('UPDATE doctor_profiles SET hospital_id=NULL WHERE hospital_id=?', (record_id,))
        query('DELETE FROM hospital_specialties WHERE hospital_id=?', (record_id,))
        query('DELETE FROM hospitals WHERE id=?', (record_id,))
    elif kind == 'specialty':
        query('UPDATE doctor_profiles SET specialty_id=NULL WHERE specialty_id=?', (record_id,))
        query('DELETE FROM hospital_specialties WHERE specialty_id=?', (record_id,))
        query('DELETE FROM disease_specialties WHERE specialty_id=?', (record_id,))
        query('DELETE FROM specialties WHERE id=?', (record_id,))
    else:
        abort(404)
    db().commit(); flash(f'{kind.title()} deleted permanently.', 'success')
    return redirect(url_for('admin_catalog'))

with app.app_context():
    initialize_db()

if __name__ == '__main__':
    # Keep debug disabled by default; set FLASK_DEBUG=true in .env only while developing.
    # macOS Control Center commonly reserves port 5000, so this project uses 5050 by default.
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '5050')), debug=os.getenv('FLASK_DEBUG', '').lower() == 'true')
