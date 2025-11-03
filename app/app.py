from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import pandas as pd
from pathlib import Path

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DATA_DIR = Path("data")
CHUNKS_FILE = DATA_DIR / "all_chunks.csv"
INCONS_FILE = DATA_DIR / "all_inconsistencies.csv"

# --- Load data ---
chunks_df = pd.read_csv(CHUNKS_FILE)
incons_df = pd.read_csv(INCONS_FILE)

# --- Normalize text ---
def clean_str(s):
    return str(s).strip() if pd.notna(s) else ""

for df in [chunks_df, incons_df]:
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).map(clean_str)

# --- Build matching keys ---
chunks_df["key"] = (
    chunks_df["catalogue_id"].astype(str)
    + "||"
    + chunks_df["num"].astype(str)
    + "||"
    + chunks_df["text"].astype(str)
)

incons_df["key"] = (
    incons_df["catalogue_id"].astype(str)
    + "||"
    + incons_df["current_num"].astype(str)
    + "||"
    + incons_df["excerpt"].astype(str)
)

# --- Compute revision flags ---
chunks_df["needs_revision"] = chunks_df["key"].isin(incons_df["key"])

# --- Precompute catalogue stats ---
catalogue_stats = (
    chunks_df.groupby("catalogue_id")["needs_revision"]
    .agg(["sum", "count"])
    .reset_index()
    .rename(columns={"sum": "issues", "count": "total"})
)
catalogue_stats["issues"] = catalogue_stats["issues"].astype(int)
catalogue_stats["percent_issues"] = (catalogue_stats["issues"] / catalogue_stats["total"] * 100).round(1)


@app.get("/")
def home(request: Request):
    """Show overview of catalogues and issue counts."""
    return templates.TemplateResponse(
        "catalogues.html",
        {
            "request": request,
            "catalogues": catalogue_stats.to_dict(orient="records"),
        },
    )


@app.get("/catalogue/{catalogue_id}")
def view_catalogue(request: Request, catalogue_id: str):
    """Show editable chunks for a single catalogue."""
    catalogue_chunks = chunks_df[chunks_df["catalogue_id"] == catalogue_id].copy()

    if catalogue_chunks.empty:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"No data found for catalogue {catalogue_id}."},
        )
    # Add anchor IDs for TOC
    catalogue_chunks["anchor_id"] = [
        f"chunk-{i}" for i in catalogue_chunks["index"].astype(str)
    ]
    catalogue_chunks["needs_revision"] = catalogue_chunks["needs_revision"].astype(bool)

    return templates.TemplateResponse(
        "catalogue_detail.html",
        {
            "request": request,
            "catalogue_id": catalogue_id,
            "chunks": catalogue_chunks.to_dict(orient="records"),
        },
    )


@app.post("/update_chunk")
def update_chunk(
    catalogue_id: str = Form(...),
    index: int = Form(...),
    title: str = Form(...),
    text: str = Form(...),
):
    """Update a chunk and recompute inconsistencies."""
    global chunks_df

    mask = (chunks_df["catalogue_id"] == catalogue_id) & (chunks_df["index"] == index)
    if not mask.any():
        return RedirectResponse(url=f"/catalogue/{catalogue_id}", status_code=303)

    # Update values
    chunks_df.loc[mask, "title"] = title.strip()
    chunks_df.loc[mask, "text"] = text.strip()

    # Rebuild keys and recheck inconsistency status
    chunks_df["key"] = (
        chunks_df["catalogue_id"].astype(str)
        + "||"
        + chunks_df["num"].astype(str)
        + "||"
        + chunks_df["text"].astype(str)
    )
    chunks_df["needs_revision"] = chunks_df["key"].isin(incons_df["key"])

    # Save updated CSV
    chunks_df.to_csv(CHUNKS_FILE, index=False, encoding="utf-8")

    return RedirectResponse(url=f"/catalogue/{catalogue_id}", status_code=303)
