# Kouper Health — Care Coordinator AI

A conversational AI assistant that helps nurses book appointments for patients. Built as a take-home challenge, it combines a FastAPI + Claude-powered agent backend with a chat UI served from the same process. The agent uses Claude's tool-use API to look up patient records, find matching providers, determine appointment type (new vs. established), check available slots, and confirm bookings — never guessing from memory.

---

## Project Structure

```
.
├── agent/
│   ├── agent.py          # Claude agent loop (tool-use orchestration)
│   ├── tools.py          # Tool implementations + Anthropic schemas
│   └── data_sheet.py     # Provider directory, insurance, scheduling rules
├── server/
│   └── main.py           # FastAPI server — /, /chat, /health, /patient/{id} (port 8000)
├── ui/
│   └── index.html        # Chat UI (served at GET /)
├── data_sheet.txt        # Source provider/insurance data
├── requirements.txt
└── .env                  # (you create this — see below)
```

---

## Architecture

Everything runs as a single FastAPI process. The browser talks only to that server; all data lookups happen server-side.

```
Nurse (Browser)
      |
      | POST /chat  (message + patient_id)
      v
 FastAPI server (server/main.py)
      |
      |-- GET /patient/{id} ──────────> Patient data (in-process, _PATIENTS dict)
      |
      |-- data_sheet.py ──────────────> Provider directory, insurance & scheduling rules
      |
      |-- Anthropic Claude API ───────> LLM reasoning + tool-use loop
      |        |
      |        |-- tool: get_patient_info
      |        |-- tool: find_providers
      |        |-- tool: check_appointment_type
      |        |-- tool: get_available_slots
      |        `-- tool: book_appointment
      |
      | ChatResponse (reply + session_id)
      v
Nurse (Browser)
```

Session history is held in memory on the server (`_sessions` dict), so the agent maintains context across multiple turns without re-sending the full history from the client.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yuanjieyue/kouper-care-coordinator.git
cd kouper-care-coordinator
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
```

### 4. Create a `.env` file

```bash
cp .env.example .env            # or create it manually
```

`.env` contents:

```env
ANTHROPIC_API_KEY=sk-ant-...          # required — your Anthropic API key
ANTHROPIC_MODEL=claude-sonnet-4-6     # optional — defaults to claude-sonnet-4-6
PATIENT_API_BASE=http://localhost:8000 # optional — defaults to http://localhost:8000
```

> Get your API key at [console.anthropic.com](https://console.anthropic.com).

---

## Running the App

```bash
source venv/bin/activate
uvicorn server.main:app --reload --port 8000
```

Then open **http://localhost:8000** — the chat UI is served directly from the FastAPI server.

---

## Quick Test Scenarios

Try these in the chat UI with **Patient ID: 1** (John Doe):

| Scenario | What to type |
|---|---|
| Look up the patient | `Who is this patient and what's their appointment history?` |
| Find a specialist | `The patient needs to see an orthopedic specialist. What options do we have?` |
| Check appointment type | `Will this be a new or established patient visit with Dr. Gregory House?` |
| Full booking flow | `Book an orthopedics appointment with Dr. House for next Tuesday morning.` |
| Insurance question | `Does the patient's insurance cover the orthopedics visit?` |
| Primary care follow-up | `I need to schedule a follow-up with Dr. Meredith Grey.` |
| Check all accepted insurances | `What insurance plans do you accept?` |
| Provider location and hours | `Where is Dr. House located and what are his hours?` |
| Self-pay cost question | `How much does an orthopedics visit cost without insurance?` |

The agent will walk through provider lookup → slot availability → confirmation before booking. It will always ask you to confirm before finalizing.

You can also hit the endpoints directly:

```bash
# Health check
curl http://localhost:8000/health

# Patient record
curl http://localhost:8000/patient/1

# Start a conversation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 1, "message": "What providers are available for orthopedics?"}'

# Continue the session (use the session_id from the response above)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"patient_id": 1, "session_id": "139caa79-d0e0-423f-89c7-386af57235b8", "message": "Book the first available slot."}'
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Claude model ID to use |
| `PATIENT_API_BASE` | No | `http://localhost:8000` | Base URL of the patient data endpoint |
