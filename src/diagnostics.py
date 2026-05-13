from collections import defaultdict

from ortools.sat.python import cp_model

from models import DiagnosticDay, Role, SolverContext, SolverResult


def diagnose_unplanned_days(ctx: SolverContext, result: SolverResult) -> list[DiagnosticDay]:
    solver, status = result.solver, result.status

    date_loc_required: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for shift in ctx.shifts:
        date_loc_required[shift.date][shift.location] += 1

    date_loc_avail_T: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    date_loc_avail_P: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for date, locs in date_loc_required.items():
        for loc in locs:
            avail = ctx.persons.filter_available_on(date).filter_location_not_banned(loc)
            date_loc_avail_T[date][loc] = len(avail.filter_role(Role.TESTER))
            date_loc_avail_P[date][loc] = len(avail.filter_role(Role.PEER))

    date_loc_assigned: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (t_idx, s_idx), var in ctx.assignment_vars.items():
            if solver.Value(var):
                sh = ctx.shifts[s_idx]
                date_loc_assigned[sh.date][sh.location] += 1

    tester_weeks: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (t_idx, s_idx), var in ctx.assignment_vars.items():
            if solver.Value(var):
                tester_weeks[t_idx][ctx.shifts[s_idx].weeknummer] += 1

    days: list[DiagnosticDay] = []
    for date, locs in sorted(date_loc_required.items()):
        for loc, required in locs.items():
            if required == 0:
                continue
            assigned = date_loc_assigned[date][loc]
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and assigned >= required:
                continue
            avail_T = date_loc_avail_T[date][loc]
            avail_P = date_loc_avail_P[date][loc]
            available = avail_T + avail_P
            c_avail = available == 0 or available * 2 < required
            c_max_day = not c_avail and assigned < required and available > 0
            week = next((sh.weeknummer for sh in ctx.shifts if sh.date == date and sh.location == loc), None)
            c_max_week = bool(
                week and sum(1 for t in range(len(ctx.persons)) if tester_weeks[t][week] >= 2) and assigned < required
            )
            c_first = not c_avail and assigned < required
            if available == 0:
                reason = "Geen testers beschikbaar voor deze locatie op deze dag."
            elif available * 2 < required:
                reason = "Te weinig beschikbare testers t.o.v. aantal teams."
            else:
                reason = "Mogelijk conflict tussen constraints (max per dag/week, single first, uitsluitingen)."
            days.append(DiagnosticDay(
                date=date, location=loc, required=int(required), assigned=int(assigned),
                available=int(available), available_T=int(avail_T), available_P=int(avail_P),
                reason=reason, c_availability=c_avail, c_max_per_day=c_max_day,
                c_max_per_week=c_max_week, c_single_first=c_first, c_exclusions=c_first,
            ))
    return days
