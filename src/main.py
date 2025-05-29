from ortools.sat.python import cp_model
from persons import person_list
from shift_list import shifts, days, di_dates, do_dates

EVEN_SHIFTS_WEIGHT = 2
PREF_LOCATION_WEIGHT = 1

model = cp_model.CpModel()

assignment_vars = {}

for s_idx, shift in enumerate(shifts):
    beschikbaar = [
        tester["naam"] for tester in person_list if tester["beschikbaar"][shift["date"]]
    ]
    print(f"Shift {shift} → Beschikbare mensen: {beschikbaar}")

for s_idx, shift in enumerate(shifts):
    beschikbare_eerste = [
        t["naam"]
        for t in person_list
        if t["rol"] == "eerste" and t["beschikbaar"][shift["date"]]
    ]
    if len(beschikbare_eerste) < 1:
        print(f" Geen eerste tester beschikbaar op shift {shift}")

    print(f"Shift {shift} → Beschikbare eerste testers: {beschikbare_eerste}")

for t_idx, tester in enumerate(person_list):
    for s_idx, shift in enumerate(shifts):
        assignment_vars[(t_idx, s_idx)] = model.NewBoolVar(
            f"{tester['naam']}_op_{shift['location']}_{shift['day']}_team{shift['team']}_date_{shift['date']}"
        )

for key, value in assignment_vars.items():
    print(f"{key}: {value}")

# Constraint 1: Niet plannen als iemand niet beschikbaar is
for t_idx, tester in enumerate(person_list):
    for s_idx, shift in enumerate(shifts):
        if not tester["beschikbaar"][shift["date"]]:
            model.Add(assignment_vars[(t_idx, s_idx)] == 0)
            print(
                f"Adding constraint for {tester['naam']} on {shift['day']} (not available)"
            )


# Constraint 2: Maximaal 1 shift per dag per persoon
for t_idx, tester in enumerate(person_list):
    for date in di_dates+do_dates:
        shifts_on_date = [s_idx for s_idx, shift in enumerate(shifts) if shift["date"] == date]
        model.Add(sum(assignment_vars[(t_idx, s_idx)] for s_idx in shifts_on_date) <= 1)
        print(f"Adding constraint for {tester['naam']} on {date} (max 1 shift per day)")

# Constraint 3: Precies 2 testers per shift
for s_idx, shift in enumerate(shifts):
    model.Add(
        sum(assignment_vars[(t_idx, s_idx)] for t_idx in range(len(person_list))) == 2
    )
    print(f"added constraint of exactly 2 testers on shift {s_idx}")

# Constraint 4: Minimaal 1 eerste tester per shift
for s_idx, shift in enumerate(shifts):
    eerste_testers = [
        t_idx for t_idx, p in enumerate(person_list) if p["rol"] == "eerste"
    ]
    model.Add(sum(assignment_vars[(t_idx, s_idx)] for t_idx in eerste_testers) >= 1)

shifts_per_tester = [
    sum(assignment_vars[(t_idx, s_idx)] for s_idx in range(len(shifts)))
    for t_idx in range(len(person_list))
]
max_shifts = model.NewIntVar(0, len(shifts), "max_shifts")
min_shifts = model.NewIntVar(0, len(shifts), "min_shifts")

model.AddMaxEquality(max_shifts, shifts_per_tester)
model.AddMinEquality(min_shifts, shifts_per_tester)

penalties = []

# Constraint 5: Voorkeurslocaties
for t_idx, tester in enumerate(person_list):
    for s_idx, shift in enumerate(shifts):
        if shift["location"] != tester["voorkeur"]:
            # Boete als iemand niet op z'n voorkeurslocatie werkt
            penalties.append(assignment_vars[(t_idx, s_idx)])

# Minimaliseer het totaal aantal keren dat mensen niet op hun voorkeurslocatie werken
model.Minimize(
    # Boetes voor niet-voorkeurslocaties:
    sum(penalties) * PREF_LOCATION_WEIGHT + 
    # Eerlijkheid:
    (max_shifts - min_shifts)* EVEN_SHIFTS_WEIGHT
)

solver = cp_model.CpSolver()
# solver.parameters.log_search_progress = True
status = solver.Solve(model)
if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    print("🗓️ -Rooster:")
    
    # groepeer eerst shifts per dag
    for date in di_dates+do_dates:
        print(f"\n📅 {date}")
        for shift in shifts:
            if shift["date"] != date:
                continue

            s_idx = shifts.index(shift)
            ingedeelden = [
                person_list[t_idx]["naam"]
                for t_idx in range(len(person_list))
                if solver.Value(assignment_vars[(t_idx, s_idx)]) == 1
            ]

            team = f"team {shift['team']}"
            locatie = shift["location"]
            namen = ", ".join(ingedeelden)
            print(f"  📍 {locatie} - {team}: {namen}")
    for tester in person_list:
        print(f"👤 {tester['naam']} ({tester['rol']}) - Voorkeur: {tester['voorkeur']} - Aantal shifts: ")
        aantal_shifts = sum(
            solver.Value(assignment_vars[(t_idx, s_idx)]) == 1
            for s_idx in range(len(shifts))
            for t_idx in range(len(person_list))
            if person_list[t_idx]["naam"] == tester["naam"]
        )
        print(f"    {aantal_shifts} shifts")
else:
    print("Geen oplossing gevonden.")
