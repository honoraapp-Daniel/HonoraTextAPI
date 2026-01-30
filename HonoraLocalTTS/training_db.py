"""
Training Database Layer
SQLite storage for training runs metadata
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "training.db")


def init_db():
    """Initialize the database schema"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_runs (
                id TEXT PRIMARY KEY,
                voice_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                config TEXT,
                dataset_path TEXT,
                output_path TEXT,
                started_at TEXT,
                ended_at TEXT,
                progress_step INTEGER DEFAULT 0,
                progress_total INTEGER DEFAULT 0,
                current_epoch INTEGER DEFAULT 0,
                total_epochs INTEGER DEFAULT 0,
                current_loss REAL,
                exit_code INTEGER,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


@contextmanager
def get_connection():
    """Context manager for database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_run(run_id: str, voice_name: str, config: dict, dataset_path: str, output_path: str) -> dict:
    """Create a new training run"""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO training_runs (id, voice_name, status, config, dataset_path, output_path, created_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?)
        """, (run_id, voice_name, json.dumps(config), dataset_path, output_path, datetime.utcnow().isoformat()))
        conn.commit()
    return get_run(run_id)


def get_run(run_id: str) -> dict:
    """Get a training run by ID"""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM training_runs WHERE id = ?", (run_id,)).fetchone()
        if row:
            return dict(row)
    return None


def get_all_runs() -> list:
    """Get all training runs ordered by creation date"""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM training_runs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def update_run(run_id: str, **kwargs) -> dict:
    """Update a training run"""
    allowed_fields = [
        'status', 'started_at', 'ended_at', 'progress_step', 'progress_total',
        'current_epoch', 'total_epochs', 'current_loss', 'exit_code', 'error'
    ]
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    
    if not updates:
        return get_run(run_id)
    
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [run_id]
    
    with get_connection() as conn:
        conn.execute(f"UPDATE training_runs SET {set_clause} WHERE id = ?", values)
        conn.commit()
    
    return get_run(run_id)


def delete_run(run_id: str):
    """Delete a training run"""
    with get_connection() as conn:
        conn.execute("DELETE FROM training_runs WHERE id = ?", (run_id,))
        conn.commit()


# Initialize database on import
init_db()
