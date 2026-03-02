import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "documents.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # safer concurrent access
    return conn


def fetch_reviewed_catalogues(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id
        FROM catalogues
        WHERE reviewed = 1
    """)
    return [r["id"] for r in cur.fetchall()]


def fetch_chunks(conn, catalogue_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT chunk_index, num, title, text, image_online
        FROM chunks
        WHERE catalogue_id = ?
        ORDER BY chunk_index
    """, (catalogue_id,))
    return [dict(row) for row in cur.fetchall()]


def process_catalogue(catalogue_id, chunks):
    print(f"Processing {catalogue_id} ({len(chunks)} chunks)")

    # Example aggregation
    full_text = "\n".join(chunk["text"] for chunk in chunks)

    # 🔥 Put your real processing logic here
    # NLP, export, JSON generation, ML, etc.

    # Example output
    output_path = BASE_DIR / "exports" / f"{catalogue_id}.txt"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(full_text, encoding="utf-8")


def main():
    conn = get_db()

    catalogues = fetch_reviewed_catalogues(conn)

    if not catalogues:
        print("No reviewed catalogues.")
        return

    for catalogue_id in catalogues:
        chunks = fetch_chunks(conn, catalogue_id)
        process_catalogue(catalogue_id, chunks)

    conn.close()


if __name__ == "__main__":
    main()
