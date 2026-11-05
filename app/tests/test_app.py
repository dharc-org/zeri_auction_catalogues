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


def _save(client, **extra):
    data = {
        "catalogue_id": "doc1",
        "num[]": ["1"],
        "title[]": ["T"],
        "text[]": ["Hello"],
        "image_online[]": ["img1.jpg"],
        **extra,
    }
    return client.post("/save_document", data=data, follow_redirects=False)


def test_save_redirects_to_anchor(client, temp_db):
    seed_catalogue(temp_db)
    r = _save(client, anchor="chunk_1")
    assert r.status_code == 303
    assert r.headers["location"].endswith("/document/doc1#chunk_1")


def test_save_without_anchor_has_no_fragment(client, temp_db):
    seed_catalogue(temp_db)
    r = _save(client)
    assert "#" not in r.headers["location"]


def test_save_rejects_bad_anchor(client, temp_db):
    seed_catalogue(temp_db)
    r = _save(client, anchor="x\r\nSet-Cookie: a=b")
    assert "#" not in r.headers["location"]
    assert "Set-Cookie" not in r.headers["location"]


def test_title_is_textarea_and_multiline_saved(client, temp_db):
    seed_catalogue(temp_db)
    page = client.get("/document/doc1").text
    assert '<textarea name="title[]"' in page
    assert 'input type="text" name="title[]"' not in page

    _save(client, **{"title[]": ["very long\ntitle"]})
    conn = sqlite3.connect(temp_db)
    assert conn.execute("SELECT title FROM chunks").fetchone()[0] == "very long\ntitle"


def test_zoom_script_keeps_view(client, temp_db):
    seed_catalogue(temp_db)
    page = client.get("/document/doc1").text
    assert "DEFAULT_ZOOM = 1.5" in page
    assert 'localStorage.getItem("translateX")' in page
    # setImage must not reset zoom/pan any more
    body = page.split("function setImage(src)")[1].split("}\n")[0]
    assert "zoomLevel = 1" not in body and "translateX = 0" not in body
