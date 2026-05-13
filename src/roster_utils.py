from __future__ import annotations

from datetime import datetime


def group_shifts_by_month(shifts: list) -> dict[int, list[int]]:
    """Return {month: [shift_indices]} for a list of Shift objects."""
    result: dict[int, list[int]] = {}
    for s_idx, shift in enumerate(shifts):
        m = datetime.strptime(shift.date, "%Y-%m-%d").month
        result.setdefault(m, []).append(s_idx)
    return result


def group_shifts_by_iso_week(shifts: list) -> dict[tuple[int, int], list[int]]:
    """Return {(iso_year, iso_week): [shift_indices]} for a list of Shift objects."""
    result: dict[tuple[int, int], list[int]] = {}
    for s_idx, shift in enumerate(shifts):
        d = datetime.strptime(shift.date, "%Y-%m-%d")
        iso_year, iso_week, _ = d.isocalendar()
        result.setdefault((iso_year, iso_week), []).append(s_idx)
    return result


def get_available_months(person, shifts: list) -> set[int]:
    """Return months in which a Person has at least one available date."""
    months: set[int] = set()
    for dstr, ok in person.availability.items():
        try:
            if ok:
                months.add(datetime.strptime(dstr, "%Y-%m-%d").month)
        except Exception:
            continue
    return months
