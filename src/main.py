from ortools.sat.python import cp_model
from export import export_to_csv
from persons import person_list
from shift_list import shift_list, Filled_Shift
from constraints import (
    add_availability_constraints,
    add_single_first_tester_constraints,
    add_max_shifts_per_day_constraints,
    add_exactly_x_testers_per_shift_constraints,
    add_minimum_first_tester_per_shift_constraints,
    add_max_x_shifts_per_week_constraints,
)
from debug import (
    print_available_people_for_shifts,
    print_filled_shifts,
    print_shift_schedule,
    print_shift_count_per_person,
)

EVEN_SHIFTS_WEIGHT = 5
PREF_LOCATION_WEIGHT = 1

model = cp_model.CpModel()


def create_assignment_vars():
    assignment_vars = {}
    # Maak een variabele voor elke combinatie van persoon en shift
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            assignment_vars[(t_idx, s_idx)] = model.NewBoolVar(
                f"{tester['naam']}_op_{shift['location']}_{shift['day']}_team{shift['team']}_date_{shift['date']}"
            )

    for key, value in assignment_vars.items():
        print(f"{key}: {value}")

    return assignment_vars


def add_constraints(model, assignment_vars):
    add_availability_constraints(model, assignment_vars, person_list, shift_list)

    add_max_shifts_per_day_constraints(
        model, assignment_vars, person_list, shift_list, max_shifts=1
    )

    add_exactly_x_testers_per_shift_constraints(
        model, assignment_vars, shift_list, person_list, x=2
    )

    add_minimum_first_tester_per_shift_constraints(
        model, assignment_vars, person_list, shift_list
    )

    add_max_x_shifts_per_week_constraints(
        model, assignment_vars, person_list, shift_list, max_shifts_per_week=1
    )

    add_single_first_tester_constraints(
        model, assignment_vars, shift_list, person_list
    )

    # Constraint 5: Evenwichtige verdeling van shifts
    shifts_per_tester = [
        sum(assignment_vars[(t_idx, s_idx)] for s_idx in range(len(shift_list)))
        for t_idx in range(len(person_list))
    ]
    max_shifts = model.NewIntVar(0, len(shift_list), "max_shifts")
    min_shifts = model.NewIntVar(0, len(shift_list), "min_shifts")

    model.AddMaxEquality(max_shifts, shifts_per_tester)
    model.AddMinEquality(min_shifts, shifts_per_tester)

    penalties = []

    # Constraint 6: Voorkeurslocaties
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            if shift["location"] != tester["voorkeur"]:
                # Boete als iemand niet op z'n voorkeurslocatie werkt
                penalties.append(assignment_vars[(t_idx, s_idx)])

    # Minimaliseer het totaal aantal keren dat mensen niet op hun voorkeurslocatie werken
    model.Minimize(
        # Boetes voor niet-voorkeurslocaties:
        sum(penalties) * PREF_LOCATION_WEIGHT
        +
        # Gelijke shifts:
        (max_shifts - min_shifts) * EVEN_SHIFTS_WEIGHT
    )





def run_model():
    solver = cp_model.CpSolver()
    # solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    return solver, status


if __name__ == "__main__":
    print_available_people_for_shifts(shift_list, person_list)

    assignment_vars = create_assignment_vars()
    add_constraints(model, assignment_vars)
    solver, status = run_model()

    filled_shifts = []

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # create a list of filled shifts
        for s_idx, shift in enumerate(shift_list):
            testers = [
                person_list[t_idx]["naam"]
                for t_idx in range(len(person_list))
                if solver.Value(assignment_vars[(t_idx, s_idx)]) == 1
            ]
            filled_shifts.append(
                Filled_Shift(
                    location=shift["location"],
                    day=shift["day"],
                    date=shift["date"],
                    weeknummer=shift["weeknummer"],
                    team=shift["team"],
                    testers=testers,
                )
            )

        print_filled_shifts(filled_shifts)
        print_shift_count_per_person(assignment_vars, solver, shift_list, person_list)
        export_to_csv([entry.to_dict() for entry in filled_shifts], "rooster.csv")
    else:
        print("Geen oplossing gevonden.")
