import sqlite3
import app


def seed_catalogue(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("INSERT INTO catalogues (id) VALUES ('doc1')")
    cur.execute("""
        INSERT INTO chunks
        (catalogue_id, chunk_index, num, title, text, image_online)
        VALUES ('doc1', 1, '1', 'T', 'Hello', 'img1.jpg')
    """)
    conn.commit()
    conn.close()


def test_init_db_creates_tables(temp_db):
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}

    assert "catalogues" in tables
    assert "chunks" in tables
    assert "inconsistencies" in tables


def test_home_requires_login(temp_db, temp_data_dir):
    from fastapi.testclient import TestClient
    client = TestClient(app.app)

    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_home_logged_in(client):
    r = client.get("/")
    assert r.status_code == 200


def test_view_document(client, temp_db):
    seed_catalogue(temp_db)

    r = client.get("/document/doc1")
    assert r.status_code == 200
    assert "Hello" in r.text
    assert "img1.jpg" in r.text


def test_save_document_updates_chunk(client, temp_db):
    seed_catalogue(temp_db)

    r = client.post(
        "/save_document",
        data={
            "catalogue_id": "doc1",
            "num[]": ["1"],
            "title[]": ["New"],
            "text[]": ["Updated"],
            "image_online[]": ["img2.jpg"],
        },
        follow_redirects=False,
    )

    assert r.status_code == 303

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM chunks")
    row = cur.fetchone()

    assert row["text"] == "Updated"
    assert row["image_online"] == "img2.jpg"


def test_acquire_and_release_lock(temp_data_dir):
    ok, user = app.acquire_lock("doc1", "u1")
    assert ok

    ok2, owner = app.acquire_lock("doc1", "u2")
    assert not ok2
    assert owner == "u1"

    app.release_lock("doc1", "u1")
    ok3, _ = app.acquire_lock("doc1", "u2")
    assert ok3
