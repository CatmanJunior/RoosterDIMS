from models import Role, SolverContext


def print_available_people_for_shifts(ctx: SolverContext):
    for shift in ctx.shifts:
        beschikbaar = [p.name for p in ctx.persons if p.is_available(shift.date)]
        print(f"Shift {shift} -> Beschikbare mensen: {beschikbaar}")

    for shift in ctx.shifts:
        eerste = [p.name for p in ctx.persons if p.role == Role.TESTER and p.is_available(shift.date)]
        if len(eerste) < 1:
            print(f" Geen eerste tester beschikbaar op shift {shift}")
        print(f"Shift {shift} -> Beschikbare eerste testers: {eerste}")


def print_shift_schedule(ctx: SolverContext, solver):
    print("Rooster:")
    for date in set(s.date for s in ctx.shifts):
        print(f"\n{date}")
        for shift in ctx.shifts:
            if shift.date != date:
                continue
            assigned = [
                person.name
                for person in ctx.persons
                if solver.Value(ctx.assignment_vars[(person.idx, shift.idx)]) == 1
            ]
            print(f"  {shift.location} - team {shift.team}: {', '.join(assigned)}")


def print_shift_count_per_person(ctx: SolverContext, solver):
    print("\nAantal shifts per persoon:")
    for person in ctx.persons:
        count = sum(solver.Value(ctx.assignment_vars[(person.idx, shift.idx)]) for shift in ctx.shifts)
        print(f"{person.name} ({person.role.value}): {count} shifts")


def print_filled_shifts(shifts):
    print("Rooster:")
    for shift in shifts:
        print(f"{shift.location} - {shift.day} ({shift.date}) - Team {shift.team}: {', '.join(shift.testers)}")