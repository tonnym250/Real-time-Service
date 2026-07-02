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

app = Flask(__name__)
CORS(app)

# Firebase configuration
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://smartwaiter-c9a2e-default-rtdb.firebaseio.com")

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


def cleanup_old_requests(max_age_minutes=10):
    """Auto-cleanup old pending requests to prevent stale alerts.
    Marks requests older than max_age_minutes that are still 'requested' as 'expired'.
    """
    try:
        ref = db.reference('requests')
        snapshot = ref.get()
        
        if not snapshot or not isinstance(snapshot.val(), dict):
            return {'cleaned': 0, 'message': 'No requests to clean'}
        
        requests_data = snapshot.val()
        now = datetime.datetime.now()
        cleaned_count = 0
        
        for key, event in requests_data.items():
            if event.get('event_type') != 'requested':
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
        
        # Send Telegram notification
        table_label = table_id.replace('_', ' ').title()
        time_str = datetime.datetime.now().strftime('%H:%M:%S')
        if event_type == 'requested':
            message = f"🔔 <b>Table Request</b>\n{table_label} needs service!\n<i>{time_str}</i>"
        else:
            message = f"✅ <b>Order Served</b>\n{table_label} has been served.\n<i>{time_str}</i>"
        
        send_telegram_message(message)
        
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


@app.route('/test_telegram', methods=['GET'])
def test_telegram():
    """Send a test message to the configured Telegram chat."""
    time_str = datetime.datetime.now().strftime('%H:%M:%S')
    success = send_telegram_message(f"🧪 RTSD Test Notification\n<i>{time_str}</i>")
    if success:
        return jsonify({'success': True, 'message': 'Telegram test message sent'}), 200
    return jsonify({'success': False, 'message': 'Telegram not configured or sending failed'}), 400


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
    
    # Run initial cleanup
    cleanup_old_requests(max_age_minutes=10)
    
    # Background cleanup thread (runs every 5 minutes)
    def background_cleanup():
        while True:
            time.sleep(5 * 60)  # 5 minutes
            cleanup_old_requests(max_age_minutes=10)
    
    cleanup_thread = Thread(target=background_cleanup, daemon=True)
    cleanup_thread.start()
    
    app.run(host='0.0.0.0', port=port, debug=False)
