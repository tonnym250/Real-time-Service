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


def label_from_demand_type(demand_type: str) -> str:
    if demand_type not in TARGET_LABELS:
        raise ValueError(f'Invalid demand label: {demand_type}')
    return demand_type
