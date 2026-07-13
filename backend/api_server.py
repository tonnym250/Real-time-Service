from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db
import datetime
import json
import os
import requests
from threading import Thread
import time

# Import the demand model module with fallbacks so the server can be
# started both as a package (`python -m backend.api_server`) and
# as a script from the `backend` directory (`python api_server.py`).
try:
    from backend.demand_model import make_record, predict, train_model, classify_demand_from_stats
    from backend.busy_period import calculate_busy_baseline, predict_busy_period, describe_busy_period
except Exception:
    # fallback to local import when running from backend/ directly
    from demand_model import make_record, predict, train_model, classify_demand_from_stats
    from busy_period import calculate_busy_baseline, predict_busy_period, describe_busy_period

app = Flask(__name__)
CORS(app)

# Serve static HTML pages
@app.route('/<path:filename>')
def serve_page(filename):
    """Serve HTML pages from the pages directory."""
    pages_dir = os.path.join(os.path.dirname(__file__), '..', 'pages')
    filepath = os.path.join(pages_dir, filename)
    
    if os.path.exists(filepath) and filepath.endswith('.html'):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        response = app.response_class(content, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response, 200
    return 'Not found', 404

# Firebase configuration
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://smartwaiter-c9a2e-default-rtdb.firebaseio.com")
AUTO_RETRAIN_STATE_PATH = os.path.join(os.path.dirname(__file__), '.auto_retrain_state.json')

# Initialize Firebase with service account key
try:
    if not firebase_admin._apps:
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH") or os.path.join(os.path.dirname(__file__), 'serviceAccountKey.json')
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
    print("Firebase initialized successfully")
except Exception as e:
    print(f"Firebase initialization error: {e}")
    print("Make sure serviceAccountKey.json is present or set FIREBASE_SERVICE_ACCOUNT_PATH")

def load_telegram_config():
    """Load Telegram credentials from environment variables or a local config file."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID")

    if not bot_token or not chat_id:
        config_path = os.path.join(os.path.dirname(__file__), "telegram_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as handle:
                    config = json.load(handle) or {}
                bot_token = bot_token or config.get("bot_token")
                chat_id = chat_id or config.get("chat_id")
            except Exception as e:
                print(f"Telegram config file error: {e}")

    return bot_token, chat_id


TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = load_telegram_config()


def send_telegram_message(message):
    """Send a message to Telegram if configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram is disabled: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Telegram API error: {response.status_code} {response.text}")
            return False
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def dispatch_background_notification(message):
    """Send Telegram notifications asynchronously so the API responds faster."""
    try:
        thread = Thread(target=send_telegram_message, args=(message,), daemon=True)
        thread.start()
        return True
    except Exception as e:
        print(f"Notification dispatch error: {e}")
        return False

def is_cleanup_enabled():
    """Return whether request cleanup is explicitly enabled."""
    value = os.getenv("ENABLE_REQUEST_CLEANUP", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def should_auto_retrain(total_requests: int, last_trained_total: int, threshold: int = 100) -> bool:
    """Return whether the model should retrain based on new request volume."""
    if threshold <= 0:
        return False
    return max(0, total_requests - last_trained_total) >= threshold


def load_auto_retrain_state() -> dict:
    """Load persisted metadata for the auto-retraining threshold tracker."""
    if not os.path.exists(AUTO_RETRAIN_STATE_PATH):
        return {'last_trained_total': 0}
    try:
        with open(AUTO_RETRAIN_STATE_PATH, 'r', encoding='utf-8') as handle:
            return json.load(handle) or {'last_trained_total': 0}
    except Exception:
        return {'last_trained_total': 0}


def save_auto_retrain_state(last_trained_total: int) -> None:
    """Persist the latest request count used for the last successful retraining."""
    with open(AUTO_RETRAIN_STATE_PATH, 'w', encoding='utf-8') as handle:
        json.dump({'last_trained_total': int(last_trained_total)}, handle)


def get_last_trained_total() -> int:
    """Return the last request count used for a successful retraining."""
    return int(load_auto_retrain_state().get('last_trained_total', 0))


def maybe_auto_retrain(total_requests: int, last_trained_total: int, threshold: int = 100):
    """Auto-retrain if enough new requests have accumulated since the last training."""
    if not should_auto_retrain(total_requests, last_trained_total, threshold):
        return {'triggered': False, 'reason': 'threshold_not_reached'}

    try:
        ref = db.reference('requests')
        raw = ref.get() or {}
        stats_by_table = {}
        now = datetime.datetime.utcnow()

        for key, event in raw.items():
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
                    event_time = datetime.datetime.utcnow()

                hour = event_time.hour
                weekday = event_time.strftime('%A')

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
                s['recentHoursPeak'] = max(s['recentHoursPeak'], s['hourCounts'][hour])
            except Exception as e:
                print('auto-retrain error processing event', e)

        records = []
        for table_id, s in stats_by_table.items():
            s_copy = dict(s)
            s_copy['days'] = set(s_copy.get('days', []))
            label = _classify_table_demand(s_copy)
            rec = make_record(table_id, s_copy)
            rec['label'] = label
            records.append(rec)

        if len(records) < 3:
            return {'triggered': False, 'reason': 'not_enough_records'}

        result = train_model(records, save=True)
        save_auto_retrain_state(total_requests)
        return {'triggered': True, 'trained_records': len(records), 'accuracy': result.get('accuracy')}
    except Exception as e:
        print('auto-retrain error', e)
        return {'triggered': False, 'reason': str(e)}


def cleanup_old_requests(max_age_minutes=10):
    """Optionally mark old pending requests as expired.

    Cleanup is disabled by default so Firebase request history remains intact.
    Set ENABLE_REQUEST_CLEANUP=true to enable expiration handling.
    """
    if not is_cleanup_enabled():
        return {'cleaned': 0, 'message': 'Cleanup disabled; request history preserved'}

    try:
        ref = db.reference('requests')
        snapshot = ref.get()

        # firebase_admin returns plain Python types from ref.get()
        if not snapshot or not isinstance(snapshot, dict):
            return {'cleaned': 0, 'message': 'No requests to clean'}

        requests_data = snapshot
        now = datetime.datetime.now()
        cleaned_count = 0

        for key, event in requests_data.items():
            if not event or event.get('event_type') != 'requested':
                continue

            timestamp_str = event.get('timestamp') or event.get('iso_time')
            if not timestamp_str:
                continue

            try:
                event_time = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                age_minutes = (now - event_time).total_seconds() / 60

                if age_minutes > max_age_minutes:
                    # Mark as expired instead of deleting to keep history
                    ref.child(key).update({
                        'event_type': 'expired',
                        'cleaned_at': now.isoformat()
                    })
                    cleaned_count += 1
                    print(f"Marked request {key} as expired (age: {age_minutes:.1f}min)")
            except Exception as e:
                print(f"Error processing request {key}: {e}")

        message = f"Cleanup complete: marked {cleaned_count} old requests as expired"
        print(message)
        return {'cleaned': cleaned_count, 'message': message}

    except Exception as e:
        print(f"Cleanup error: {e}")
        return {'cleaned': 0, 'error': str(e)}


@app.route('/arduino_button', methods=['POST'])
def arduino_button():
    """Receive button press events from ESP32 and write to Firebase"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        table_id = data.get('table_id')
        event_type = data.get('event_type')
        
        if not table_id or not event_type:
            return jsonify({'error': 'Missing table_id or event_type'}), 400
        
        print(f"Received: {table_id} - {event_type}")
        
        # Get current timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Write to Firebase /requests
        ref = db.reference('requests')
        if event_type == 'served':
            snapshot = ref.get()
            if snapshot and isinstance(snapshot, dict):
                pending_keys = []
                for key, item in snapshot.items():
                    if not item:
                        continue
                    if str(item.get('table_id')) != str(table_id):
                        continue
                    if str(item.get('event_type', '')).lower() != 'requested':
                        continue
                    pending_keys.append(key)

                for key in pending_keys:
                    ref.child(key).update({
                        'event_type': 'served',
                        'timestamp': timestamp,
                        'iso_time': timestamp,
                        'served_at': timestamp
                    })

        new_entry = ref.push()
        new_entry.set({
            'table_id': table_id,
            'event_type': event_type,
            'timestamp': timestamp,
            'iso_time': timestamp
        })
        
        # Also update /tables for current state
        table_ref = db.reference(f'tables/{table_id}')
        table_ref.update({
            'status': event_type,
            'last_event': event_type,
            'updated_at': timestamp
        })
        
        print(f"Written to Firebase: {new_entry.key}")

        # Auto-retrain when enough new requests have accumulated since the last training.
        try:
            threshold = int(os.getenv("AUTO_RETRAIN_THRESHOLD", "100"))
            last_trained_total = get_last_trained_total()
            snapshot = ref.get() or {}
            total_requests = sum(1 for event in snapshot.values() if event and event.get('event_type') == 'requested')
            if should_auto_retrain(total_requests, last_trained_total, threshold):
                result = maybe_auto_retrain(total_requests, last_trained_total, threshold)
                if result.get('triggered'):
                    print('Auto retraining triggered after threshold reached')
        except Exception as e:
            print(f'Auto retraining check failed: {e}')
        
        # Send Telegram notification asynchronously to avoid delaying the response
        table_label = table_id.replace('_', ' ').title()
        time_str = datetime.datetime.now().strftime('%H:%M:%S')
        if event_type == 'requested':
            message = f"🔔 <b>Table Request</b>\n{table_label} needs service!\n<i>{time_str}</i>"
        else:
            message = f"✅ <b>Order Served</b>\n{table_label} has been served.\n<i>{time_str}</i>"
        
        dispatch_background_notification(message)
        
        return jsonify({
            'success': True,
            'message': 'Event logged to Firebase',
            'firebase_key': new_entry.key
        }), 200
        
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'service': 'smart-waiter-api'}), 200


@app.route('/firebase_requests', methods=['GET'])
def firebase_requests():
    """Return request data from Firebase without requiring the browser SDK."""
    try:
        ref = db.reference('requests')
        data = ref.get() or {}
        return jsonify({'success': True, 'data': data}), 200
    except Exception as e:
        print(f'firebase_requests error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/test_telegram', methods=['GET'])
def test_telegram():
    """Send a test message to the configured Telegram chat."""
    time_str = datetime.datetime.now().strftime('%H:%M:%S')
    success = send_telegram_message(f"🧪 RTSD Test Notification\n<i>{time_str}</i>")
    if success:
        return jsonify({'success': True, 'message': 'Telegram test message sent'}), 200
    return jsonify({'success': False, 'message': 'Telegram not configured or sending failed'}), 400


@app.route('/train_demand_model', methods=['POST'])
def train_demand_model():
    """Train or retrain the Random Forest demand model with labeled records."""
    try:
        payload = request.get_json()
        if not payload or 'records' not in payload:
            return jsonify({'error': 'Missing records in request body'}), 400

        result = train_model(payload['records'], save=True)
        return jsonify({'success': True, 'accuracy': result['accuracy'], 'model_path': result['model_path']}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _classify_table_demand(stats):
    """Use the same table-level heuristic as the recommendation UI."""
    return classify_demand_from_stats(stats)


@app.route('/bootstrap_train', methods=['POST', 'GET'])
def bootstrap_train():
    """Bootstrap training using heuristic labels derived from Firebase request history.
    GET: run bootstrap and train using current DB data
    POST: accepts optional JSON {"min_records": <int>} to require minimum records
    """
    try:
        params = request.get_json(silent=True) or {}
        min_records = int(params.get('min_records', 3))

        ref = db.reference('requests')
        raw = ref.get() or {}

        # aggregate stats per table
        stats_by_table = {}
        now = datetime.datetime.utcnow()

        for key, event in raw.items():
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
                    # fallback parse
                    event_time = datetime.datetime.utcnow()

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

        # Build labeled records
        records = []
        for table_id, s in stats_by_table.items():
            s_copy = dict(s)
            s_copy['days'] = set(s_copy.get('days', []))
            label = _classify_table_demand(s_copy)
            rec = make_record(table_id, s_copy)
            rec['label'] = label
            records.append(rec)

        if len(records) < min_records:
            return jsonify({'success': False, 'error': f'Not enough records to train ({len(records)}/{min_records}). Need at least {min_records} labeled examples.', 'records_found': len(records), 'records_needed': min_records}), 400

        try:
            result = train_model(records, save=True)
            return jsonify({'success': True, 'trained_records': len(records), 'accuracy': result.get('accuracy'), 'model_path': result.get('model_path')}), 200
        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve), 'records_found': len(records)}), 400
    except Exception as e:
        print('bootstrap_train error', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/predict_demand', methods=['POST'])
def predict_demand():
    """Predict table demand labels using the trained Random Forest model."""
    try:
        payload = request.get_json() or {}
        stats_by_table = payload.get('stats_by_table') or {}

        if not stats_by_table:
            # Fall back to the Firebase table registry when the client did not send stats.
            tables_ref = db.reference('tables')
            tables = tables_ref.get() or {}
            stats_by_table = {
                table_id: {
                    'totalRequests': 0,
                    'recent24': 0,
                    'days': set(),
                    'hourCounts': {},
                    'dayCounts': {},
                    'recentHoursPeak': 0
                }
                for table_id in tables.keys()
                if table_id != 'table_99'
            }

        records = []
        for table_id, stats in stats_by_table.items():
            if not table_id:
                continue
            record = make_record(table_id, stats)
            records.append(record)

        if not records:
            return jsonify({'success': True, 'predictions': {}}), 200

        predictions = predict(records)
        return jsonify({'success': True, 'predictions': dict(zip([r['table_id'] for r in records], predictions))}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/predict_busy_period', methods=['POST'])
def get_busy_period():
    """Predict if current hour/day will be busy based on historical patterns."""
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({'error': 'No JSON payload'}), 400

        # Get current hour and day
        now = datetime.datetime.now()
        current_hour = now.hour
        current_day = now.strftime('%A')

        # Read Firebase request history
        ref = db.reference('requests')
        raw = ref.get() or {}
        events = [v for v in raw.values() if v]

        # Calculate baseline from historical data
        baseline = calculate_busy_baseline(events)

        # Predict busy period for current time
        current_requests = payload.get('current_request_count', 0)
        baseline_key = f"{current_day}_{current_hour}"
        baseline_average = baseline.get(baseline_key)
        period = predict_busy_period(current_requests, current_hour, current_day, baseline)
        description = describe_busy_period(
            period,
            current_hour,
            current_day,
            current_requests=current_requests,
            baseline_average=baseline_average,
        )

        return jsonify({
            'success': True,
            'period': period,
            'description': description,
            'current_hour': current_hour,
            'current_day': current_day,
            'current_requests': current_requests,
            'baseline_average': baseline_average,
        }), 200
    except Exception as e:
        print(f'busy_period error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


def classify_wait_time(pending_requests: int, oldest_wait_minutes: float) -> str:
    """Classify the current service pace in a simple, friendly way."""
    if pending_requests <= 0:
        return 'low'
    if pending_requests >= 6 or oldest_wait_minutes >= 15:
        return 'high'
    if pending_requests >= 3 or oldest_wait_minutes >= 8:
        return 'medium'
    return 'low'


def format_wait_estimate(pending_requests: int, oldest_wait_minutes: float) -> str:
    """Format a professional wait-time estimate for the advisory card."""
    if pending_requests <= 0:
        return 'Under 3 minutes'

    estimate = pending_requests * 2.5 + max(0, oldest_wait_minutes - 6) * 0.5
    if estimate < 5:
        return 'Under 5 minutes'
    if estimate < 10:
        return '5–9 minutes'
    if estimate < 15:
        return '10–14 minutes'
    return '15+ minutes'


def describe_wait_time(level: str, pending_requests: int, oldest_wait_minutes: float) -> dict:
    """Generate a simple, friendly service update payload."""
    if pending_requests <= 0:
        return {
            'title': 'All good',
            'message': 'No tables are waiting right now. Everything looks calm and service is moving smoothly.',
            'estimate': 'Under 3 minutes',
            'badge': 'Smooth service'
        }

    estimated_wait = format_wait_estimate(pending_requests, oldest_wait_minutes)
    oldest_minutes = int(oldest_wait_minutes)
    oldest_text = f'{oldest_minutes} minute{"s" if oldest_minutes != 1 else ""}'

    if level == 'high':
        return {
            'title': 'Needs attention',
            'message': f'Some tables are still waiting, and the oldest request has been waiting about {oldest_text}. Please check in soon.',
            'estimate': estimated_wait,
            'badge': 'Please check in'
        }
    if level == 'medium':
        return {
            'title': 'Getting busy',
            'message': f'Some tables are waiting, and the oldest request has been waiting about {oldest_text}. A quick check would help.',
            'estimate': estimated_wait,
            'badge': 'Keep an eye on it'
        }
    return {
        'title': 'All good',
        'message': f'Some tables are waiting, but the oldest request has only been waiting about {oldest_text}. Service is still moving well.',
        'estimate': estimated_wait,
        'badge': 'Smooth service'
    }


@app.route('/recommend_wait_time', methods=['POST'])
def recommend_wait_time():
    """Provide a rule-based wait-time recommendation separate from demand modeling."""
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'success': False, 'error': 'Missing JSON payload'}), 400

        pending_requests = int(payload.get('pending_requests', payload.get('current_request_count', 0)))
        oldest_wait_minutes = float(payload.get('oldest_wait_minutes', payload.get('max_pending_age_minutes', 0)))

        level = classify_wait_time(pending_requests, oldest_wait_minutes)
        result = describe_wait_time(level, pending_requests, oldest_wait_minutes)

        return jsonify({
            'success': True,
            'level': level,
            'pending_requests': pending_requests,
            'oldest_wait_minutes': oldest_wait_minutes,
            'title': result['title'],
            'message': result['message'],
            'estimate': result['estimate'],
            'badge': result['badge']
        }), 200
    except Exception as e:
        print(f'recommend_wait_time error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/cleanup', methods=['POST', 'GET'])
def cleanup():
    """Manually trigger cleanup of old pending requests."""
    max_age = request.args.get('max_age_minutes', default=10, type=int)
    result = cleanup_old_requests(max_age)
    return jsonify(result), 200


@app.route('/clear_all_requests', methods=['POST'])
def clear_all_requests():
    """DANGER: Clear all requests from Firebase. Use with caution."""
    try:
        ref = db.reference('requests')
        ref.delete()
        message = "All requests cleared from Firebase"
        print(message)
        return jsonify({'success': True, 'message': message}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5001'))
    print("Starting Real Time Service Delivery System API Server...")
    print(f"Listening on 0.0.0.0:{port}")
    print(f"Endpoint: http://0.0.0.0:{port}/arduino_button")
    
    if is_cleanup_enabled():
        cleanup_old_requests(max_age_minutes=10)
        
        # Background cleanup thread (runs every 5 minutes)
        def background_cleanup():
            while True:
                time.sleep(5 * 60)  # 5 minutes
                cleanup_old_requests(max_age_minutes=10)
        
        cleanup_thread = Thread(target=background_cleanup, daemon=True)
        cleanup_thread.start()
    else:
        print("Request cleanup disabled; old requests will remain in Firebase.")
    
    app.run(host='0.0.0.0', port=port, debug=False)
