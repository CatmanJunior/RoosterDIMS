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
