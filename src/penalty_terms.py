from __future__ import annotations

from datetime import datetime
from typing import List
from ortools.sat.python import cp_model

from models import SolverContext
from roster_utils import group_shifts_by_month, group_shifts_by_iso_week, get_available_months


def build_monthly_max_excess_vars(ctx: SolverContext) -> list:
    model, av = ctx.model, ctx.assignment_vars
    month_to_shifts = group_shifts_by_month(ctx.shifts)
    zero = model.NewIntVar(0, 0, "zero_const")
    excess_vars = []
    for person in ctx.persons:
        cap = person.month_max
        for m, month_shifts in month_to_shifts.items():
            m_count = len(month_shifts)
            diff = model.NewIntVar(-cap, m_count - cap, f"diff_p{person.idx}_m{m}")
            model.Add(diff == sum(av[(person.idx, s)] for s in month_shifts) - cap)
            excess = model.NewIntVar(0, max(0, m_count - cap), f"excess_p{person.idx}_m{m}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)
    return excess_vars


def build_monthly_avg_cost_vars(ctx: SolverContext, weight: int) -> list:
    model, av = ctx.model, ctx.assignment_vars
    ym_keys = {
        (datetime.strptime(s.date, "%Y-%m-%d").year, datetime.strptime(s.date, "%Y-%m-%d").month)
        for s in ctx.shifts
    }
    n_months = len(ym_keys)
    zero = model.NewIntVar(0, 0, "zero_const_avg_total")
    cost_vars = []
    total_shifts = len(ctx.shifts)
    for person in ctx.persons:
        target_total = person.month_avg * n_months
        diff = model.NewIntVar(target_total - total_shifts, target_total, f"avg_total_diff_p{person.idx}")
        model.Add(diff == target_total - sum(av[(person.idx, s.idx)] for s in ctx.shifts))
        deficit = model.NewIntVar(0, max(0, target_total), f"avg_total_deficit_p{person.idx}")
        model.AddMaxEquality(deficit, [diff, zero])
        costs = [weight * i * i for i in range(max(0, target_total) + 1)]
        cost_ub = costs[-1] if costs else 0
        cost_var = model.NewIntVar(0, cost_ub, f"avg_total_cost_p{person.idx}")
        model.AddElement(deficit, costs, cost_var)
        cost_vars.append(cost_var)
    return cost_vars


def build_weekly_multi_excess_vars(ctx: SolverContext) -> list:
    model, av = ctx.model, ctx.assignment_vars
    week_to_shifts = group_shifts_by_iso_week(ctx.shifts)
    zero = model.NewIntVar(0, 0, "zero_const_week")
    excess_vars = []
    for person in ctx.persons:
        for (y, w), week_shifts in week_to_shifts.items():
            mcount = len(week_shifts)
            diff = model.NewIntVar(-1, max(0, mcount - 1), f"wk_diff_p{person.idx}_{y}w{w}")
            model.Add(diff == sum(av[(person.idx, s)] for s in week_shifts) - 1)
            excess = model.NewIntVar(0, max(0, mcount - 1), f"wk_excess_p{person.idx}_{y}w{w}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)
    return excess_vars


def build_monthly_min_avail_missing_vars(ctx: SolverContext) -> list:
    model, av = ctx.model, ctx.assignment_vars
    month_to_shifts = group_shifts_by_month(ctx.shifts)
    missing_vars = []
    for person in ctx.persons:
        months_available = get_available_months(person, ctx.shifts)
        for m, s_indices in month_to_shifts.items():
            if m not in months_available:
                continue
            assigned_sum = model.NewIntVar(0, len(s_indices), f"ass_sum_p{person.idx}_m{m}")
            model.Add(assigned_sum == sum(av[(person.idx, s)] for s in s_indices))
            missing = model.NewBoolVar(f"miss_p{person.idx}_m{m}")
            model.Add(assigned_sum == 0).OnlyEnforceIf(missing)
            model.Add(assigned_sum >= 1).OnlyEnforceIf(missing.Not())
            missing_vars.append(missing)
    return missing_vars


def build_location_penalties(ctx: SolverContext) -> list:
    return [
        ctx.assignment_vars[(person.idx, shift.idx)]
        for person in ctx.persons
        for shift in ctx.shifts
        if person.loc_flag(shift.location) == 1
    ]


def build_location_penalty_span_vars(ctx: SolverContext):
    model, av = ctx.model, ctx.assignment_vars
    n_shifts = len(ctx.shifts)
    loc_penalty_counts = []
    for person in ctx.persons:
        terms = [
            av[(person.idx, shift.idx)]
            for shift in ctx.shifts
            if person.loc_flag(shift.location) == 1
        ]
        if terms:
            cnt = model.NewIntVar(0, len(terms), f"loc_penalty_count_p{person.idx}")
            model.Add(cnt == sum(terms))
        else:
            cnt = model.NewIntVar(0, 0, f"loc_penalty_count_p{person.idx}_zero")
            model.Add(cnt == 0)
        loc_penalty_counts.append(cnt)

    if not loc_penalty_counts:
        zero = model.NewIntVar(0, 0, "loc_penalty_span_zero")
        return zero, zero

    max_loc = model.NewIntVar(0, n_shifts, "max_loc_penalties")
    min_loc = model.NewIntVar(0, n_shifts, "min_loc_penalties")
    model.AddMaxEquality(max_loc, loc_penalty_counts)
    model.AddMinEquality(min_loc, loc_penalty_counts)
    return max_loc, min_loc


def build_fairness_span_vars(ctx: SolverContext):
    model, av = ctx.model, ctx.assignment_vars
    n = len(ctx.shifts)
    shifts_per_tester = [
        sum(av[(person.idx, shift.idx)] for shift in ctx.shifts)
        for person in ctx.persons
    ]
    max_shifts = model.NewIntVar(0, n, "max_shifts")
    min_shifts = model.NewIntVar(0, n, "min_shifts")
    model.AddMaxEquality(max_shifts, shifts_per_tester)
    model.AddMinEquality(min_shifts, shifts_per_tester)
    return max_shifts, min_shifts


def build_coverage_deficit_vars(ctx: SolverContext, target_per_shift: int = 2) -> list:
    """Per-shift deficit vars: max(0, target - assigned). Used in partial mode."""
    model, av = ctx.model, ctx.assignment_vars
    zero = model.NewIntVar(0, 0, "zero_const_cov")
    n = len(ctx.persons)
    deficit_vars = []
    for shift in ctx.shifts:
        total = sum(av[(p.idx, shift.idx)] for p in ctx.persons)
        assigned_var = model.NewIntVar(0, n, f"cov_assigned_s{shift.idx}")
        model.Add(assigned_var == total)
        diff = model.NewIntVar(-target_per_shift, target_per_shift, f"cov_diff_s{shift.idx}")
        model.Add(diff == target_per_shift - assigned_var)
        deficit = model.NewIntVar(0, target_per_shift, f"cov_deficit_s{shift.idx}")
        model.AddMaxEquality(deficit, [diff, zero])
        deficit_vars.append(deficit)
    return deficit_vars


def apply_objective(ctx: SolverContext) -> None:
    w = ctx.weights
    loc_penalties = build_location_penalties(ctx)
    monthly_excess = build_monthly_max_excess_vars(ctx)
    avg_costs = build_monthly_avg_cost_vars(ctx, w.monthly_avg)
    weekly_multi = build_weekly_multi_excess_vars(ctx)
    min_av_missing = build_monthly_min_avail_missing_vars(ctx)
    max_shifts, min_shifts = build_fairness_span_vars(ctx)
    max_loc_pen, min_loc_pen = build_location_penalty_span_vars(ctx)

    loc_fairness_w = w.location_fairness or w.fairness
    coverage_term = 0
    if w.coverage:
        coverage_deficits = build_coverage_deficit_vars(ctx)
        coverage_term = sum(coverage_deficits) * w.coverage

    expr = (
        sum(loc_penalties) * w.location
        + (max_shifts - min_shifts) * w.fairness
        + (max_loc_pen - min_loc_pen) * loc_fairness_w
        + sum(monthly_excess) * w.monthly
        + sum(avg_costs)  # already scaled by monthly_avg weight
        + sum(weekly_multi) * w.weekly_multi
        + sum(min_av_missing) * w.monthly_min_avail
        + coverage_term
    )
    ctx.model.Minimize(expr)