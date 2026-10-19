"""Planetary image identification: vision model when configured; metadata-only fallback.
Not a scientifically validated classifier. Do not use for flight or research decisions.
"""
import base64
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/classification", tags=["Planet identification"])
CLASSES = ["Earth", "Mars", "Moon", "Jupiter", "Saturn", "Venus", "Mercury", "Neptune", "Uranus", "Sun", "Other", "Unknown"]
MAX_IMAGE = 8 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp"}

class NasaImage(BaseModel):
    image_url: str = Field(max_length=1500)
    nasa_id: str = Field(min_length=1, max_length=160)
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=2500)


def metadata_guess(title: str, description: str):
    """Only classify from explicit title; otherwise abstain. No model confidence."""
    title = title.lower()
    found = [x for x in CLASSES[:10] if re.search(r"\b" + re.escape(x.lower()) + r"\b", title)]
    return found[0] if len(found) == 1 else "Unknown"


def parse_model_answer(raw):
    try:
        value = json.loads(raw)
        label = str(value.get("label", "Unknown"))
        if label not in CLASSES: label = "Unknown"
        confidence = str(value.get("confidence", "uncertain")).lower()
        if confidence not in {"low", "medium", "high", "uncertain"}: confidence = "uncertain"
        return {"label": label, "confidence": confidence, "reason": str(value.get("reason", ""))[:900], "visible_features": [str(x)[:160] for x in value.get("visible_features", [])[:5]]}
    except (ValueError, TypeError, AttributeError):
        return {"label": "Unknown", "confidence": "uncertain", "reason": "Model output could not be parsed.", "visible_features": []}


def classify_bytes(data: bytes, mime: str, metadata: str = ""):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(503, "Image classification requires OPENAI_API_KEY. Metadata lookup remains available for NASA images.")
    from openai import OpenAI
    payload = base64.b64encode(data).decode("ascii")
    instruction = ("You identify the likely astronomical body depicted in an image. "
        "Choose EXACTLY one from: " + ", ".join(CLASSES) + ". "
        "Identify based on visible evidence; a spacecraft, diagram, illustration, star field, or ambiguous crop may be Other or Unknown. "
        "Metadata is context, not proof. Do not assert certainty from a visual guess. "
        "Return JSON only with keys label, confidence (low/medium/high/uncertain), reason, visible_features (array of strings). "
        "Do not claim a calibrated probability or verified scientific classification.")
    try:
        response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=45).chat.completions.create(
            model=os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            messages=[{"role":"system", "content": instruction},
                      {"role":"user", "content":[{"type":"text","text":"Context (unverified): " + metadata[:1800]},
                         {"type":"image_url","image_url":{"url":f"data:{mime};base64,{payload}","detail":"high"}}]}],
            response_format={"type":"json_object"}, max_tokens=350)
        return parse_model_answer(response.choices[0].message.content or "")
    except Exception as exc:
        raise HTTPException(502, f"Vision provider failed: {type(exc).__name__}. Check your API key, model access and billing.")


@router.post("/upload")
async def classify_upload(file: UploadFile = File(...)):
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "Upload JPEG, PNG or WEBP only")
    data = await file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE: raise HTTPException(413, "Image exceeds 8 MB")
    if len(data) < 16: raise HTTPException(422, "Empty or invalid image")
    from PIL import Image, UnidentifiedImageError
    import io
    try:
        im = Image.open(io.BytesIO(data)); im.verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, "File is not a valid image")
    result = classify_bytes(data, mime)
    return {**result, "method": "ai_vision", "source": "uploaded_image", "note": "AI visual estimate, not a validated planetary classification."}


@router.post("/nasa")
async def classify_nasa(req: NasaImage):
    # Never fetch an arbitrary user-provided URL: re-query NASA by ID, use trusted returned asset.
    try:
        async with httpx.AsyncClient(timeout=18) as client:
            r = await client.get("https://images-api.nasa.gov/search", params={"nasa_id": req.nasa_id, "media_type": "image"})
            r.raise_for_status()
        items = r.json().get("collection", {}).get("items", [])
        item = next((i for i in items if i.get("data", [{}])[0].get("nasa_id") == req.nasa_id), None)
        if not item: raise HTTPException(404, "NASA image not found")
        data = item["data"][0]
        title = data.get("title", "")
        desc = data.get("description", "")
        urls = [x.get("href", "") for x in item.get("links", []) if x.get("render") == "image"]
        image_url = next((u for u in urls if urlparse(u).scheme == "https" and urlparse(u).hostname == "images-assets.nasa.gov"), None)
        if not image_url: raise HTTPException(422, "No supported NASA thumbnail")
        guess = metadata_guess(title, desc)
        if not os.getenv("OPENAI_API_KEY"):
            return {"label":guess,"confidence":"uncertain","reason":"NASA title keyword only; visual identification unavailable without OpenAI API key.","visible_features":[],"method":"nasa_metadata_only","source":f"https://images.nasa.gov/details/{req.nasa_id}","note":"Metadata-only guess; not image classification."}
        async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
            img = await client.get(image_url)
            img.raise_for_status()
        if len(img.content) > MAX_IMAGE: raise HTTPException(413, "NASA thumbnail too large")
        mime = img.headers.get("content-type", "image/jpeg").split(";")[0]
        if mime not in ALLOWED_MIME: raise HTTPException(415, "Unsupported NASA image format")
        result = classify_bytes(img.content, mime, f"NASA title: {title}; description: {desc[:1200]}")
        return {**result,"method":"ai_vision_with_nasa_context","source":f"https://images.nasa.gov/details/{req.nasa_id}","note":"AI visual estimate; check NASA source metadata for provenance."}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"NASA service unavailable: {type(exc).__name__}")


@router.get("/labels")
def labels():
    return {"classes": CLASSES, "mode": "vision-model-with-abstention", "requires_key_for_upload": True}
