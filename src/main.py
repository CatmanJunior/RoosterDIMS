from ortools.sat.python import cp_model
from persons import person_list
from shift_list import shift_list
from constraints import (
    add_availability_constraints,
    add_max_shifts_per_day_constraints,
    add_exactly_x_testers_per_shift_constraints,
    add_minimum_first_tester_per_shift_constraints,
    add_max_x_shifts_per_week_constraints,
)
from debug import print_available_people_for_shifts

EVEN_SHIFTS_WEIGHT = 5
PREF_LOCATION_WEIGHT = 1

model = cp_model.CpModel()

assignment_vars = {}


print_available_people_for_shifts(shift_list, person_list)

# Maak een variabele voor elke combinatie van persoon en shift
for t_idx, tester in enumerate(person_list):
    for s_idx, shift in enumerate(shift_list):
        assignment_vars[(t_idx, s_idx)] = model.NewBoolVar(
            f"{tester['naam']}_op_{shift['location']}_{shift['day']}_team{shift['team']}_date_{shift['date']}"
        )

for key, value in assignment_vars.items():
    print(f"{key}: {value}")


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
    # Eerlijkheid:
    (max_shifts - min_shifts) * EVEN_SHIFTS_WEIGHT
)

solver = cp_model.CpSolver()
# solver.parameters.log_search_progress = True
status = solver.Solve(model)
if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    print("🗓️ -Rooster:")

    # groepeer eerst shifts per dag
    for date in set(shift["date"] for shift in shift_list):
        print(f"\n📅 {date}")
        for shift in shift_list:
            if shift["date"] != date:
                continue

            s_idx = shift_list.index(shift)
            ingedeelden = [
                person_list[t_idx]["naam"]
                for t_idx in range(len(person_list))
                if solver.Value(assignment_vars[(t_idx, s_idx)]) == 1
            ]

            team = f"team {shift['team']}"
            locatie = shift["location"]
            namen = ", ".join(ingedeelden)
            print(f"  📍 {locatie} - {team}: {namen}")
            
    # Print het aantal shifts per persoon
    print("\n👥 -Aantal shifts per persoon:")
    for tester in person_list:
        print(
            f"👤 {tester['naam']} ({tester['rol']}) - Voorkeur: {tester['voorkeur']} - Aantal shifts: "
        )
        aantal_shifts = sum(
            solver.Value(assignment_vars[(t_idx, s_idx)]) == 1
            for s_idx in range(len(shift_list))
            for t_idx in range(len(person_list))
            if person_list[t_idx]["naam"] == tester["naam"]
        )
        print(f"    {aantal_shifts} shifts")
else:
    print("Geen oplossing gevonden.")
