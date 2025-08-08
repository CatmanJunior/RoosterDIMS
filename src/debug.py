def print_available_people_for_shifts(shift_list, person_list):
    for s_idx, shift in enumerate(shift_list):
        beschikbaar = [
            tester["naam"]
            for tester in person_list
            if tester["beschikbaar"].get(shift["date"], False)
        ]
        print(f"Shift {shift} → Beschikbare mensen: {beschikbaar}")

    for s_idx, shift in enumerate(shift_list):
        beschikbare_eerste = [
            t["naam"]
            for t in person_list
            if t["rol"] == "eerste" and t["beschikbaar"].get(shift["date"], False)
        ]
        if len(beschikbare_eerste) < 1:
            print(f" Geen eerste tester beschikbaar op shift {shift}")

        print(f"Shift {shift} → Beschikbare eerste testers: {beschikbare_eerste}")


def print_shift_schedule(assignment_vars, solver, shift_list, person_list):
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
def print_shift_count_per_person(assignment_vars, solver, shift_list, person_list):
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

def print_filled_shifts(filled_shifts):
    print("🗓️ -Rooster:")
    for shift in filled_shifts:
        print(
            f"📍 {shift.location} - {shift.day} ({shift.date}) - Team {shift.team}: {', '.join(shift.testers)}"
        )
