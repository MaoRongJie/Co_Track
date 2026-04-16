# Co-Track Backend

## AI Workflow Structure

```text
app/
├─ agents/
│  ├─ creative_dialogue_and_image_agent.py
│  ├─ intent_and_3d_generation_agent.py
│  └─ providers/
│     ├─ openai_text_image_provider.py
│     ├─ three_d_generation_provider.py
│     └─ provider_protocols.py
├─ graph/
│  ├─ contracts.py
│  ├─ nodes.py
│  ├─ engine.py
│  └─ session_store.py
├─ llm/
│  ├─ client.py
│  └─ json.py
├─ stages/
│  ├─ stage1_extract_concept.py
│  ├─ stage2_plan_3d_model.py
│  ├─ stage3_generate_creative_reply.py
│  └─ stage4_generate_image_assets.py
├─ workflow/
│  └─ controller.py
└─ routes/
   └─ workflow.py
```

## Run (uv)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

If your network requires a mirror:

```bash
cd backend
$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Default bootstrap data

- A default host user is created on startup:
  - `email`: `host@co-track.local`
  - `password`: `Host@123456`
- A default meeting is created:
  - `invite_code`: `555555`

## Key APIs

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/sessions`
- `POST /api/sessions/join`
- `GET /api/sessions/{id}`
- `GET /api/rtc/config`

## Socket.IO events

- Inbound:
  - `meeting:media_join`
  - `meeting:media_leave`
  - `webrtc:offer`
  - `webrtc:answer`
  - `webrtc:ice_candidate`
  - `media:toggle`
  - `media:speak_request`
  - `media:speak_approve`
- Outbound:
  - `meeting:peer_joined`
  - `meeting:peer_left`
  - `webrtc:offer`
  - `webrtc:answer`
  - `webrtc:ice_candidate`
  - `media:peer_state`
  - `media:speak_granted`
