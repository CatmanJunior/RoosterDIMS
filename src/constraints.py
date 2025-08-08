# Constraint 1: Niet plannen als iemand niet beschikbaar is
def add_availability_constraints(model, assignment_vars, person_list, shift_list):
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            # Als de tester niet beschikbaar is op deze datum, dan kan hij/zij niet worden ingepland,
            # of als de datum niet in de beschikbaarheidslijst staat, dan wel.
            if not tester["beschikbaar"].get(shift["date"], True):
                model.Add(assignment_vars[(t_idx, s_idx)] == 0)
                print(
                    f"Adding constraint for {tester['naam']} on {shift['day']} (not available)"
                )


# Constraint 2: Maximaal 1 shift per dag per persoon
def add_max_shifts_per_day_constraints(
    model, assignment_vars, person_list, shift_list, max_shifts=1
):
    for t_idx, tester in enumerate(person_list):
        for date in set(shift["date"] for shift in shift_list):
            shifts_on_date = [
                s_idx for s_idx, shift in enumerate(shift_list) if shift["date"] == date
            ]
            model.Add(
                sum(assignment_vars[(t_idx, s_idx)] for s_idx in shifts_on_date)
                <= max_shifts
            )
            print(
                f"Adding constraint for {tester['naam']} on {date} (max 1 shift per day)"
            )


# Constraint 3: Precies 2 testers per shift
def add_exactly_x_testers_per_shift_constraints(
    model, assignment_vars, shift_list, person_list, x=2
):
    for s_idx, shift in enumerate(shift_list):
        model.Add(
            sum(assignment_vars[(t_idx, s_idx)] for t_idx in range(len(person_list)))
            == x
        )
        print(f"Adding constraint for exactly {x} testers on shift {s_idx}")


# Constraint 4: Minimaal 1 eerste tester per shift
def add_minimum_first_tester_per_shift_constraints(
    model, assignment_vars, person_list, shift_list
):
    for s_idx, shift in enumerate(shift_list):
        eerste_testers = [
            t_idx for t_idx, p in enumerate(person_list) if p["rol"] == "eerste"
        ]
        model.Add(sum(assignment_vars[(t_idx, s_idx)] for t_idx in eerste_testers) >= 1)
        print(f"Adding constraint for at least 1 first tester on shift {s_idx}")


# Constraint 6: Maximaal x shifts per week per persoon
def add_max_x_shifts_per_week_constraints(
    model, assignment_vars, person_list, shift_list, max_shifts_per_week=1
):
    weeknums = set(shift["weeknummer"] for shift in shift_list)
    for num in weeknums:
        for t_idx, tester in enumerate(person_list):
            shifts_this_week = [
                s_idx
                for s_idx, shift in enumerate(shift_list)
                if shift["weeknummer"] == num
            ]
            model.Add(
                sum(assignment_vars[t_idx, s_idx] for s_idx in shifts_this_week)
                <= max_shifts_per_week
            )

# Constraint 7: Maximaal 1 eerste tester per shift, tenzij er geen peers beschikbaar zijn
def add_single_first_tester_constraints(model, assignment_vars, shift_list, person_list):
    """
    Dit zorgt ervoor dat er maximaal 1 eerste tester per shift is, tenzij er geen peers beschikbaar zijn.
    In dat geval is er geen beperking op het aantal eerste testers.
    """

    eerste_idx = [i for i, p in enumerate(person_list) if p["rol"] == "eerste"]
    peer_idx = [i for i, p in enumerate(person_list) if p["rol"] == "peer"]

    for s_idx, shift in enumerate(shift_list):
        

        # Peers die beschikbaar zijn op deze dag
        beschikbare_peers = [
            t_idx for t_idx in peer_idx if person_list[t_idx]["beschikbaar"].get(shift["date"], True)
        ]

        if not beschikbare_peers:
            # Niemand beschikbaar → geen beperking op aantal eerste testers
            continue

        # Anders: we beperken het aantal eerste testers tot max 1
        model.Add(sum(assignment_vars[(t_idx, s_idx)] for t_idx in eerste_idx) <= 1)
