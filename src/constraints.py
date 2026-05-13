import json
import os
from pathlib import Path

from models import Role, SolverContext
from penalty_terms import apply_objective


def _log(msg: str) -> None:
    """Print only when ROOSTER_VERBOSE env var is truthy."""
    if os.environ.get("ROOSTER_VERBOSE") not in (None, "", "0", "false", "False"):
        print(msg)


# Constraint 1: Niet plannen als iemand niet beschikbaar is
def add_availability_constraints(ctx: SolverContext) -> None:
    model, av = ctx.model, ctx.assignment_vars
    for person in ctx.persons:
        for shift in ctx.shifts:
            if person.role == Role.PEER and not shift.allow_peer:
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Blocking peer assignment for {person.name} on {shift.date} (loc={shift.location})")
                continue
            if person.role == Role.TESTER and not shift.allow_tester:
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Blocking tester assignment for {person.name} on {shift.date} (loc={shift.location})")
                continue
            if not person.is_available(shift.date):
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Adding constraint for {person.name} on {shift.day} (not available)")
            if person.loc_flag(shift.location) == 0:
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Adding hard location ban for {person.name} at {shift.location} on {shift.date}")
            if shift.date in person.date_loc2_only and shift.location != person.date_loc2_only[shift.date]:
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Blocking {person.name} at {shift.location} on {shift.date} (only available at {person.date_loc2_only[shift.date]})")
            if shift.date in person.date_loc2_banned and shift.location == person.date_loc2_banned[shift.date]:
                model.Add(av[(person.idx, shift.idx)] == 0)
                _log(f"Blocking {person.name} at {shift.location} on {shift.date} (banned from location 2)")


# Constraint 2: Maximaal 1 shift per dag per persoon
def add_max_shifts_per_day_constraints(ctx: SolverContext, max_shifts: int = 1) -> None:
    model, av = ctx.model, ctx.assignment_vars
    dates = ctx.shifts.dates()
    for person in ctx.persons:
        for date in dates:
            day_shifts = [s.idx for s in ctx.shifts.filter_date(date)]
            model.Add(sum(av[(person.idx, s_idx)] for s_idx in day_shifts) <= max_shifts)
            _log(f"Adding constraint for {person.name} on {date} (max 1 shift per day)")


# Constraint 3: Precies 2 testers per shift (of minimaal min_x in partieel modus)
def add_exactly_x_testers_per_shift_constraints(
    ctx: SolverContext, x: int = 2, min_x: int | None = None
) -> None:
    model, av = ctx.model, ctx.assignment_vars
    for shift in ctx.shifts:
        total = sum(av[(p.idx, shift.idx)] for p in ctx.persons)
        if min_x is not None:
            model.Add(total <= x)
            model.Add(total >= min_x)
            _log(f"Adding constraint for {min_x}-{x} testers on shift {shift.idx} (loc={shift.location})")
        else:
            model.Add(total == x)
            _log(f"Adding constraint for exactly {x} testers on shift {shift.idx} (loc={shift.location})")


# Constraint 4: Minimaal 1 eerste tester per shift
def add_minimum_first_tester_per_shift_constraints(ctx: SolverContext, partial: bool = False) -> None:
    model, av = ctx.model, ctx.assignment_vars
    tester_idxs = [p.idx for p in ctx.persons.filter_role(Role.TESTER)]
    all_idxs = [p.idx for p in ctx.persons]
    for shift in ctx.shifts:
        if not shift.allow_tester:
            continue
        n_testers = sum(av[(t_idx, shift.idx)] for t_idx in tester_idxs)
        if partial:
            # If any person is assigned, at least one must be a tester.
            # total <= 2 * n_testers: when total=1 or 2, n_testers must be >= 1.
            # When total=0 the inequality is trivially satisfied (0 <= 0).
            total = sum(av[(p_idx, shift.idx)] for p_idx in all_idxs)
            model.Add(total <= 2 * n_testers)
        else:
            model.Add(n_testers >= 1)
        _log(f"Adding min_first constraint (partial={partial}) for shift {shift.idx}")


# Constraint: Maximaal x shifts per week per persoon
def add_max_x_shifts_per_week_constraints(
    ctx: SolverContext, max_shifts_per_week: int = 1
) -> None:
    model, av = ctx.model, ctx.assignment_vars
    weeknums = set(s.weeknummer for s in ctx.shifts)
    for num in weeknums:
        week_shifts = [s.idx for s in ctx.shifts.filter_week(num)]
        for person in ctx.persons:
            model.Add(sum(av[(person.idx, s_idx)] for s_idx in week_shifts) <= max_shifts_per_week)


# Constraint: Maximaal 1 eerste tester per shift, tenzij er geen peers beschikbaar zijn
def add_single_first_tester_constraints(ctx: SolverContext) -> None:
    model, av = ctx.model, ctx.assignment_vars
    tester_idxs = [p.idx for p in ctx.persons.filter_role(Role.TESTER)]

    for shift in ctx.shifts:
        if not shift.allow_peer:
            continue
        if not ctx.persons.filter_role(Role.PEER).filter_available_on(shift.date):
            continue
        model.Add(sum(av[(t_idx, shift.idx)] for t_idx in tester_idxs) <= 1)


def _apply_mutual_exclusions(ctx: SolverContext) -> None:
    try:
        excl_path = Path("data") / "mutual_exclusions.json"
        if not excl_path.exists():
            return
        exclusions = json.loads(excl_path.read_text(encoding="utf-8"))
        if not exclusions:
            return
        name_to_idx = {p.name: p.idx for p in ctx.persons}
        date_to_shifts: dict[str, list[int]] = {}
        for shift in ctx.shifts:
            date_to_shifts.setdefault(shift.date, []).append(shift.idx)
        for pair in exclusions:
            if not pair or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if a not in name_to_idx or b not in name_to_idx:
                continue
            a_idx, b_idx = name_to_idx[a], name_to_idx[b]
            for shift_idxs in date_to_shifts.values():
                va = [ctx.assignment_vars[(a_idx, s)] for s in shift_idxs if (a_idx, s) in ctx.assignment_vars]
                vb = [ctx.assignment_vars[(b_idx, s)] for s in shift_idxs if (b_idx, s) in ctx.assignment_vars]
                if va or vb:
                    ctx.model.Add(sum(va + vb) <= 1)
    except Exception:
        pass


def add_constraints(ctx: SolverContext, use_constraints: set[str], allow_partial: bool = False) -> None:
    active = use_constraints
    partial = allow_partial

    for key, fn in {
        "availability": add_availability_constraints,
        "max_per_day": add_max_shifts_per_day_constraints,
    }.items():
        if key in active:
            fn(ctx)

    if "exact_testers" in active:
        add_exactly_x_testers_per_shift_constraints(ctx, x=2, min_x=0 if partial else None)
    if "min_first" in active:
        add_minimum_first_tester_per_shift_constraints(ctx, partial=partial)
    if "max_per_week" in active:
        add_max_x_shifts_per_week_constraints(ctx, max_shifts_per_week=2)
    if "single_first" in active:
        add_single_first_tester_constraints(ctx)
    _apply_mutual_exclusions(ctx)

    apply_objective(ctx)