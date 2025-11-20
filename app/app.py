from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import pandas as pd
import urllib.parse
from pathlib import Path
import os
import conf as c

# TODO update requirements.txt also for Docling
# TODO calculate and store reviewed documents
# TODO add status to each document to be shown in homepag
# TODO resolve inconsistency does not work

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = Path("../docling/documents")

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
            issues_percent = round((issues / chunks * 100))
            documents_stats[document_name] = {"chunks": chunks, "expected_chunks":expected_chunks, "issues": issues, "issues_percent":issues_percent, "status": "to be revised"}
        else:
            documents_stats[document_name] = {"chunks": 0,  "expected_chunks":0, "issues": 0, "issues_percent":0, "status": "to be transcribed"}


@app.get("/")
def home(request: Request, sort: str = "id", order: str = "asc"):
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
def view_document(request: Request, catalogue_id: str):
    """Show editable chunks for a single catalogue."""

    chunks_file = DATA_DIR / catalogue_id / 'chunks.csv'
    issues_file = DATA_DIR / catalogue_id / 'inconsistencies.csv'
    chunks_df = pd.read_csv(chunks_file)
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
async def save_catalogue(request: Request):
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

    # redirect to the scrolling anchor
    return RedirectResponse(
        f"/document/{catalogue_id}#{anchor}",
        status_code=303
    )

@app.post("/resolve_inconsistency")
async def resolve_inconsistency(catalogue_id: str = Form(...), num: str = Form(...)):
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
