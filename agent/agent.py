"""
Care Coordinator agent loop.

Drives a multi-turn conversation using Claude's tool use API.
Stateless per call — the caller owns the message history and persists it
between turns (e.g. the FastAPI session store).

Usage:
    reply, updated_history = process_message(patient_id=1, history=[], user_message="...")
"""

import datetime
import json
import os

import anthropic

from agent.tools import TOOLS, execute_tool

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Safety cap: prevent infinite tool-call loops on unexpected model behaviour
MAX_TOOL_ITERATIONS = 10


# ── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """
    Build the system prompt with today's date injected.
    No provider data is included here — the agent must always look that up
    via tools so it never relies on stale baked-in context.
    """
    today = datetime.date.today().strftime("%B %d, %Y")
    return f"""\
You are a Care Coordinator assistant for Kouper Health. You support nurses and \
care coordinators who are booking appointments on behalf of their patients.

Today's date is {today}.

## Your responsibilities
- Help the nurse find the right provider for a patient's specialty or referral need.
- Determine whether the patient's next visit will be NEW (30 min) or ESTABLISHED \
(15 min) based on appointment history, and surface that clearly.
- Look up available slots and help the nurse select an appropriate time.
- Confirm the provider, location, date/time, and any cost implications \
before calling book_appointment — never book without explicit confirmation.
- Include arrival guidance in every booking summary so the nurse can relay it \
to the patient (NEW: arrive 30 min early; ESTABLISHED: 10 min early).

## How to use your tools
- Always call tools to look up data. Never guess provider details, hours, insurance \
acceptance, or appointment rules from memory.
- You may need to call multiple tools in sequence: e.g. get_patient_info → \
find_providers → get_appointment_type → get_available_slots → book_appointment.
- If a tool returns an error, explain it clearly and suggest the nurse call \
the office directly to resolve it.

## Tone and scope
- Be efficient and precise — nurses are busy professionals who need clear, \
actionable information without unnecessary explanation.
- If the nurse asks about clinical matters (symptoms, diagnoses, treatment options), \
note that this is outside your scope and suggest they consult the treating provider.
- Only surface patient details (name, DOB, history) when directly relevant to the \
booking task. Do not repeat sensitive information unnecessarily.

You help with: scheduling, provider lookup, insurance questions, arrival guidance, \
and appointment type determination.
You do NOT provide: clinical guidance, diagnoses, treatment recommendations, \
or advice on patient care decisions.\
"""


# ── Agent loop ────────────────────────────────────────────────────────────────

def process_message(
    patient_id: int,
    history: list[dict],
    user_message: str,
    model: str = MODEL,
) -> tuple[str, list[dict]]:
    """
    Process one user turn and return (assistant_reply, updated_history).

    Args:
        patient_id:   Used to scope tool calls that require patient context.
                      Prepended to the first user message so the agent knows
                      which patient it's serving without the caller needing to
                      say it in every message.
        history:      The full conversation so far as a list of message dicts.
                      Pass [] for a new conversation.
        user_message: The patient's latest message.
        model:        Claude model ID to use.

    Returns:
        A tuple of (reply_text, updated_history).
        updated_history should be stored by the caller and passed back on the
        next turn to maintain conversation context.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    # Inject the patient ID into the first user message so the agent always
    # knows who it is talking to without requiring the caller to re-state it.
    if not history:
        first_content = f"[Patient ID: {patient_id}]\n\n{user_message}"
    else:
        first_content = user_message

    messages = history + [{"role": "user", "content": first_content}]
    system = _build_system_prompt()

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Always append the full assistant response (content block objects).
        # This preserves tool_use blocks that must be present in history when
        # we send back tool_result blocks on the next API call.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            reply = _extract_text(response.content)
            return reply, messages

        if response.stop_reason == "tool_use":
            tool_results = _execute_tool_calls(response.content)
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason (max_tokens, stop_sequence, etc.)
        # Return whatever text Claude produced, if any.
        reply = _extract_text(response.content)
        if not reply:
            reply = (
                "I'm sorry, I wasn't able to complete that. "
                "Please try rephrasing or call the office directly."
            )
        return reply, messages

    # Iteration cap hit — should not happen in normal operation
    return (
        "I'm sorry, that request took too many steps to process. "
        "Please try again or call the office directly.",
        messages,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(content: list) -> str:
    """Pull the first text block from a content list, or return empty string."""
    return next(
        (block.text for block in content if hasattr(block, "text") and block.type == "text"),
        "",
    )


def _execute_tool_calls(content: list) -> list[dict]:
    """
    Execute every tool_use block in a response content list and return
    a list of tool_result dicts ready to be sent back as a user message.
    """
    results = []
    for block in content:
        if not hasattr(block, "type") or block.type != "tool_use":
            continue
        tool_result = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(tool_result),
        })
    return results
