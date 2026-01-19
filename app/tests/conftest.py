import sys, os
from pathlib import Path

# Add parent folder to Python path
ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
os.environ["PYTEST_RUNNING"] = "1"

import pytest
import sqlite3
from fastapi.testclient import TestClient
import app  # now this works


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    def get_test_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(app, "DB_PATH", db_path)
    monkeypatch.setattr(app, "get_db", get_test_db)

    app.init_db()
    return db_path


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "documents"
    data_dir.mkdir()

    monkeypatch.setattr(app, "DATA_DIR", data_dir)
    return data_dir


@pytest.fixture
def client(temp_db, temp_data_dir):
    client = TestClient(app.app)

    response = client.post(
        "/login",
        data={"email": "marilena.daquino2@unibo.it", "password": "admin"},
        follow_redirects=False,
    )


    assert response.status_code == 303
    return client
