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
            if shift["location"] != tester["pref_location"] and _assigned(
                solver, assignment_vars[(t_idx, s_idx)]
            ):
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
    month_to_shifts: Dict[int, List[int]] = defaultdict(list)
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts[m].append(s_idx)

    rows: List[Dict[str, Any]] = []
    for t_idx, tester in enumerate(person_list):
        target = int(tester.get("month_avg", 0))
        for m, s_indices in month_to_shifts.items():
            assigned = sum(_assigned(solver, assignment_vars[(t_idx, s)]) for s in s_indices)
            deficit = max(0, target - assigned)
            if deficit > 0:
                rows.append(
                    {
                        "component": "monthly_avg",
                        "person": tester["name"],
                        "month": m,
                        "assigned_in_month": assigned,
                        "avg": target,
                        "units": deficit,
                        "weighted": deficit * weight,
                    }
                )
    return rows
