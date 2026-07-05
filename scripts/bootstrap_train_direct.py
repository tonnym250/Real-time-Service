from pathlib import Path
import datetime
import os

# Ensure backend package path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from demand_model import make_record, train_model

# Initialize firebase admin locally like the server
import firebase_admin
from firebase_admin import credentials, db

SERVICE_ACCOUNT = os.path.join(os.path.dirname(__file__), '..', 'backend', 'serviceAccountKey.json')
FIREBASE_DB_URL = os.getenv('FIREBASE_DATABASE_URL', 'https://smartwaiter-c9a2e-default-rtdb.firebaseio.com')

if not firebase_admin._apps:
    cred = credentials.Certificate(SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DB_URL})

ref = db.reference('requests')
raw = ref.get() or {}

stats_by_table = {}
now = datetime.datetime.utcnow()

for key, event in (raw.items() if isinstance(raw, dict) else []):
    try:
        if not event or event.get('event_type') != 'requested':
            continue
        table_id = event.get('table_id')
        ts = event.get('timestamp') or event.get('iso_time') or event.get('time')
        if not ts:
            continue
        try:
            event_time = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            event_time = now
        hour = event_time.hour
        weekday = event_time.strftime('%A')
        age_hours = (now - event_time).total_seconds() / 3600.0

        s = stats_by_table.setdefault(table_id, {
            'totalRequests': 0,
            'recent24': 0,
            'days': set(),
            'hourCounts': {},
            'dayCounts': {},
            'recentHoursPeak': 0,
        })
        s['totalRequests'] += 1
        s['days'].add(weekday)
        s['hourCounts'][hour] = s['hourCounts'].get(hour, 0) + 1
        s['dayCounts'][weekday] = s['dayCounts'].get(weekday, 0) + 1
        if age_hours <= 24:
            s['recent24'] = s.get('recent24', 0) + 1
        s['recentHoursPeak'] = max(s['recentHoursPeak'], s['hourCounts'][hour])
    except Exception as e:
        print('error processing event', e)


# Build labeled records using heuristic
records = []
for table_id, s in stats_by_table.items():
    s_copy = dict(s)
    s_copy['days'] = set(s_copy.get('days', []))
    # heuristic label
    total = s_copy.get('totalRequests', 0)
    unique_days = len(s_copy.get('days', []))
    recent24 = s_copy.get('recent24', 0)
    recentHoursPeak = s_copy.get('recentHoursPeak', 0)
    if total >= 8 or unique_days >= 4 or recentHoursPeak >= 3:
        label = 'recurring'
    elif total >= 3 or unique_days >= 2 or recent24 >= 2:
        label = 'occasional'
    else:
        label = 'low'
    rec = make_record(table_id, s_copy)
    rec['label'] = label
    records.append(rec)

print('Found', len(records), 'tables with requests')
if len(records) < 1:
    print('No data to train')
    raise SystemExit(1)

# If we have too few records, augment with simple synthetic variants
# Reduced augmentation target from 10 to 3 samples to match a 3-table setup
if len(records) < 3:
    print('Augmenting records to reach 3 samples')
    aug = []
    i = 0
    while len(records) + len(aug) < 3:
        src = records[i % len(records)]
        copy = dict(src)
        # tweak numeric features slightly
        copy['hour'] = (copy.get('hour', 0) + (i % 3) - 1) % 24
        copy['total_requests'] = max(0, copy.get('total_requests', 0) + ((i % 2) * 1))
        copy['recent_24h'] = max(0, copy.get('recent_24h', 0) + (i % 2))
        copy['unique_days'] = max(1, copy.get('unique_days', 1) + (i % 2))
        aug.append(copy)
        i += 1
    records.extend(aug)

res = train_model(records, save=True)
print('Training finished:', res)
print('Model saved to backend/demand_model.joblib')
