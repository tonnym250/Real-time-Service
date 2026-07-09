import json
import os
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score
import joblib

MODEL_PATH = Path(__file__).with_name('demand_model.joblib')

FEATURE_COLUMNS = [
    'hour',
    'weekday',
    'total_requests',
    'recent_24h',
    'unique_days',
    'peak_hour_count'
]

CATEGORICAL_COLUMNS = ['weekday']
NUMERIC_COLUMNS = ['hour', 'total_requests', 'recent_24h', 'unique_days', 'peak_hour_count']

TARGET_LABELS = ['low', 'occasional', 'recurring']


def build_pipeline() -> Pipeline:
    numeric_transformer = 'passthrough'
    categorical_transformer = OneHotEncoder(handle_unknown='ignore')

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', numeric_transformer, NUMERIC_COLUMNS),
            ('cat', categorical_transformer, CATEGORICAL_COLUMNS),
        ],
        remainder='drop'
    )

    pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('classifier', RandomForestClassifier(n_estimators=100, random_state=42))
    ])

    return pipeline


def _validate_record(record: Dict[str, Any]) -> bool:
    return all(key in record for key in FEATURE_COLUMNS)


def train_model(records: List[Dict[str, Any]], save: bool = True) -> Dict[str, Any]:
    if len(records) < 3:
        raise ValueError('At least 3 labeled records are required for training')

    data = [
        {key: record[key] for key in FEATURE_COLUMNS} for record in records if _validate_record(record)
    ]
    labels = [record['label'] for record in records if _validate_record(record)]

    if len(data) != len(labels):
        raise ValueError('Feature and label counts do not match')

    # Use DataFrame so ColumnTransformer can select columns by name
    X = pd.DataFrame(data)[FEATURE_COLUMNS]
    y = pd.Series(labels)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    predictions = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)

    if save:
        joblib.dump(pipeline, MODEL_PATH)

    return {
        'accuracy': float(accuracy),
        'model_path': str(MODEL_PATH)
    }


def load_model() -> Pipeline:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f'Model file not found at {MODEL_PATH}')
    return joblib.load(MODEL_PATH)


def predict(records: List[Dict[str, Any]]) -> List[str]:
    model = load_model()
    X = pd.DataFrame([{key: row.get(key) for key in FEATURE_COLUMNS} for row in records])[FEATURE_COLUMNS]
    return model.predict(X).tolist()


def make_record(table_id: str, stats: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'table_id': table_id,
        'hour': int(stats.get('topHour', 0) or 0),
        'weekday': stats.get('topDay', 'Monday'),
        'total_requests': int(stats.get('totalRequests', 0)),
        'recent_24h': int(stats.get('recent24', 0)),
        'unique_days': int(len(stats.get('days', set()))),
        'peak_hour_count': int(stats.get('recentHoursPeak', 0)),
    }


def classify_demand_from_stats(stats: Dict[str, Any]) -> str:
    """Classify a table's demand pattern from aggregated request stats.

    This mirrors the frontend heuristic and avoids overusing the model for simple
    table-level summaries. It also keeps low-volume tables from being labelled the
    same as high-volume tables just because they share the same hour/day context.
    """
    total_requests = int(stats.get('totalRequests', 0) or 0)
    recent_24h = int(stats.get('recent24', 0) or 0)
    days = stats.get('days', [])
    unique_days = len(days) if isinstance(days, (list, set)) else int(days or 0)
    peak_hour_count = int(stats.get('recentHoursPeak', 0) or 0)

    if total_requests >= 20 or unique_days >= 5 or peak_hour_count >= 5:
        return 'recurring'
    if total_requests >= 10 or unique_days >= 3 or recent_24h >= 4:
        return 'occasional'
    return 'low'


def label_from_demand_type(demand_type: str) -> str:
    if demand_type not in TARGET_LABELS:
        raise ValueError(f'Invalid demand label: {demand_type}')
    return demand_type


def describe_demand_pattern(demand_type: str, stats: Dict[str, Any], table_name: str) -> str:
    """Convert the model's demand label into a short, user-friendly message."""
    normalized_type = (demand_type or '').strip().lower()
    peak_day = stats.get('topDay') or 'the week'
    hour = int(stats.get('topHour', 0) or 0)

    if normalized_type == 'recurring':
        if 11 <= hour < 15:
            return f"{table_name} is busy on {peak_day} around lunch and may need extra attention."
        if 17 <= hour < 21:
            return f"{table_name} is busy on {peak_day} around the evening rush and may need a quick check-in."
        return f"{table_name} shows repeated demand on {peak_day} and may benefit from proactive support."

    if normalized_type == 'occasional':
        return f"{table_name} has moderate demand and is worth monitoring on {peak_day} during busy periods."

    return f"{table_name} is quiet right now and usually stays calm after service."
