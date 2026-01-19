from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

import sqlite3
import pandas as pd
import itsdangerous
import json, time, os
from pathlib import Path
import conf as c
# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = Path("../docling/documents")
DB_PATH = BASE_DIR / "documents.db"

LOCK_TIMEOUT = 60 * 30
SECRET = "CHANGE_THIS_REMEMBER_SECRET"

VALID_USERS = {
    "marilena.daquino2@unibo.it": "admin"
}

serializer = itsdangerous.URLSafeTimedSerializer(SECRET)

# -----------------------------------------------------------------------------
# FASTAPI SETUP
# -----------------------------------------------------------------------------

middleware = [
    Middleware(SessionMiddleware, secret_key="CHANGE_ME_SECRET")
]

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not os.getenv("PYTEST_RUNNING"):
        ingest_new_catalogues()
    yield

app = FastAPI(middleware=middleware, lifespan=lifespan)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

def sort_url(request, column):
    current_sort = request.query_params.get("sort", "id")
    current_order = request.query_params.get("order", "asc")

    if current_sort == column:
        new_order = "desc" if current_order == "asc" else "asc"
    else:
        new_order = "asc"

    return f"/?sort={column}&order={new_order}"

templates.env.globals["sort_url"] = sort_url

def sort_arrow(sort, order, column):
    if sort != column:
        return ""
    return "↑" if order == "asc" else "↓"

templates.env.globals["sort_arrow"] = sort_arrow

# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS catalogues (
        id TEXT PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed INTEGER DEFAULT 0
    )
    """)

    # existing columns
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalogue_id TEXT,
        chunk_index INTEGER,
        num TEXT,
        title TEXT,
        text TEXT,
        original_text TEXT,
        edited INTEGER DEFAULT 0,
        updated_at TIMESTAMP,
        updated_by TEXT,
        FOREIGN KEY (catalogue_id) REFERENCES catalogues(id)
    )
    """)

    # add image_online column if it doesn't exist
    cur.execute("PRAGMA table_info(chunks)")
    columns = [col["name"] for col in cur.fetchall()]
    if "image_online" not in columns:
        cur.execute("ALTER TABLE chunks ADD COLUMN image_online TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inconsistencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalogue_id TEXT,
        num TEXT,
        excerpt TEXT,
        resolved INTEGER DEFAULT 0,
        FOREIGN KEY (catalogue_id) REFERENCES catalogues(id)
    )
    """)
    conn.commit()
    conn.close()


def ingest_new_catalogues():
    conn = get_db()
    cur = conn.cursor()

    for p in DATA_DIR.iterdir():
        if not p.is_dir():
            continue

        catalogue_id = p.name
        original_csv = p / "chunks_original.csv"
        incoming_csv = p / "chunks.csv"

        # already ingested?
        cur.execute("SELECT 1 FROM catalogues WHERE id = ?", (catalogue_id,))
        if cur.fetchone():
            continue

        # archive csv
        if incoming_csv.exists() and not original_csv.exists():
            incoming_csv.rename(original_csv)

        if not original_csv.exists():
            continue

        df = pd.read_csv(original_csv)

        cur.execute(
            "INSERT INTO catalogues (id) VALUES (?)",
            (catalogue_id,)
        )

        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO chunks
                (catalogue_id, chunk_index, num, title, text, original_text, image_online)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                catalogue_id,
                int(row["index"]),
                str(row["num"]),
                str(row.get("title", "")),
                str(row["text"]),
                str(row["text"]),
                str(row.get("image_online", ""))
            ))

        # issues
        issues_csv = p / "inconsistencies.csv"
        if issues_csv.exists() and issues_csv.stat().st_size > 0:
            try:
                df_issues = pd.read_csv(issues_csv)
            except pd.errors.EmptyDataError:
                df_issues = pd.DataFrame()

            for _, row in df_issues.iterrows():
                cur.execute("""
                    INSERT INTO inconsistencies
                    (catalogue_id, num, excerpt)
                    VALUES (?, ?, ?)
                """, (
                    catalogue_id,
                    str(row.get("prev_num") or row.get("current_num") or ""),
                    str(row.get("excerpt", "")),
                ))

    conn.commit()
    conn.close()

# -----------------------------------------------------------------------------
# LOCKING WHILE SOMEONE EDITS A DOCUMENT
# -----------------------------------------------------------------------------

def require_login(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def lock_path(catalogue_id):
    return DATA_DIR / catalogue_id / ".lock"


def acquire_lock(catalogue_id, user):
    lp = lock_path(catalogue_id)
    lp.parent.mkdir(exist_ok=True, parents=True)

    if not lp.exists():
        lp.write_text(json.dumps({"user": user, "ts": time.time()}))
        return True, user

    data = json.loads(lp.read_text())
    if time.time() - data["ts"] > LOCK_TIMEOUT or data["user"] == user:
        lp.write_text(json.dumps({"user": user, "ts": time.time()}))
        return True, user

    return False, data["user"]

@app.post("/heartbeat/{catalogue_id}")
async def heartbeat(catalogue_id: str, user: str = Depends(require_login)):
    """ Refresh lock timestamp every few minutes while the user is editing. """
    lp = lock_path(catalogue_id)
    if not lp.exists():
        # Lock disappeared: recreate it for the current user
        with open(lp, "w") as f:
            json.dump({"user": user, "ts": time.time()}, f)
        return {"status": "recreated"}
    try:
        with open(lp) as f:
            data = json.load(f)
        if data.get("user") == user:
            # Refresh timestamp
            with open(lp, "w") as f:
                json.dump({"user": user, "ts": time.time()}, f)
            return {"status": "refreshed"}
        else:
            # Another user has taken the lock
            return {"status": "locked_by_other", "owner": data.get("user")}
    except Exception:
        return {"status": "error"}


def release_lock(catalogue_id, user):
    lp = lock_path(catalogue_id)
    if lp.exists():
        data = json.loads(lp.read_text())
        if data.get("user") == user:
            lp.unlink()

# -----------------------------------------------------------------------------
# AUTH
# -----------------------------------------------------------------------------

def require_login(request: Request):
    if "user" in request.session:
        return request.session["user"]

    token = request.cookies.get("remember_token")
    if token:
        try:
            email = serializer.loads(token, max_age=60 * 60 * 24 * 30)
            if email in VALID_USERS:
                request.session["user"] = email
                return email
        except Exception:
            pass

    raise HTTPException(status_code=303, headers={"Location": "/login"})


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request,"login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    remember: str = Form(None)
):
    if VALID_USERS.get(email) == password:
        request.session["user"] = email
        response = RedirectResponse("/", status_code=303)
        if remember:
            response.set_cookie(
                "remember_token",
                serializer.dumps(email),
                max_age=60 * 60 * 24 * 30,
                httponly=True,
            )
        return response

    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": "Invalid credentials"}
    )

@app.get("/logout")
def logout(request: Request, user: str = Depends(require_login)):
    for p in DATA_DIR.iterdir():
        if p.is_dir():
            release_lock(p.name, user)
    request.session.clear()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("remember_token")
    return response

# -----------------------------------------------------------------------------
# HOME
# -----------------------------------------------------------------------------

def fetch_documents_stats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            c.id AS catalogue_id,
            COUNT(DISTINCT ch.id) AS chunks,
            COUNT(DISTINCT i.id) AS issues,
            c.reviewed
        FROM catalogues c
        LEFT JOIN chunks ch
            ON ch.catalogue_id = c.id
        LEFT JOIN inconsistencies i
            ON i.catalogue_id = c.id AND i.resolved = 0
        GROUP BY c.id
    """)

    docs = {}
    for r in cur.fetchall():
        chunks = r["chunks"]
        issues = r["issues"]

        status = "reviewed" if r["reviewed"] else (
            "to be revised" if chunks > 0 else "to be transcribed"
        )

        docs[r["catalogue_id"]] = {
            "chunks": chunks,
            "expected_chunks": None,
            "issues": issues,
            "issues_percent": round((issues / chunks) * 100) if chunks else 0,
            "status": status,
        }

    conn.close()
    return docs

def build_project_stats(documents_stats):
    total_documents = len(documents_stats)
    transcribed_documents = sum(
        1 for d in documents_stats.values() if d["chunks"] > 0
    )
    reviewed_documents = sum(
        1 for d in documents_stats.values() if d["status"] == "reviewed"
    )

    return {
        "project_name": c.project_name,
        "total_documents": total_documents,
        "transcribed_documents": transcribed_documents,
        "reviewed_documents": reviewed_documents,
        "document_id": None,
        "chunks": None,
    }

@app.get("/")
def home(
    request: Request,
    sort: str = "id",
    order: str = "asc",
    user: str = Depends(require_login)
):
    documents_stats = fetch_documents_stats()
    project_stats = build_project_stats(documents_stats)

    reverse = order == "desc"

    if sort == "issues":
        sorted_docs = dict(
            sorted(
                documents_stats.items(),
                key=lambda x: x[1]["issues"],
                reverse=reverse
            )
        )
    elif sort == "chunks":
        sorted_docs = dict(
            sorted(
                documents_stats.items(),
                key=lambda x: x[1]["chunks"],
                reverse=reverse
            )
        )
    elif sort == "status":
        sorted_docs = dict(
            sorted(
                documents_stats.items(),
                key=lambda x: x[1]["status"],
                reverse=reverse
            )
        )
    else:  # id
        sorted_docs = dict(
            sorted(
                documents_stats.items(),
                key=lambda x: x[0],
                reverse=reverse
            )
        )


    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "projects": project_stats,
            "documents": sorted_docs,
            "sort": sort,
            "order": order,
        }
    )


# -----------------------------------------------------------------------------
# DOCUMENT VIEW
# -----------------------------------------------------------------------------
def fetch_unresolved_inconsistencies(catalogue_id: str):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT num
        FROM inconsistencies
        WHERE catalogue_id = ? AND resolved = 0
    """, (catalogue_id,))

    nums = {r["num"] for r in cur.fetchall()}
    conn.close()
    return nums

@app.get("/document/{catalogue_id}")
def view_document(
    request: Request,
    catalogue_id: str,
    user: str = Depends(require_login)
):
    ok, locked_by = acquire_lock(catalogue_id, user)
    if not ok:
        return templates.TemplateResponse(
            request,
            "locked.html",
            {
                "request": request,
                "catalogue_id": catalogue_id,
                "locked_by": locked_by
            },
        )

    conn = get_db()
    cur = conn.cursor()

    # fetch chunks
    cur.execute("""
        SELECT id, chunk_index, num, title, text, image_online
        FROM chunks
        WHERE catalogue_id = ?
        ORDER BY chunk_index
    """, (catalogue_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "message": f"No chunks found for {catalogue_id}"
            },
        )

    # unresolved inconsistencies
    inconsistent_nums = fetch_unresolved_inconsistencies(catalogue_id)

    # build chunks for main content + sidebar
    chunks = []
    sidebar_chunks = []

    for i, r in enumerate(rows, start=1):
        anchor_id = f"chunk_{i}"
        needs_revision = str(r["num"]) in inconsistent_nums

        chunk = {
            "id": r["id"],
            "num": r["num"],
            "title": r["title"],
            "text": r["text"],
            "anchor_id": anchor_id,
            "needs_revision": needs_revision,
            "image_online": r["image_online"] or "",
        }

        chunks.append(chunk)

        sidebar_chunks.append({
            "num": r["num"],
            "anchor_id": anchor_id,
            "needs_revision": needs_revision,
        })

    # rebuild project_stats for sidebar
    project_stats = {
        "project_name": c.project_name,
        "document_id": catalogue_id,
        "chunks": sidebar_chunks,
    }

    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "request": request,
            "catalogue_id": catalogue_id,
            "chunks": chunks,
            "projects": project_stats,
        },
    )


# -----------------------------------------------------------------------------
# SAVE DOCUMENT
# -----------------------------------------------------------------------------

@app.post("/save_document")
async def save_document(request: Request, user: str = Depends(require_login)):
    """
    Save the edited chunks for a catalogue.

    - Updates existing chunks including image_online
    - Inserts new chunks
    - Deletes chunks removed from the interface
    - Reindexes all chunks correctly
    """
    form = await request.form()
    catalogue_id = form.get("catalogue_id")
    nums = form.getlist("num[]")
    titles = form.getlist("title[]")
    texts = form.getlist("text[]")
    image_paths = form.getlist("image_online[]")  # new hidden inputs in your template

    conn = get_db()
    cur = conn.cursor()

    # Fetch current chunks from DB
    cur.execute("SELECT id, chunk_index FROM chunks WHERE catalogue_id = ?", (catalogue_id,))
    db_chunks = cur.fetchall()
    db_ids_by_index = {r["chunk_index"]: r["id"] for r in db_chunks}

    processed_db_ids = set()

    for idx, (num, title, text, image_online) in enumerate(zip(nums, titles, texts, image_paths), start=1):
        if idx in db_ids_by_index:
            # Update existing chunk
            chunk_id = db_ids_by_index[idx]
            cur.execute("""
                UPDATE chunks
                SET num = ?, title = ?, text = ?, image_online = ?,
                    edited = 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ?
            """, (
                num.strip(),
                title.strip(),
                text.strip(),
                image_online.strip(),
                user,
                chunk_id
            ))
            processed_db_ids.add(chunk_id)
        else:
            # Insert new chunk
            cur.execute("""
                INSERT INTO chunks
                (catalogue_id, chunk_index, num, title, text, original_text, image_online, edited, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
            """, (
                catalogue_id,
                idx,
                num.strip(),
                title.strip(),
                text.strip(),
                text.strip(),
                image_online.strip(),
                user
            ))

    # Delete chunks removed in the interface
    for r in db_chunks:
        if r["id"] not in processed_db_ids:
            cur.execute("DELETE FROM chunks WHERE id = ?", (r["id"],))

    conn.commit()
    conn.close()

    # Release lock after saving
    release_lock(catalogue_id, user)

    return RedirectResponse(f"/document/{catalogue_id}", status_code=303)


# -----------------------------------------------------------------------------
# REVIEW STATUS
# -----------------------------------------------------------------------------

@app.post("/mark_reviewed")
def mark_reviewed(document_id: str = Form(...), user: str = Depends(require_login)):
    conn = get_db()
    conn.execute(
        "UPDATE catalogues SET reviewed = 1 WHERE id = ?",
        (document_id,)
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/undo_review")
def undo_review(document_id: str = Form(...), user: str = Depends(require_login)):
    conn = get_db()
    conn.execute(
        "UPDATE catalogues SET reviewed = 0 WHERE id = ?",
        (document_id,)
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/", status_code=303)


# -----------------------------------------------------------------------------
# INCONSISTENCIES
# -----------------------------------------------------------------------------

@app.post("/resolve_inconsistency")
async def resolve_inconsistency(
    catalogue_id: str = Form(...),
    num: str = Form(...),
    user: str = Depends(require_login)
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE inconsistencies
        SET resolved = 1
        WHERE catalogue_id = ? AND num = ?
    """, (catalogue_id, num))

    conn.commit()
    resolved = cur.rowcount > 0
    conn.close()

    return JSONResponse({"success": resolved})
