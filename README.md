# Kouper Health — Care Coordinator AI

A conversational AI assistant that helps nurses book appointments for patients. Built as a take-home challenge, it combines a Flask patient-data API, a FastAPI + Claude-powered agent backend, and a plain-HTML chat UI. The agent uses Claude's tool-use API to look up patient records, find matching providers, determine appointment type (new vs. established), check available slots, and confirm bookings — never guessing from memory.

---

## Project Structure

```
.
├── api/
│   └── flask-app.py      # Flask patient data API (port 5000)
├── agent/
│   ├── agent.py          # Claude agent loop (tool-use orchestration)
│   ├── tools.py          # Tool implementations + Anthropic schemas
│   └── data_sheet.py     # Provider directory, insurance, scheduling rules
├── server/
│   └── main.py           # FastAPI server — /chat and /health (port 8000)
├── ui/
│   └── index.html        # Chat UI (open directly in browser)
├── data_sheet.txt        # Source provider/insurance data
├── requirements.txt
└── .env                  # (you create this — see below)
```

---

## Setup

### 1. Clone the repo

```bash
git clone <repo-url>
cd MLChallenge
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
pip install flask               # Flask is not in requirements.txt
```

### 4. Create a `.env` file

```bash
cp .env.example .env            # or create it manually
```

`.env` contents:

```env
ANTHROPIC_API_KEY=sk-ant-...          # required — your Anthropic API key
ANTHROPIC_MODEL=claude-sonnet-4-6     # optional — defaults to claude-sonnet-4-6
PATIENT_API_BASE=http://localhost:5000 # optional — defaults to http://localhost:5000
```

> Get your API key at [console.anthropic.com](https://console.anthropic.com).

Load the env vars before starting the servers:

```bash
export $(cat .env | xargs)
```

---

## Running the App (3 terminals)

### Terminal 1 — Flask patient API

```bash
source venv/bin/activate
python api/flask-app.py
# Runs on http://localhost:5000
```

### Terminal 2 — FastAPI agent server

```bash
source venv/bin/activate
export $(cat .env | xargs)
uvicorn server.main:app --reload --port 8000
# Runs on http://localhost:8000
```

### Terminal 3 — Chat UI

Just open the file in your browser — no build step needed:

```bash
open ui/index.html          # macOS
# xdg-open ui/index.html   # Linux
# start ui/index.html       # Windows
```

Or navigate to the file path directly in your browser: `file:///path/to/MLChallenge/ui/index.html`

---

## Quick Test Scenarios

Make sure all three services are running, then try these in the chat UI with **Patient ID: 1** (John Doe):

| Scenario | What to type |
|---|---|
| Look up the patient | `Who is this patient and what's their appointment history?` |
| Find a specialist | `The patient needs to see an orthopedic specialist. What options do we have?` |
| Check appointment type | `Will this be a new or established patient visit with Dr. Gregory House?` |
| Full booking flow | `Book an orthopedics appointment with Dr. House for next Tuesday morning.` |
| Insurance question | `Does the patient's insurance cover the orthopedics visit?` |
| Primary care follow-up | `I need to schedule a follow-up with Dr. Meredith Grey.` |

The agent will walk through provider lookup → slot availability → confirmation before booking. It will always ask you to confirm before finalizing.

You can also hit the FastAPI endpoints directly:

```bash
# Health check
curl http://localhost:8000/health

# Start a conversation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 1, "message": "What providers are available for orthopedics?"}'

# Continue the session (use the session_id from the response above)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 1, "session_id": "<session_id>", "message": "Book the first available slot."}'
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Claude model ID to use |
| `PATIENT_API_BASE` | No | `http://localhost:5000` | Base URL of the Flask patient API |
