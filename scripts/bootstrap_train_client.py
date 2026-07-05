import requests
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5001'
# Default minimum labeled records changed from 10 to 3 for a 3-table setup
MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 3

resp = requests.post(f'{BASE}/bootstrap_train', json={'min_records': MIN}, timeout=30)
print(resp.status_code)
print(resp.text)
