import csv
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Tuple

# Row shape for penalties export
# Common fields: component, person, units, weighted, extra info by component


def _assigned(solver, var) -> int:
    return int(solver.Value(var) == 1)


def compute_shift_counts(assignment_vars, solver, num_people: int, num_shifts: int) -> List[int]:
    counts = [
        sum(_assigned(solver, assignment_vars[(t, s)]) for s in range(num_shifts))
        for t in range(num_people)
    ]
    return counts


def compute_location_penalty_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            assigned = _assigned(solver, assignment_vars[(t_idx, s_idx)])
            if not assigned:
                continue
            flags = tester.get("pref_loc_flags", {})
            if flags:
                flag = flags.get(shift["location"], 2)
                # 0: hard banned (should not occur if constraints applied), 1: penalize, 2: no penalty
                if flag == 1:
                    rows.append(
                        {
                            "component": "location",
                            "person": tester["name"],
                            "date": shift["date"],
                            "day": shift["day"],
                            "location": shift["location"],
                            "team": shift["team"],
                            "units": 1,
                            "weighted": weight,
                        }
                    )
            else:
                # Legacy behavior: penalize when not on single preferred location
                if shift["location"] != tester.get("pref_location"):
                    rows.append(
                        {
                            "component": "location",
                            "person": tester["name"],
                            "date": shift["date"],
                            "day": shift["day"],
                            "location": shift["location"],
                            "team": shift["team"],
                            "units": 1,
                            "weighted": weight,
                        }
                    )
    return rows


def compute_monthly_min_avail_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    """Rows for: if a person was available in a month, but assigned 0 shifts in that month => 1 unit penalty."""
    month_to_shifts: Dict[int, List[int]] = defaultdict(list)
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts[m].append(s_idx)

    rows: List[Dict[str, Any]] = []
    for t_idx, tester in enumerate(person_list):
        avail_map = tester.get("availability", {}) or {}
        months_available = set()
        for dstr, ok in avail_map.items():
            try:
                if ok:
                    m = datetime.strptime(dstr, "%Y-%m-%d").month
                    months_available.add(m)
            except Exception:
                continue
        for m, s_indices in month_to_shifts.items():
            if m not in months_available:
                continue
            assigned = sum(_assigned(solver, assignment_vars[(t_idx, s)]) for s in s_indices)
            if assigned == 0:
                rows.append(
                    {
                        "component": "monthly_min_avail",
                        "person": tester["name"],
                        "month": m,
                        "assigned_in_month": assigned,
                        "units": 1,
                        "weighted": weight,
                    }
                )
    return rows


def compute_monthly_excess_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    # Group shifts by month index 1..12
    month_to_shifts: Dict[int, List[int]] = defaultdict(list)
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts[m].append(s_idx)

    rows: List[Dict[str, Any]] = []
    for t_idx, tester in enumerate(person_list):
        cap = int(tester.get("month_max", 0))
        for m, s_indices in month_to_shifts.items():
            assigned = sum(_assigned(solver, assignment_vars[(t_idx, s)]) for s in s_indices)
            excess = max(0, assigned - cap)
            if excess > 0:
                rows.append(
                    {
                        "component": "monthly",
                        "person": tester["name"],
                        "month": m,
                        "assigned_in_month": assigned,
                        "cap": cap,
                        "units": excess,
                        "weighted": excess * weight,
                    }
                )
    return rows


def compute_fairness_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    counts = compute_shift_counts(assignment_vars, solver, len(person_list), len(shift_list))
    span = (max(counts) if counts else 0) - (min(counts) if counts else 0)
    return [
        {
            "component": "fairness",
            "person": "",
            "units": span,
            "weighted": span * weight,
        }
    ]


def compute_weekly_multi_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    """Penalize more than 1 assignment in the same ISO week for the same person.

    For each person/week: units = max(0, assigned_in_week - 1)
    weighted = units * weight
    """
    from datetime import datetime as _dt
    # Build week mapping
    week_to_shifts: Dict[Tuple[int, int], List[int]] = {}
    for s_idx, shift in enumerate(shift_list):
        d = _dt.strptime(shift["date"], "%Y-%m-%d")
        iso_year, iso_week, _ = d.isocalendar()
        week_to_shifts.setdefault((iso_year, iso_week), []).append(s_idx)

    rows: List[Dict[str, Any]] = []
    for t_idx, tester in enumerate(person_list):
        for (y, w), s_indices in week_to_shifts.items():
            assigned = sum(_assigned(solver, assignment_vars[(t_idx, s)]) for s in s_indices)
            units = max(0, assigned - 1)
            if units > 0:
                rows.append(
                    {
                        "component": "weekly_multi",
                        "person": tester["name"],
                        "iso_year": y,
                        "iso_week": w,
                        "assigned_in_week": assigned,
                        "units": units,
                        "weighted": units * weight,
                    }
                )
    return rows


def export_penalties(
    filepath: str,
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weights: Dict[str, int],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compute a long-form penalty list and write to CSV. Returns (rows, summary)."""
    all_rows: List[Dict[str, Any]] = []

    loc_rows = compute_location_penalty_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("location", 1)
    )
    all_rows.extend(loc_rows)

    monthly_rows = compute_monthly_excess_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("monthly", 1)
    )
    all_rows.extend(monthly_rows)

    fairness_rows = compute_fairness_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("fairness", 1)
    )
    all_rows.extend(fairness_rows)

    # Monthly average shortfalls
    avg_rows = compute_monthly_avg_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("monthly_avg", 1)
    )
    all_rows.extend(avg_rows)

    # Monthly minimum availability penalty rows
    min_av_rows = compute_monthly_min_avail_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("monthly_min_avail", 1)
    )
    all_rows.extend(min_av_rows)

    # Weekly multi-assignments
    weekly_rows = compute_weekly_multi_rows(
        assignment_vars, solver, person_list, shift_list, weights.get("weekly_multi", 1)
    )
    all_rows.extend(weekly_rows)

    # Aggregate totals
    total_weighted = sum(r.get("weighted", 0) for r in all_rows)
    by_component: Dict[str, int] = defaultdict(int)
    for r in all_rows:
        by_component[r["component"]] += int(r.get("weighted", 0))

    summary = {
        "total_weighted": total_weighted,
        "by_component": dict(by_component),
    }

    # Write CSV
    fieldnames = sorted({k for r in all_rows for k in r.keys()})
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)

    # Also write a compact summary CSV
    summary_path = filepath.replace(".csv", "_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["component", "weighted_total"])
        for comp, val in by_component.items():
            writer.writerow([comp, val])
        writer.writerow(["__total__", total_weighted])

    return all_rows, summary


def compute_monthly_avg_rows(
    assignment_vars,
    solver,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
) -> List[Dict[str, Any]]:
    # Determine distinct year-months present in the roster and total shifts
    ym_keys = set()
    for shift in shift_list:
        d = datetime.strptime(shift["date"], "%Y-%m-%d")
        ym_keys.add((d.year, d.month))
    n_months = len(ym_keys) if ym_keys else 0

    rows: List[Dict[str, Any]] = []
    total_shifts = len(shift_list)
    for t_idx, tester in enumerate(person_list):
        per_month = int(tester.get("month_avg", 0))
        target_total = per_month * n_months
        assigned_total = sum(_assigned(solver, assignment_vars[(t_idx, s)]) for s in range(total_shifts))
        deficit = max(0, target_total - assigned_total)
        # Quadratic cost: weight * deficit^2
        weighted = weight * (deficit * deficit)
        if deficit > 0:
            rows.append(
                {
                    "component": "monthly_avg",
                    "person": tester["name"],
                    "months": n_months,
                    "assigned_total": assigned_total,
                    "avg_per_month": per_month,
                    "target_total": target_total,
                    "units": deficit,
                    "weighted": weighted,
                }
            )
    return rows
