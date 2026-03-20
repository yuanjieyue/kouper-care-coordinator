"""
Agent tool implementations and Anthropic tool schemas for the Care Coordinator.

Each Python function is the implementation; TOOLS is the schema list passed
directly to the Claude API. execute_tool() is the dispatcher used by the
agent loop.
"""

import datetime
import os
import uuid
from typing import Any

import requests

from agent.data_sheet import (
    ACCEPTED_INSURANCES,
    APPOINTMENT_DURATIONS,
    ARRIVAL_EARLY_MINUTES,
    DAY_TO_WEEKDAY,
    ESTABLISHED_LOOKBACK_YEARS,
    SELF_PAY_RATES,
    find_providers,
    get_provider_by_name,
)

PATIENT_API_BASE = os.getenv("PATIENT_API_BASE", "http://localhost:5000")

# Simulated booking store — keyed by booking ID
_bookings: dict[str, dict] = {}


# ── Tool implementations ──────────────────────────────────────────────────────

def get_patient_info(patient_id: int) -> dict:
    """
    Fetch a patient record from the patient API.
    Returns demographics, PCP, referred providers, and appointment history.
    """
    try:
        resp = requests.get(
            f"{PATIENT_API_BASE}/patient/{patient_id}", timeout=5
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Patient API unavailable — is the Flask server running?"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"Patient not found (HTTP {e.response.status_code})."}


def find_providers_tool(
    specialty: str | None = None,
    insurance: str | None = None,
) -> dict:
    """
    Search the provider directory with optional specialty and insurance filters.

    Insurance acceptance is network-wide (all providers share the same accepted
    plan list). If an insurance is supplied, the response indicates whether it is
    accepted and includes self-pay rates when it is not.
    """
    providers = find_providers(specialty=specialty)

    insurance_accepted: bool | None = None
    if insurance:
        insurance_accepted = any(
            insurance.lower() in plan.lower() for plan in ACCEPTED_INSURANCES
        )

    results = []
    for p in providers:
        entry: dict[str, Any] = {
            "name": p.full_name,
            "certification": p.certification,
            "specialty": p.specialty,
            "departments": [
                {
                    "name": d.name,
                    "phone": d.phone,
                    "address": d.address,
                    "hours": d.hours_raw,
                }
                for d in p.departments
            ],
        }
        if insurance is not None:
            entry["insurance_accepted"] = insurance_accepted
            if not insurance_accepted:
                entry["self_pay_rate"] = f"${SELF_PAY_RATES[p.specialty]}"
        results.append(entry)

    return {
        "providers": results,
        "count": len(results),
        "insurance_note": (
            f"{insurance} is "
            f"{'accepted' if insurance_accepted else 'NOT accepted — self-pay applies'}"
            if insurance
            else None
        ),
    }


def get_appointment_type(patient_id: int, provider_name: str) -> dict:
    """
    Determine NEW vs ESTABLISHED for a patient/provider pair.

    ESTABLISHED requires a completed appointment with that provider within
    the last ESTABLISHED_LOOKBACK_YEARS years. Cancelled and no-show visits
    do not count.

    Returns appointment type, duration, arrival guidance, and the date of the
    last qualifying completed visit for transparency.
    """
    patient = get_patient_info(patient_id)
    if "error" in patient:
        return patient

    provider = get_provider_by_name(provider_name)
    if not provider:
        return {"error": f"Provider '{provider_name}' not found in directory."}

    today = datetime.date.today()
    cutoff = today.replace(year=today.year - ESTABLISHED_LOOKBACK_YEARS)

    last_completed: datetime.date | None = None
    for appt in patient.get("appointments", []):
        if appt.get("status") != "completed":
            continue
        # Loose match: provider last name appears in the appointment's provider field
        if provider.last_name.lower() not in appt.get("provider", "").lower():
            continue
        appt_date = datetime.datetime.strptime(appt["date"], "%m/%d/%y").date()
        if last_completed is None or appt_date > last_completed:
            last_completed = appt_date

    is_established = last_completed is not None and last_completed >= cutoff
    appt_type = "ESTABLISHED" if is_established else "NEW"

    return {
        "patient_id": patient_id,
        "provider": provider.full_name,
        "appointment_type": appt_type,
        "duration_minutes": APPOINTMENT_DURATIONS[appt_type],
        "arrive_early_minutes": ARRIVAL_EARLY_MINUTES[appt_type],
        "last_completed_visit": (
            last_completed.isoformat() if last_completed else None
        ),
        "reason": (
            f"Last completed visit was {last_completed} "
            f"({'within' if is_established else 'more than'} {ESTABLISHED_LOOKBACK_YEARS} years)"
            if last_completed
            else "No prior completed visits on record"
        ),
    }


def check_insurance(insurance_name: str) -> dict:
    """
    Check whether an insurance plan is accepted by Kouper Health providers.
    Returns self-pay rates for all specialties when the plan is not accepted.
    """
    accepted = any(
        insurance_name.lower() in plan.lower() for plan in ACCEPTED_INSURANCES
    )
    result: dict[str, Any] = {
        "insurance": insurance_name,
        "accepted": accepted,
        "accepted_plans": ACCEPTED_INSURANCES,
    }
    if not accepted:
        result["self_pay_rates"] = {
            specialty: f"${rate}" for specialty, rate in SELF_PAY_RATES.items()
        }
    return result


def get_available_slots(provider_name: str, num_days: int = 7) -> dict:
    """
    Return simulated available slots for a provider over the next num_days days.

    Slots are generated hourly within each department's office hours.
    When a provider works at multiple locations on different days (e.g. House),
    slots are grouped by department so the agent can present location options.
    """
    provider = get_provider_by_name(provider_name)
    if not provider:
        return {"error": f"Provider '{provider_name}' not found in directory."}

    today = datetime.date.today()
    slots_by_dept: dict[str, list[str]] = {}

    for dept in provider.departments:
        valid_weekdays = {DAY_TO_WEEKDAY[d] for d in dept.days}
        open_h = int(dept.open_time.split(":")[0])
        close_h = int(dept.close_time.split(":")[0])

        dept_slots: list[str] = []
        for offset in range(1, num_days + 1):
            date = today + datetime.timedelta(days=offset)
            if date.weekday() not in valid_weekdays:
                continue
            date_str = date.strftime("%A, %b %d")
            for hour in range(open_h, close_h):
                time_label = datetime.time(hour, 0).strftime("%I:%M %p").lstrip("0")
                dept_slots.append(f"{date_str} at {time_label}")

        slots_by_dept[dept.name] = dept_slots

    return {
        "provider": provider.full_name,
        "specialty": provider.specialty,
        "available_slots_by_department": slots_by_dept,
        "note": "Slots are indicative. Confirm with the office before finalizing.",
    }


def book_appointment(
    patient_id: int,
    provider_name: str,
    department_name: str,
    slot: str,
) -> dict:
    """
    Simulate booking an appointment and return a confirmation.

    Looks up appointment type automatically to include correct duration and
    arrival instructions. Stores the booking in the in-memory _bookings store.
    Always confirm the details with the patient before calling this tool.
    """
    provider = get_provider_by_name(provider_name)
    if not provider:
        return {"error": f"Provider '{provider_name}' not found in directory."}

    dept = next(
        (d for d in provider.departments if department_name.lower() in d.name.lower()),
        None,
    )
    if not dept:
        return {
            "error": (
                f"Department '{department_name}' not found for {provider.full_name}."
            ),
            "available_departments": [d.name for d in provider.departments],
        }

    appt_info = get_appointment_type(patient_id, provider_name)
    # Fall back to NEW if type lookup fails (e.g. API down)
    appt_type = appt_info.get("appointment_type", "NEW")
    arrive_early = ARRIVAL_EARLY_MINUTES[appt_type]

    booking_id = str(uuid.uuid4())[:8].upper()
    booking: dict[str, Any] = {
        "booking_id": booking_id,
        "status": "confirmed",
        "patient_id": patient_id,
        "provider": provider.full_name,
        "department": dept.name,
        "address": dept.address,
        "phone": dept.phone,
        "slot": slot,
        "appointment_type": appt_type,
        "duration_minutes": APPOINTMENT_DURATIONS[appt_type],
        "arrive_early_minutes": arrive_early,
        "instructions": (
            f"Please arrive {arrive_early} minutes early. "
            f"Call {dept.phone} if you need to reschedule."
        ),
    }
    _bookings[booking_id] = booking
    return booking


# ── Anthropic tool schemas ────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "get_patient_info",
        "description": (
            "Fetch a patient's full record from the patient API: demographics, "
            "primary care provider, referred providers and specialties, and "
            "appointment history with statuses (completed, noshow, cancelled)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The numeric patient ID.",
                }
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "find_providers",
        "description": (
            "Search the provider directory. Optionally filter by specialty "
            "(e.g. 'Primary Care', 'Orthopedics', 'Surgery'). "
            "Optionally supply the patient's insurance to check acceptance "
            "and see self-pay rates when not accepted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialty": {
                    "type": "string",
                    "description": (
                        "Specialty to filter by. Omit to return all providers."
                    ),
                },
                "insurance": {
                    "type": "string",
                    "description": (
                        "Patient insurance plan name to check acceptance for."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_appointment_type",
        "description": (
            "Determine whether a patient's next visit with a specific provider "
            "will be NEW (30 min) or ESTABLISHED (15 min), based on completed "
            "appointment history within the past 5 years. "
            "Also returns how many minutes early the patient should arrive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The numeric patient ID.",
                },
                "provider_name": {
                    "type": "string",
                    "description": (
                        "Provider last name or full name "
                        "(e.g. 'Grey' or 'Dr. Meredith Grey')."
                    ),
                },
            },
            "required": ["patient_id", "provider_name"],
        },
    },
    {
        "name": "check_insurance",
        "description": (
            "Check whether a specific insurance plan is accepted by Kouper Health "
            "providers. Returns the full list of accepted plans and self-pay rates "
            "for all specialties when the plan is not accepted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "insurance_name": {
                    "type": "string",
                    "description": "The insurance plan name to check.",
                }
            },
            "required": ["insurance_name"],
        },
    },
    {
        "name": "get_available_slots",
        "description": (
            "Return available appointment slots for a provider over the next N days "
            "(default 7). Slots are within office hours at each of the provider's "
            "departments. Use get_appointment_type first to know the appointment "
            "duration and help the patient pick an appropriate slot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider_name": {
                    "type": "string",
                    "description": "Provider last name or full name.",
                },
                "num_days": {
                    "type": "integer",
                    "description": "Days ahead to look. Defaults to 7.",
                },
            },
            "required": ["provider_name"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Simulate booking an appointment for a patient. Returns a confirmation "
            "with booking ID, location, and arrival instructions. "
            "IMPORTANT: Always confirm the provider, location, and slot with the "
            "patient before calling this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "The numeric patient ID.",
                },
                "provider_name": {
                    "type": "string",
                    "description": "Provider last name or full name.",
                },
                "department_name": {
                    "type": "string",
                    "description": "The department/location name to book at.",
                },
                "slot": {
                    "type": "string",
                    "description": (
                        "Appointment slot exactly as returned by get_available_slots."
                    ),
                },
            },
            "required": ["patient_id", "provider_name", "department_name", "slot"],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

_TOOL_FUNCTIONS: dict[str, Any] = {
    "get_patient_info":    lambda inp: get_patient_info(**inp),
    "find_providers":      lambda inp: find_providers_tool(**inp),
    "get_appointment_type": lambda inp: get_appointment_type(**inp),
    "check_insurance":     lambda inp: check_insurance(**inp),
    "get_available_slots": lambda inp: get_available_slots(**inp),
    "book_appointment":    lambda inp: book_appointment(**inp),
}


def execute_tool(name: str, tool_input: dict) -> dict:
    """
    Dispatch a tool call by name and return the result dict.
    Returns an error dict if the tool is unknown or raises an exception.
    """
    fn = _TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool: '{name}'."}
    try:
        return fn(tool_input)
    except Exception as e:
        return {"error": f"Tool '{name}' raised an exception: {e}"}
