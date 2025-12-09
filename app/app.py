from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
import itsdangerous
import json, time
import pandas as pd
import urllib.parse
from pathlib import Path
import os
import conf as c

# TODO update requirements.txt for Docling
# TODO resolve inconsistency does not work
# TODO test multiple users editing
# TODO revise how images are added:
## when modifying the text there is no match with the md and the image does not appear anymore in edit document

middleware = [
    Middleware(SessionMiddleware, secret_key="CHANGE_ME_SECRET")
]
app = FastAPI(middleware=middleware)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = Path("../docling/documents")

VALID_USERS = {
    "marilena.daquino2@unibo.it": "admin"
}

SECRET = "CHANGE_THIS_REMEMBER_SECRET"
serializer = itsdangerous.URLSafeTimedSerializer(SECRET)
#app.add_middleware(SessionMiddleware, secret_key="CHANGE_ME_SECRET")

# stats
url_pages_to_be_parsed = f'https://docs.google.com/spreadsheets/d/{c.metadata_spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(c.sheet_name)}'
df_pages = pd.read_csv(url_pages_to_be_parsed)
total_documents = df_pages["item_id"].nunique()
transcribed_documents = sum(1 for p in DATA_DIR.iterdir() if p.is_dir())
document_id = None
show_chunks = None
project_stats = {
    "project_name": c.project_name,
    "total_documents": total_documents,
    "transcribed_documents": transcribed_documents,
    "reviewed_documents": 0,
    "document_id": document_id, # to populate document pages
    "chunks": show_chunks,
}

STATUS_FILE = Path("reviewed_status.csv")

def load_reviewed_status():
    if not STATUS_FILE.exists() or STATUS_FILE.stat().st_size == 0:
        return {}
    try:
        df = pd.read_csv(STATUS_FILE)
        if df.empty:
            return {}
        return {str(row["document_id"]): row["status"] for _, row in df.iterrows()}
    except Exception:
        return {}

def save_reviewed_status(status_dict):
    if not status_dict:
        # Write an EMPTY but valid CSV
        pd.DataFrame(columns=["document_id", "status"]).to_csv(STATUS_FILE, index=False)
        return

    df = pd.DataFrame([
        {"document_id": k, "status": v}
        for k, v in status_dict.items()
    ])
    df.to_csv(STATUS_FILE, index=False)

# Load saved statuses
reviewed_status = load_reviewed_status()

documents_stats = {}
for p in DATA_DIR.iterdir():
    if p.is_dir():
        document_name = p.name
        chunks_file =  p / 'chunks.csv'
        if os.path.exists(chunks_file):
            chunks_df = pd.read_csv(chunks_file)
            chunks = len(chunks_df)
            expected_chunks = None if chunks_df.empty else chunks_df.iloc[-1]["num"]
            issues_file =  p / 'inconsistencies.csv'
            if issues_file.exists() and issues_file.stat().st_size > 0:
                try:
                    issues = len(pd.read_csv(issues_file))
                except pd.errors.EmptyDataError:
                    issues = 0
            else:
                issues = 0
            issues_percent = round((issues / chunks * 100)) if chunks else 0
            documents_stats[document_name] = {"chunks": chunks, "expected_chunks":expected_chunks, "issues": issues, "issues_percent":issues_percent, "status": "to be revised"}
        else:
            documents_stats[document_name] = {"chunks": 0,  "expected_chunks":0, "issues": 0, "issues_percent":0, "status": "to be transcribed"}

# Update document status
for doc_id, stat in reviewed_status.items():
    if doc_id in documents_stats:
        documents_stats[doc_id]["status"] = stat

# Compute reviewed_documents count
project_stats["reviewed_documents"] = sum(
    1 for d in documents_stats.values() if d["status"] == "reviewed"
)

LOCK_TIMEOUT = 60 * 30  # 30 minutes

def lock_path(catalogue_id):
    return DATA_DIR / catalogue_id / ".lock"


def acquire_lock(catalogue_id, user):
    if not catalogue_id:
        raise ValueError("catalogue_id is missing")

    lp = lock_path(catalogue_id)

    # Ensure parent directory exists
    lp.parent.mkdir(parents=True, exist_ok=True)

    # If no lock exists → create it
    if not lp.exists():
        with open(lp, "w") as f:
            json.dump({"user": user, "timestamp": time.time()}, f)
        return True, user

    # Load existing lock
    with open(lp) as f:
        data = json.load(f)

    lock_user = data["user"]
    lock_time = data["timestamp"]

    # Expired → take it over
    if time.time() - lock_time > LOCK_TIMEOUT:
        with open(lp, "w") as f:
            json.dump({"user": user, "timestamp": time.time()}, f)
        return True, user

    # Already owned by this user → refresh
    if lock_user == user:
        with open(lp, "w") as f:
            json.dump({"user": user, "timestamp": time.time()}, f)
        return True, user

    # Locked by someone else
    return False, lock_user


def release_lock(catalogue_id, user):
    lp = lock_path(catalogue_id)
    if lp.exists():
        try:
            with open(lp) as f:
                owner = json.load(f).get("user")
            if owner == user:
                lp.unlink()
        except:
            pass


def require_login(request: Request):
    """
    Robust authentication check:
    1. If session contains user → authenticated
    2. Else if remember_token cookie exists → validate and restore session
    3. Else → redirect to login
    """
    # 1. Session already valid
    if "user" in request.session:
        return request.session["user"]

    # 2. Try remember_token cookie
    token = request.cookies.get("remember_token")
    if token:
        try:
            email = serializer.loads(token, max_age=60*60*24*30)  # valid for 30 days
            if email in VALID_USERS:
                request.session["user"] = email
                return email
        except Exception:
            pass  # token invalid or expired → fall through to login redirect

    # 3. Not authenticated → redirect properly
    raise HTTPException(
        status_code=303,
        headers={"Location": "/login"}
    )


def get_image(chunks_df, catalogue_id):

    md_dir = DATA_DIR / catalogue_id   # directory with your .md files
    df = chunks_df

    # Read all markdown files into memory once
    markdown_files = {
        md_file.name: md_file.read_text(encoding="utf-8", errors="ignore")
        for md_file in md_dir.glob("*.md")
        if md_file.name != "all.md"
    }

    # Helper: find first markdown file containing the text
    def find_markdown_file(text):
        text_clean = str(text).strip()
        for fname, content in markdown_files.items():
            if text_clean in content:
                page_uri = c.iiif_page_uri_base + catalogue_id + '!' + urllib.parse.quote(fname[:-3]) + '/full/max/0/default.jpg'
                print(page_uri)
                return page_uri
        return None

    # Add column to dataframe
    df["image_online"] = df["text"].apply(find_markdown_file)

    # Save updated CSV
    #df.to_csv("chunks_with_images.csv", index=False)
    return df



@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    remember: str = Form(None)
):
    if email in VALID_USERS and VALID_USERS[email] == password:
        request.session["user"] = email

        # If "Remember me" checked → create persistent signed cookie
        if remember:
            token = serializer.dumps(email)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                "remember_token",
                token,
                max_age=60 * 60 * 24 * 30,  # 30 days
                httponly=True,
                secure=False,  # set True in production
                samesite="lax",
            )
            return response

        # Normal login
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid credentials"}
    )

@app.get("/logout")
def logout(request: Request, user: str = Depends(require_login)):
    # release all locks owned by this user
    for p in DATA_DIR.iterdir():
        if p.is_dir():
            release_lock(p.name, user)

    request.session.clear()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("remember_token")
    return response


@app.post("/heartbeat/{catalogue_id}")
async def heartbeat(catalogue_id: str, user: str = Depends(require_login)):
    """
    Refresh lock timestamp every few minutes while the user is editing.
    """
    lp = lock_path(catalogue_id)

    if not lp.exists():
        # Lock disappeared: recreate it for the current user
        with open(lp, "w") as f:
            json.dump({"user": user, "timestamp": time.time()}, f)
        return {"status": "recreated"}

    try:
        with open(lp) as f:
            data = json.load(f)
        if data.get("user") == user:
            # Refresh timestamp
            with open(lp, "w") as f:
                json.dump({"user": user, "timestamp": time.time()}, f)
            return {"status": "refreshed"}
        else:
            # Another user has taken the lock
            return {"status": "locked_by_other", "owner": data.get("user")}

    except Exception:
        return {"status": "error"}


@app.post("/release_lock/{catalogue_id}")
async def api_release_lock(catalogue_id: str, user: str = Depends(require_login)):
    release_lock(catalogue_id, user)
    return {"status": "released"}


@app.get("/")
def home(request: Request, sort: str = "id", order: str = "asc", user: str = Depends(require_login)):
    """Show overview of catalogues and issue counts."""
    project_stats["document_id"] , project_stats["chunks"] = None , None
    reverse = order == "desc"

    if sort == "issues":
        sorted_docs = dict(sorted(documents_stats.items(), key=lambda x: x[1]["issues"], reverse=reverse))
    elif sort == "chunks":
        sorted_docs = dict(sorted(documents_stats.items(), key=lambda x: x[1]["chunks"], reverse=reverse))
    elif sort == "status":
        sorted_docs = dict(sorted(documents_stats.items(), key=lambda x: x[1]["status"], reverse=reverse))
    else:  # default: sort by ID
        sorted_docs = dict(sorted(documents_stats.items(), key=lambda x: x[0], reverse=reverse))

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "projects": project_stats,
            "documents": sorted_docs,
            "sort": sort,
            "order": order
        },
    )



@app.get("/document/{catalogue_id}")
def view_document(request: Request, catalogue_id: str, user: str = Depends(require_login)):
    """Show editable chunks for a single catalogue."""
    if not catalogue_id or catalogue_id == "undefined":
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Invalid catalogue_id: {catalogue_id!r}."},
        )

    ok, locked_by = acquire_lock(catalogue_id, user)

    if not ok:
        return templates.TemplateResponse(
            "locked.html",
            {"request": request, "catalogue_id": catalogue_id, "locked_by": locked_by},
        )

    chunks_file = DATA_DIR / catalogue_id / 'chunks.csv'
    issues_file = DATA_DIR / catalogue_id / 'inconsistencies.csv'
    chunks_df = pd.read_csv(chunks_file)
    chunks_df = get_image(chunks_df, catalogue_id)

    if issues_file.exists() and issues_file.stat().st_size > 0:
        try:
            incons_df = pd.read_csv(issues_file)
        except pd.errors.EmptyDataError:
            incons_df = pd.DataFrame()
    else:
        incons_df = pd.DataFrame()

    def clean_str(s):
        return str(s).strip() if pd.notna(s) else ""

    # recast types
    for df in [chunks_df, incons_df]:
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).map(clean_str)

    if chunks_df.empty:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"No data found for document {catalogue_id}."},
        )

    # --- Build matching keys ---
    chunks_df["key"] = (
        chunks_df["catalogue_id"].astype(str)
        + "||"
        + chunks_df["num"].astype(str)
        + "||"
        + chunks_df["text"].astype(str)
    )

    if not incons_df.empty:
        incons_df["key"] = (
            incons_df["catalogue_id"].astype(str)
            + "||"
            + incons_df["current_num"].astype(str)
            + "||"
            + incons_df["excerpt"].astype(str)
        )

        # --- Compute revision flags ---
        chunks_df["needs_revision"] = chunks_df["key"].isin(incons_df["key"])
    else:
        chunks_df["needs_revision"] = False

    # Add anchor IDs for TOC
    # chunks_df["anchor_id"] = [
    #     f"chunk-{i}" for i in chunks_df["index"].astype(str)
    # ]
    chunks_df["anchor_id"] = chunks_df.index.map(lambda i: f"chunk_{i+1}")
    chunks_df["needs_revision"] = chunks_df["needs_revision"].astype(bool)


    # update sidebar
    project_stats["document_id"] = catalogue_id
    project_stats["chunks"] = chunks_df.to_dict(orient="records")



    return templates.TemplateResponse(
        "document.html",
        {
            "request": request,
            "projects": project_stats,
            "catalogue_id": catalogue_id,
            "chunks": chunks_df.to_dict(orient="records"),
        },
    )


@app.post("/save_document")
async def save_catalogue(request: Request, user: str = Depends(require_login)):
    form = await request.form()

    catalogue_id = form.get("catalogue_id")
    anchor = form.get("anchor") or ""

    nums = form.getlist("num[]")
    titles = form.getlist("title[]")
    texts = form.getlist("text[]")

    updated = []
    for idx, (num, title, text) in enumerate(zip(nums, titles, texts), start=1):
        updated.append({
            "catalogue_id": catalogue_id,
            "index": idx,
            "num": num.strip(),
            "title": title.strip(),
            "text": text.strip(),
        })

    chunks_file = DATA_DIR / catalogue_id / "chunks.csv"
    pd.DataFrame(updated).to_csv(chunks_file, index=False, encoding="utf-8")

    release_lock(catalogue_id, user)

    # redirect to the scrolling anchor
    return RedirectResponse(
        f"/document/{catalogue_id}#{anchor}",
        status_code=303
    )


@app.post("/resolve_inconsistency")
async def resolve_inconsistency(catalogue_id: str = Form(...), num: str = Form(...), user: str = Depends(require_login)):
    """Remove inconsistency entry from CSV when user resolves it."""

    issues_file = DATA_DIR / catalogue_id / 'inconsistencies.csv'

    if not issues_file.exists() or issues_file.stat().st_size == 0:
        return JSONResponse({"success": False, "error": "No inconsistencies file."})

    incons_df = pd.read_csv(issues_file)

    before = len(incons_df)
    incons_df = incons_df[
        ~((incons_df["catalogue_id"] == catalogue_id) &
          (incons_df["prev_num"].astype(str) == str(num)))
    ]
    after = len(incons_df)

    incons_df.to_csv(issues_file, index=False, encoding="utf-8")  # fixed typo: INCONS_FILE → issues_file

    resolved = before != after
    return JSONResponse({"success": resolved})

@app.post("/mark_reviewed")
def mark_reviewed(
    document_id: str = Form(...),
    user: str = Depends(require_login)
):
    if document_id in documents_stats:
        documents_stats[document_id]["status"] = "reviewed"

    reviewed_status[document_id] = "reviewed"
    save_reviewed_status(reviewed_status)

    # Update project stats
    project_stats["reviewed_documents"] = sum(
        1 for d in documents_stats.values() if d["status"] == "reviewed"
    )

    return RedirectResponse("/", status_code=303)


@app.post("/undo_review")
def undo_review(
    document_id: str = Form(...),
    user: str = Depends(require_login)
):
    if document_id in documents_stats:
        # Restore default behavior
        documents_stats[document_id]["status"] = (
            "to be revised" if documents_stats[document_id]["chunks"] > 0
            else "to be transcribed"
        )

    if document_id in reviewed_status:
        del reviewed_status[document_id]
        save_reviewed_status(reviewed_status)

    # Update project stats
    project_stats["reviewed_documents"] = sum(
        1 for d in documents_stats.values() if d["status"] == "reviewed"
    )

    return RedirectResponse("/", status_code=303)
