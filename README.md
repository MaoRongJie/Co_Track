# Co-Track

Co-Track is a collaborative coating-design workspace with:
- A React + TypeScript frontend for meeting flow, drawing canvas, AI sidebar, and stage-based review.
- A FastAPI backend for auth, sessions, stage orchestration, AI chat/image, and RTC signaling.

## Project Structure

```text
.
|-- frontend/
|   |-- src/
|   |-- public/
|   |-- index.html
|   |-- package.json
|   `-- .env.example
|-- backend/
|   |-- app/
|   |-- tests/
|   |-- pyproject.toml
|   |-- README.md
|   `-- .env.example
|-- docs/
|-- package.json
`-- README.md
```

## Quick Start

### From the repository root

```bash
npm run frontend:install
npm run backend:sync
npm run frontend:dev
npm run backend:dev
```

If `backend/.venv` is already present, you can skip `npm run backend:sync` and start the backend directly.

### Directly in each app

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

If `uv` is unavailable but `backend/.venv` already exists, you can run:

```bash
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend default: `http://127.0.0.1:5173`

Backend health check:

```bash
curl http://127.0.0.1:8000/health
```

## Environment Variables

- Frontend example: `frontend/.env.example`
- Backend example: `backend/.env.example`

Important frontend keys:
- `VITE_API_BASE_URL`
- `VITE_SOCKET_URL`
- `VITE_STUN_URL`

Important backend keys:
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_TEXT_MODEL`
- `OPENAI_VISION_MODEL`
- `OPENAI_IMAGE_MODEL`

## Root Scripts

- `npm run frontend:install`: install frontend dependencies
- `npm run frontend:dev`: start the frontend dev server
- `npm run frontend:build`: type-check and build the frontend
- `npm run frontend:preview`: preview the frontend build
- `npm run backend:sync`: sync backend dependencies with `uv`
- `npm run backend:dev`: run the backend server with the existing backend virtualenv or `uv`
