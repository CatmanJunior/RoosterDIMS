import csv
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from models import PenaltyRow, SolverContext
from roster_utils import group_shifts_by_month, group_shifts_by_iso_week, get_available_months


def _assigned(solver, var) -> int:
    return int(solver.Value(var) == 1)


def compute_location_penalty_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    rows: List[PenaltyRow] = []
    for person in ctx.persons:
        for shift in ctx.shifts:
            if not _assigned(solver, ctx.assignment_vars[(person.idx, shift.idx)]):
                continue
            if person.loc_flag(shift.location) == 1:
                rows.append(PenaltyRow(
                    component="location", person=person.name, units=1, weighted=weight,
                    extra={"date": shift.date, "day": shift.day, "location": shift.location, "team": shift.team},
                ))
    return rows


def compute_monthly_min_avail_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    month_to_shifts = group_shifts_by_month(ctx.shifts)
    rows: List[PenaltyRow] = []
    for person in ctx.persons:
        months_available = get_available_months(person, ctx.shifts)
        for m, s_indices in month_to_shifts.items():
            if m not in months_available:
                continue
            assigned = sum(_assigned(solver, ctx.assignment_vars[(person.idx, s)]) for s in s_indices)
            if assigned == 0:
                rows.append(PenaltyRow(
                    component="monthly_min_avail", person=person.name, units=1, weighted=weight,
                    extra={"month": m, "assigned_in_month": assigned},
                ))
    return rows


def compute_monthly_excess_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    month_to_shifts = group_shifts_by_month(ctx.shifts)
    rows: List[PenaltyRow] = []
    for person in ctx.persons:
        cap = person.month_max
        for m, s_indices in month_to_shifts.items():
            assigned = sum(_assigned(solver, ctx.assignment_vars[(person.idx, s)]) for s in s_indices)
            excess = max(0, assigned - cap)
            if excess > 0:
                rows.append(PenaltyRow(
                    component="monthly", person=person.name, units=excess, weighted=excess * weight,
                    extra={"month": m, "assigned_in_month": assigned, "cap": cap},
                ))
    return rows


def compute_fairness_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    counts = [sum(_assigned(solver, ctx.assignment_vars[(person.idx, shift.idx)]) for shift in ctx.shifts) for person in ctx.persons]
    span = (max(counts) if counts else 0) - (min(counts) if counts else 0)
    return [PenaltyRow(component="fairness", person="", units=span, weighted=span * weight)]


def compute_weekly_multi_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    week_to_shifts = group_shifts_by_iso_week(ctx.shifts)
    rows: List[PenaltyRow] = []
    for person in ctx.persons:
        for (y, w), s_indices in week_to_shifts.items():
            assigned = sum(_assigned(solver, ctx.assignment_vars[(person.idx, s)]) for s in s_indices)
            units = max(0, assigned - 1)
            if units > 0:
                rows.append(PenaltyRow(
                    component="weekly_multi", person=person.name, units=units, weighted=units * weight,
                    extra={"iso_year": y, "iso_week": w, "assigned_in_week": assigned},
                ))
    return rows


def compute_monthly_avg_rows(ctx: SolverContext, solver, weight: int) -> List[PenaltyRow]:
    from datetime import datetime
    ym_keys = {
        (datetime.strptime(s.date, "%Y-%m-%d").year, datetime.strptime(s.date, "%Y-%m-%d").month)
        for s in ctx.shifts
    }
    n_months = len(ym_keys)
    rows: List[PenaltyRow] = []
    for person in ctx.persons:
        target_total = person.month_avg * n_months
        assigned_total = sum(_assigned(solver, ctx.assignment_vars[(person.idx, shift.idx)]) for shift in ctx.shifts)
        deficit = max(0, target_total - assigned_total)
        if deficit > 0:
            rows.append(PenaltyRow(
                component="monthly_avg", person=person.name,
                units=deficit, weighted=weight * deficit * deficit,
                extra={
                    "months": n_months, "assigned_total": assigned_total,
                    "avg_per_month": person.month_avg, "target_total": target_total,
                },
            ))
    return rows


def export_penalties(
    ctx: SolverContext,
    solver,
    filepath: str,
) -> Tuple[List[PenaltyRow], Dict[str, Any]]:
    """Compute a long-form penalty list and write to CSV. Returns (rows, summary)."""
    weights = ctx.weights.as_dict()
    all_rows: List[PenaltyRow] = (
        compute_location_penalty_rows(ctx, solver, weights.get("location", 1))
        + compute_monthly_excess_rows(ctx, solver, weights.get("monthly", 1))
        + compute_fairness_rows(ctx, solver, weights.get("fairness", 1))
        + compute_monthly_avg_rows(ctx, solver, weights.get("monthly_avg", 1))
        + compute_monthly_min_avail_rows(ctx, solver, weights.get("monthly_min_avail", 1))
        + compute_weekly_multi_rows(ctx, solver, weights.get("weekly_multi", 1))
    )

    total_weighted = sum(r.weighted for r in all_rows)
    by_component: Dict[str, int] = defaultdict(int)
    for r in all_rows:
        by_component[r.component] += r.weighted

    summary = {"total_weighted": total_weighted, "by_component": dict(by_component)}

    row_dicts = [r.to_dict() for r in all_rows]
    fieldnames = sorted({k for d in row_dicts for k in d.keys()})
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row_dicts)

    summary_path = filepath.replace(".csv", "_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["component", "weighted_total"])
        for comp, val in by_component.items():
            writer.writerow([comp, val])
        writer.writerow(["__total__", total_weighted])

    return all_rows, summary