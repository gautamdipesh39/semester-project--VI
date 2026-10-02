from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def normalise(value):
    return str(value).strip().lower().replace(' ', '_').replace('-', '_')

def find_sources():
    yield from (ROOT / 'data' / 'raw').glob('*.csv')
    yield from (ROOT / 'Dataset').glob('*.xlsx')

def load_source(path):
    try:
        df = pd.read_csv(path) if path.suffix == '.csv' else pd.read_excel(path)
    except Exception as exc:
        print(f'Skipped {path.name}: {exc}')
        return []
    df.columns = [normalise(c) for c in df.columns]
    target = next((c for c in ('disease', 'prognosis', 'diagnosis') if c in df.columns), None)
    if not target:
        return []
    symptom_cols = [c for c in df.columns if c.startswith('symptom')]
    # Some datasets use one 0/1 column per symptom rather than symptom_1... columns.
    # Keep only binary columns and exclude identifiers/demographics.
    if not symptom_cols:
        excluded = {'patient_id', 'age', 'gender', target}
        symptom_cols = [c for c in df.columns if c not in excluded and set(df[c].dropna().unique()).issubset({0, 1, True, False})]
    records = []
    for _, row in df.iterrows():
        disease = row.get(target)
        if pd.isna(disease):
            continue
        symptoms = []
        for c in symptom_cols:
            value = row.get(c)
            if pd.notna(value) and str(value).strip() not in ('', '0', 'nan', 'false'):
                # For 0/1 datasets, the column name is the symptom; otherwise use its value.
                symptoms.append(c if value in (1, True) else normalise(value))
        if symptoms:
            records.append({'disease': str(disease).strip(), 'symptoms': '|'.join(sorted(set(symptoms)))})
    return records

records = []
for source in find_sources():
    records.extend(load_source(source))
if not records:
    raise SystemExit('No usable training rows found. Add a CSV with disease/prognosis and symptom_1... columns.')
cleaned = pd.DataFrame(records).drop_duplicates().dropna()
out = ROOT / 'data' / 'cleaned' / 'disease_training.csv'
out.parent.mkdir(parents=True, exist_ok=True)
cleaned.to_csv(out, index=False)
print(f'Wrote {len(cleaned)} cleaned rows to {out}')
