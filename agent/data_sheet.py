"""
Structured representation of the provider directory and appointment rules
from data/data_sheet.txt.

Queried at runtime by agent tools — never baked into the system prompt.
All business logic lives here so tools stay thin.
"""

from dataclasses import dataclass, field
from typing import Optional

# Canonical weekday ordering for range parsing (e.g. "Tu-Th")
_DAY_ORDER = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]

# Python weekday (Mon=0) for each abbreviation, used when generating slots
DAY_TO_WEEKDAY: dict[str, int] = {
    "M": 0, "Tu": 1, "W": 2, "Th": 3, "F": 4, "Sa": 5, "Su": 6
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Department:
    name: str
    phone: str
    address: str
    hours_raw: str       # e.g. "M-F 9am-5pm" — kept for display
    days: list[str]      # e.g. ["M", "Tu", "W"]
    open_time: str       # 24h string, e.g. "09:00"
    close_time: str      # 24h string, e.g. "17:00"


@dataclass
class Provider:
    last_name: str
    first_name: str
    certification: str   # e.g. "MD", "FNP", "PhD, MD"
    specialty: str
    departments: list[Department] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"Dr. {self.first_name} {self.last_name}"


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _to_24h(time_str: str) -> str:
    """Convert '9am' or '5pm' → '09:00' / '17:00'."""
    t = time_str.lower().strip()
    if t.endswith("am"):
        return f"{int(t[:-2]):02d}:00"
    if t.endswith("pm"):
        h = int(t[:-2])
        return f"{h + 12 if h != 12 else 12:02d}:00"
    return t  # already in usable form


def _parse_hours(hours_str: str) -> tuple[list[str], str, str]:
    """
    Parse 'M-F 9am-5pm' (or 'Tu-Th 10am-4pm') into
    (day_list, open_24h, close_24h).

    Day ranges like 'M-W' expand to all days between them inclusive,
    using _DAY_ORDER as the canonical sequence.
    """
    day_part, time_part = hours_str.strip().split(" ", 1)
    open_str, close_str = time_part.split("-", 1)

    if "-" in day_part:
        start, end = day_part.split("-", 1)
        si = _DAY_ORDER.index(start)
        ei = _DAY_ORDER.index(end)
        days = _DAY_ORDER[si : ei + 1]
    else:
        days = [day_part]

    return days, _to_24h(open_str), _to_24h(close_str)


def _dept(name: str, phone: str, address: str, hours: str) -> Department:
    days, open_time, close_time = _parse_hours(hours)
    return Department(
        name=name,
        phone=phone,
        address=address,
        hours_raw=hours,
        days=days,
        open_time=open_time,
        close_time=close_time,
    )


# ── Provider directory ────────────────────────────────────────────────────────

PROVIDERS: list[Provider] = [
    Provider(
        last_name="Grey",
        first_name="Meredith",
        certification="MD",
        specialty="Primary Care",
        departments=[
            _dept(
                "Sloan Primary Care",
                "(710) 555-2070",
                "202 Maple St, Winston-Salem, NC 27101",
                "M-F 9am-5pm",
            ),
        ],
    ),
    Provider(
        last_name="House",
        first_name="Gregory",
        certification="MD",
        specialty="Orthopedics",
        departments=[
            _dept(
                "PPTH Orthopedics",
                "(445) 555-6205",
                "101 Pine St, Greensboro, NC 27401",
                "M-W 9am-5pm",
            ),
            _dept(
                "Jefferson Hospital",
                "(215) 555-6123",
                "202 Maple St, Claremont, NC 28610",
                "Th-F 9am-5pm",
            ),
        ],
    ),
    Provider(
        last_name="Yang",
        first_name="Cristina",
        certification="MD",
        specialty="Surgery",
        departments=[
            _dept(
                "Seattle Grace Cardiac Surgery",
                "(710) 555-3082",
                "456 Elm St, Charlotte, NC 28202",
                "M-F 9am-5pm",
            ),
        ],
    ),
    Provider(
        last_name="Perry",
        first_name="Chris",
        certification="FNP",
        specialty="Primary Care",
        departments=[
            _dept(
                "Sacred Heart Surgical Department",
                "(339) 555-7480",
                "123 Main St, Raleigh, NC 27601",
                "M-W 9am-5pm",
            ),
        ],
    ),
    Provider(
        last_name="Brennan",
        first_name="Temperance",
        certification="PhD, MD",
        specialty="Orthopedics",
        departments=[
            _dept(
                "Jefferson Hospital",
                "(215) 555-6123",
                "202 Maple St, Claremont, NC 28610",
                "Tu-Th 10am-4pm",
            ),
        ],
    ),
]

# ── Business rules ────────────────────────────────────────────────────────────

# All Kouper Health providers share the same accepted insurance list.
ACCEPTED_INSURANCES: list[str] = [
    "Medicaid",
    "United Health Care",
    "Blue Cross Blue Shield of North Carolina",
    "Aetna",
    "Cigna",
]

SELF_PAY_RATES: dict[str, int] = {
    "Primary Care": 150,
    "Orthopedics": 300,
    "Surgery": 1000,
}

# Appointment type → duration in minutes
APPOINTMENT_DURATIONS: dict[str, int] = {
    "NEW": 30,
    "ESTABLISHED": 15,
}

# How many minutes early each appointment type should arrive
ARRIVAL_EARLY_MINUTES: dict[str, int] = {
    "NEW": 30,
    "ESTABLISHED": 10,
}

# A patient is ESTABLISHED if they have a completed visit in this many years
ESTABLISHED_LOOKBACK_YEARS: int = 5


# ── Query helpers ─────────────────────────────────────────────────────────────

def find_providers(
    specialty: Optional[str] = None,
    name_query: Optional[str] = None,
) -> list[Provider]:
    """Filter PROVIDERS by specialty and/or partial name match."""
    results = PROVIDERS
    if specialty:
        results = [p for p in results if p.specialty.lower() == specialty.lower()]
    if name_query:
        q = name_query.lower()
        results = [
            p for p in results
            if q in p.last_name.lower() or q in p.first_name.lower()
        ]
    return results


def get_provider_by_name(name: str) -> Optional[Provider]:
    """
    Case-insensitive partial match against last name, first name, or full name.
    Returns the first match, or None.
    """
    q = name.lower()
    for p in PROVIDERS:
        if q in p.last_name.lower() or q in p.first_name.lower() or q in p.full_name.lower():
            return p
    return None
