from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple
from ortools.sat.python import cp_model


def build_monthly_max_excess_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    month_to_shifts: Dict[int, List[int]] = {}
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts.setdefault(m, []).append(s_idx)

    zero = model.NewIntVar(0, 0, "zero_const")
    excess_vars = []

    for t_idx, tester in enumerate(person_list):
        cap = int(tester.get("month_max", 0))
        for m, month_shifts in month_to_shifts.items():
            m_count = len(month_shifts)
            diff_lb = -cap
            diff_ub = m_count - cap
            diff = model.NewIntVar(diff_lb, diff_ub, f"diff_p{t_idx}_m{m}")
            model.Add(
                diff == sum(assignment_vars[(t_idx, s_idx)] for s_idx in month_shifts) - cap
            )
            excess = model.NewIntVar(0, max(0, diff_ub), f"excess_p{t_idx}_m{m}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)

    return excess_vars


def build_monthly_avg_cost_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weight: int,
):
    ym_keys = set()
    for shift in shift_list:
        d = datetime.strptime(shift["date"], "%Y-%m-%d")
        ym_keys.add((d.year, d.month))
    n_months = len(ym_keys) if ym_keys else 0

    zero = model.NewIntVar(0, 0, "zero_const_avg_total")
    cost_vars = []
    total_shifts = len(shift_list)

    for t_idx, tester in enumerate(person_list):
        per_month = int(tester.get("month_avg", 0))
        target_total = per_month * n_months

        diff_lb = target_total - total_shifts
        diff_ub = target_total
        diff = model.NewIntVar(diff_lb, diff_ub, f"avg_total_diff_p{t_idx}")
        model.Add(
            diff
            == target_total - sum(assignment_vars[(t_idx, s_idx)] for s_idx in range(total_shifts))
        )

        deficit = model.NewIntVar(0, max(0, diff_ub), f"avg_total_deficit_p{t_idx}")
        model.AddMaxEquality(deficit, [diff, zero])

        costs = [weight * (i * i) for i in range(max(0, diff_ub) + 1)]
        cost_ub = costs[-1] if costs else 0
        cost_var = model.NewIntVar(0, cost_ub, f"avg_total_cost_p{t_idx}")
        model.AddElement(deficit, costs, cost_var)
        cost_vars.append(cost_var)

    return cost_vars


def build_weekly_multi_excess_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    from datetime import datetime as _dt

    week_to_shifts: Dict[Tuple[int, int], List[int]] = {}
    for s_idx, shift in enumerate(shift_list):
        d = _dt.strptime(shift["date"], "%Y-%m-%d")
        iso_year, iso_week, _ = d.isocalendar()
        week_to_shifts.setdefault((iso_year, iso_week), []).append(s_idx)

    zero = model.NewIntVar(0, 0, "zero_const_week")
    excess_vars = []
    for t_idx, _tester in enumerate(person_list):
        for (y, w), week_shifts in week_to_shifts.items():
            mcount = len(week_shifts)
            diff = model.NewIntVar(-1, max(0, mcount - 1), f"wk_diff_p{t_idx}_{y}w{w}")
            model.Add(diff == sum(assignment_vars[(t_idx, s)] for s in week_shifts) - 1)
            excess = model.NewIntVar(0, max(0, mcount - 1), f"wk_excess_p{t_idx}_{y}w{w}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)
    return excess_vars


def build_monthly_min_avail_missing_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    month_to_shifts: Dict[int, List[int]] = {}
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts.setdefault(m, []).append(s_idx)

    missing_vars = []
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
            assigned_sum = model.NewIntVar(0, len(s_indices), f"ass_sum_p{t_idx}_m{m}")
            model.Add(assigned_sum == sum(assignment_vars[(t_idx, s)] for s in s_indices))
            missing = model.NewBoolVar(f"miss_p{t_idx}_m{m}")
            model.Add(assigned_sum == 0).OnlyEnforceIf(missing)
            model.Add(assigned_sum >= 1).OnlyEnforceIf(missing.Not())
            missing_vars.append(missing)
    return missing_vars


def build_location_penalties(
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    penalties = []
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            flags = tester.get("pref_loc_flags", {})
            flag = flags.get(shift["location"]) if flags else None
            if flag is None:
                if tester.get("pref_location") and shift["location"] != tester["pref_location"]:
                    penalties.append(assignment_vars[(t_idx, s_idx)])
            else:
                if flag == 1:  # penalize
                    penalties.append(assignment_vars[(t_idx, s_idx)])
    return penalties


def build_location_penalty_span_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    """
    Build max/min variables for per-tester location-penalty counts.

    Encourages spreading 'bad location' assignments over testers instead of
    loading them onto a few people.
    Returns (max_loc_pen, min_loc_pen)
    """
    n_shifts = len(shift_list)

    loc_penalty_counts = []
    for t_idx, tester in enumerate(person_list):
        terms = []
        flags_map = tester.get("pref_loc_flags", {}) or {}
        pref_fallback = tester.get("pref_location")
        for s_idx, shift in enumerate(shift_list):
            loc = shift["location"]
            flag = flags_map.get(loc) if flags_map else None

            bad_here = False
            if flag is None:
                if pref_fallback and loc != pref_fallback:
                    bad_here = True
            else:
                if flag == 1:
                    bad_here = True

            if bad_here:
                terms.append(assignment_vars[(t_idx, s_idx)])

        if terms:
            cnt = model.NewIntVar(0, len(terms), f"loc_penalty_count_p{t_idx}")
            model.Add(cnt == sum(terms))
        else:
            cnt = model.NewIntVar(0, 0, f"loc_penalty_count_p{t_idx}_zero")
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


def build_fairness_span_vars(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
):
    shifts_per_tester = [
        sum(assignment_vars[(t_idx, s_idx)] for s_idx in range(len(shift_list)))
        for t_idx in range(len(person_list))
    ]
    max_shifts = model.NewIntVar(0, len(shift_list), "max_shifts")
    min_shifts = model.NewIntVar(0, len(shift_list), "min_shifts")
    model.AddMaxEquality(max_shifts, shifts_per_tester)
    model.AddMinEquality(min_shifts, shifts_per_tester)
    return max_shifts, min_shifts


def apply_objective(
    model: cp_model.CpModel,
    assignment_vars,
    person_list: List[Dict[str, Any]],
    shift_list: List[Dict[str, Any]],
    weights: Dict[str, int],
):
    loc_penalties = build_location_penalties(assignment_vars, person_list, shift_list)
    monthly_excess = build_monthly_max_excess_vars(model, assignment_vars, person_list, shift_list)
    avg_costs = build_monthly_avg_cost_vars(model, assignment_vars, person_list, shift_list, weights.get("monthly_avg", 0))
    weekly_multi = build_weekly_multi_excess_vars(model, assignment_vars, person_list, shift_list)
    min_av_missing = build_monthly_min_avail_missing_vars(model, assignment_vars, person_list, shift_list)
    max_shifts, min_shifts = build_fairness_span_vars(model, assignment_vars, person_list, shift_list)
    # Location-penalty fairness: try to spread bad-location assignments across testers
    max_loc_pen, min_loc_pen = build_location_penalty_span_vars(model, assignment_vars, person_list, shift_list)

    # location_fairness allows tuning how strongly we prefer spreading location penalties
    loc_fairness_w = weights.get("location_fairness", weights.get("fairness", 0))
    expr = (
        sum(loc_penalties) * weights.get("location", 0)
        + (max_shifts - min_shifts) * weights.get("fairness", 0)
        + (max_loc_pen - min_loc_pen) * loc_fairness_w
        + sum(monthly_excess) * weights.get("monthly", 0)
        + sum(avg_costs)  # already scaled by monthly_avg weight
        + sum(weekly_multi) * weights.get("weekly_multi", 0)
        + sum(min_av_missing) * weights.get("monthly_min_avail", 0)
    )
    model.Minimize(expr)
