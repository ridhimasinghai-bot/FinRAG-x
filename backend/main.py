from typing import Optional

import pymupdf as fitz

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import current_user, login as do_login, signup as do_signup
from pipeline import add_document, answer_question

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCS = {}  # context_id -> {"name", "chunks", "owner"}  (in memory; cleared on restart)


class AskRequest(BaseModel):
    question: str
    mode: str = "dense"
    doc_id: Optional[str] = None


class Cred(BaseModel):
    email: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/signup")
def signup(c: Cred):
    return do_signup(c.email, c.password)


@app.post("/login")
def login(c: Cred):
    return do_login(c.email, c.password)


@app.get("/docs-list")
def docs_list(user: str = Depends(current_user)):
    return [{"id": k, **v} for k, v in DOCS.items() if v["owner"] == user]


@app.post("/upload")
def upload(file: UploadFile = File(...), user: str = Depends(current_user)):
    data = file.file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 15 MB.")
    name = file.filename or "document"
    if name.lower().endswith(".pdf"):
        pdf = fitz.open(stream=data, filetype="pdf")
        pages = [(i + 1, p.get_text()) for i, p in enumerate(pdf)]
    elif name.lower().endswith(".txt"):
        pages = [(1, data.decode("utf-8", errors="ignore"))]
    else:
        raise HTTPException(400, "Upload a .pdf or .txt file.")
    try:
        ctx, n = add_document(name, pages)
    except ValueError as e:
        raise HTTPException(422, str(e))
    DOCS[ctx] = {"name": name, "chunks": n, "owner": user}
    return {"id": ctx, "name": name, "chunks": n}


@app.post("/ask")
def ask(req: AskRequest, user: str = Depends(current_user)):
    only = None
    if req.doc_id:
        if req.doc_id not in DOCS or DOCS[req.doc_id]["owner"] != user:
            raise HTTPException(404, "That uploaded document is no longer loaded. Please upload it again.")
        only = {req.doc_id}
    try:
        return answer_question(req.question, req.mode, only_ids=only)
    except Exception as e:
        raise HTTPException(503, f"{type(e).__name__}: {str(e)[:300]}")
