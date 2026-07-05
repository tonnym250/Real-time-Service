# Smart Waiter — Recommendation ML

This project includes a Random Forest-based demand prediction pipeline.

Quick start (local):

1. Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Start the backend API server:

```bash
python api_server.py
```

3. Bootstrap train the model using historical Firebase `requests` data:

```bash
python scripts\bootstrap_train_client.py http://localhost:5001 10
```

This calls the `/bootstrap_train` endpoint which:
- reads `/requests` from Firebase
- aggregates per-table stats using the same heuristic as the frontend
- labels each table with the heuristic (low/occasional/recurring)
- trains and saves a Random Forest model to `backend/demand_model.joblib`

4. The recommendation page will POST `stats_by_table` to `/predict_demand` and use backend predictions when available.

Notes:
- For meaningful models, ensure your Firebase `requests` history has sufficient data and variety.
- You can retrain by POSTing labeled records to `/train_demand_model` (JSON: `{ "records": [ ... ] }`).
