# ORBIT-MIND AI V4 — Integrated Mission Intelligence

Full-stack **research demonstrator** with 3D animated Earth/satellite, simulated telemetry, LangGraph four-stage analysis, SQLite history, NASA image search, OpenAI vision planet identification, PDF/TXT research retrieval, CelesTrak TLE catalog with SGP4 orbit altitudes, NASA/JPL historical fireballs, and hypothetical repair triage.

## Run (Windows PowerShell)

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Edit backend/.env and insert your OpenAI key (optional for orbit feeds, required for vision).
uvicorn app.main:app --reload --port 8000
```

In a second terminal from the project root:
```powershell
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173 · API docs: http://localhost:8000/docs

## Data provenance & limitations

- **CelesTrak**: public TLE elements, fetched on demand; SGP4 Earth-centered position and approximate altitude computed at request time. This is **not real-time telemetry**, complete catalog enumeration, or precise surface distance. Results limited to 50 per query and public groups. External API can be unavailable/rate limited.
- **NASA JPL Fireball API**: historical observed atmospheric events, not live meteor detection or impact prediction.
- **Satellite health / repair**: unknown for catalog satellites; no legitimate repair counts can be calculated from TLEs. Maintenance simulator uses **user-provided hypothetical telemetry** and reports possible flags, never real repairability.
- **Planet image classification**: OpenAI vision inference, not a validated custom-trained classifier; may misidentify images.
- **RAG**: locally indexed uploaded documents and retrieval snippets, not an official NASA knowledge base.
- **Mission control**: simulated telemetry only; never sends real commands.

## Environment

`backend/.env` (template included):
```dotenv
OPENAI_API_KEY=your_secret_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_VISION_MODEL=gpt-4.1-mini
CORS_ORIGINS=http://localhost:5173
```

`frontend/.env`: `VITE_API_URL=http://localhost:8000`

Never commit API keys. API usage may incur fees.

## Test
```powershell
cd backend
pip install -r requirements-dev.txt
pytest -q
```

Live external API calls and browser build must be tested on a networked development machine.
