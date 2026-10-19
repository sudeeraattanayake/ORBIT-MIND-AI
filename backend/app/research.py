"""Public NASA media search and local, cited document retrieval."""
import io
import re
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pypdf import PdfReader

router = APIRouter(prefix="/api/research", tags=["NASA Research"])
DOCS = []  # in-memory documents, intentionally cleared on restart

@router.get("/nasa-images")
async def nasa_images(q: str = "Earth from space"):
    if not 2 <= len(q) <= 120:
        raise HTTPException(422, "Search must be 2–120 characters")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get("https://images-api.nasa.gov/search", params={"q": q, "media_type": "image", "page_size": 12})
            response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])
        return [{"nasa_id": x.get("data", [{}])[0].get("nasa_id", ""), "title": x.get("data", [{}])[0].get("title", ""), "description": x.get("data", [{}])[0].get("description", "")[:800], "image": next((y.get("href") for y in x.get("links", []) if y.get("render") == "image" and y.get("href", "").startswith("https://")), None), "source": "https://images.nasa.gov/details/" + x.get("data", [{}])[0].get("nasa_id", "")} for x in items if x.get("data")]
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"NASA image service unavailable: {type(exc).__name__}")

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    name = (file.filename or "document")[:120]
    if not name.lower().endswith((".txt", ".md", ".pdf")):
        raise HTTPException(400, "Only .txt, .md and .pdf are supported")
    data = await file.read(3_000_001)
    if len(data) > 3_000_000:
        raise HTTPException(413, "Maximum document size is 3 MB")
    try:
        if name.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages[:40])]
        else:
            pages = [(1, data.decode("utf-8"))]
    except Exception:
        raise HTTPException(400, "Could not extract document text")
    count = 0
    for page, content in pages:
        for start in range(0, len(content), 900):
            chunk = content[start:start+1100].strip()
            if len(chunk) > 30:
                DOCS.append({"source": name, "page": page, "text": chunk})
                count += 1
    if len(DOCS) > 2500:
        del DOCS[:-2500]
    if not count:
        raise HTTPException(422, "No extractable text; scanned PDFs need OCR")
    return {"filename": name, "chunks_added": count, "total_chunks": len(DOCS)}

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)

@router.post("/ask")
def ask(request: Question):
    if not DOCS:
        raise HTTPException(400, "Upload a research document first")
    corpus = [d["text"] for d in DOCS]
    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform(corpus + [request.question])
        scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    except ValueError:
        raise HTTPException(422, "Documents have insufficient searchable text")
    best = sorted(range(len(scores)), key=lambda i: -scores[i])[:3]
    sources = [{**DOCS[i], "score": round(float(scores[i]), 3)} for i in best if scores[i] > 0.025]
    if not sources:
        return {"answer": "No relevant passage found in the uploaded documents.", "sources": []}
    import os
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            context = "\n\n".join(f"[{i+1}] {s['source']} page {s['page']}: {s['text']}" for i,s in enumerate(sources))
            r = OpenAI(timeout=20).chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), messages=[{"role":"system","content":"Answer ONLY from the supplied excerpts. Cite excerpt numbers [1], [2], etc. If evidence is insufficient, say so. No invented claims."},{"role":"user","content":f"Question: {request.question}\nExcerpts:\n{context}"}], max_tokens=350)
            return {"answer": r.choices[0].message.content, "sources": sources}
        except Exception:
            pass
    return {"answer": "Relevant document excerpts below (extractive retrieval; configure OPENAI_API_KEY for a synthesized answer).", "sources": sources}

class VisionRequest(BaseModel):
    image_url: str
    question: str = "Describe visible geographic and atmospheric features, and limitations of this image."

@router.post("/vision")
def vision(request: VisionRequest):
    if not request.image_url.startswith("https://images-assets.nasa.gov/"):
        raise HTTPException(400, "Select a NASA image returned by the search API")
    import os
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(400, "Set OPENAI_API_KEY in backend/.env to enable vision")
    try:
        from openai import OpenAI
        response = OpenAI(timeout=30).chat.completions.create(model=os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"), messages=[{"role":"system","content":"Analyze visible image features cautiously. Do not infer precise coordinates, dates, spectral bands or scientific measurements from visual appearance. State uncertainty. NASA image library items may be photographs rather than calibrated satellite observations."},{"role":"user","content":[{"type":"text","text":request.question[:500]},{"type":"image_url","image_url":{"url":request.image_url,"detail":"low"}}]}], max_tokens=350)
        return {"analysis": response.choices[0].message.content, "note": "Qualitative visual description, not scientific remote sensing classification."}
    except Exception as exc:
        raise HTTPException(502, f"Vision analysis unavailable: {type(exc).__name__}")
