from datetime import datetime
import os
from typing import Dict
from config import get_locations_config

def _log(msg: str) -> None:
    """Print only when ROOSTER_VERBOSE env var is truthy."""
    if os.environ.get("ROOSTER_VERBOSE") not in (None, "", "0", "false", "False"):
        print(msg)



# Constraint 1: Niet plannen als iemand niet beschikbaar is
def add_availability_constraints(model, assignment_vars, person_list, shift_list):
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            # Als de tester niet beschikbaar is op deze datum, dan kan hij/zij niet worden ingepland,
            # of als de datum niet in de beschikbaarheidslijst staat, dan wel.
            if not tester["availability"].get(shift["date"], True):
                model.Add(assignment_vars[(t_idx, s_idx)] == 0)
                _log(
                    f"Adding constraint for {tester['name']} on {shift['day']} (not available)"
                )
            # New: hard location ban if Pref_Loc flag for location is 0
            flags = tester.get("pref_loc_flags", {})
            loc_flag = flags.get(shift["location"])
            if loc_flag == 0:
                model.Add(assignment_vars[(t_idx, s_idx)] == 0)
                _log(
                    f"Adding hard location ban for {tester['name']} at {shift['location']} on {shift['date']}"
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
            _log(
                f"Adding constraint for {tester['name']} on {date} (max 1 shift per day)"
            )


# Constraint 3: Precies 2 testers per shift
def add_exactly_x_testers_per_shift_constraints(
    model, assignment_vars, shift_list, person_list, x: int = 2
):
    """Enforce the exact number of testers per shift.

    Behavior:
    - If a shift's location has "peers": 0 in config/locations.json, then that shift
      requires exactly 1 tester (1 T, no peer).
    - Otherwise, use the legacy rule of exactly `x` testers (default 2).
    """
    # Build a map {location_name: peers_flag}
    loc_conf = get_locations_config()
    loc_peers: Dict[str, int] = {
        loc.get("name"): int(loc.get("peers", 1)) for loc in loc_conf.get("locations", [])
    }

    for s_idx, shift in enumerate(shift_list):
        loc = shift["location"]
        peers_flag = loc_peers.get(loc, 1)
        required_testers = 1 if peers_flag == 0 else x

        model.Add(
            sum(assignment_vars[(t_idx, s_idx)] for t_idx in range(len(person_list)))
            == required_testers
        )
        _log(
            f"Adding constraint for exactly {required_testers} testers on shift {s_idx} (loc={loc}, peers={peers_flag})"
        )


# Constraint 4: Minimaal 1 eerste tester per shift
def add_minimum_first_tester_per_shift_constraints(
    model, assignment_vars, person_list, shift_list
):
    for s_idx, shift in enumerate(shift_list):
        eerste_testers = [
            t_idx for t_idx, p in enumerate(person_list) if p["role"] == "T"
        ]
        model.Add(sum(assignment_vars[(t_idx, s_idx)] for t_idx in eerste_testers) >= 1)
        _log(f"Adding constraint for at least 1 first tester on shift {s_idx}")


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


# constraint 8: Maximaal x shifts per maand per persoon gebasseerd op voorkeuren.#
# Gebasseerd op de "Hoevaak PM Max" van de person_list
def calculate_max_x_shifts_per_month_penalty(
    assignment_vars, person_list, shift_list, max_shifts_per_month=1, penalty_weight=100
):

    monthnums = set(
        datetime.strptime(shift["date"], "%Y-%m-%d").month for shift in shift_list
    )
    penalty = 0
    for num in monthnums:
        for t_idx, tester in enumerate(person_list):
            shifts_this_month = [
                s_idx
                for s_idx, shift in enumerate(shift_list)
                if datetime.strptime(shift["date"], "%Y-%m-%d").month == num
            ]
            max_shifts = tester.get("month_max", max_shifts_per_month)
            total_shifts = sum(assignment_vars[t_idx, s_idx] for s_idx in shifts_this_month)
            excess = max(0, total_shifts - max_shifts)
            penalty += excess * penalty_weight
    return penalty


# Constraint 7: Maximaal 1 eerste tester per shift, tenzij er geen peers beschikbaar zijn
def add_single_first_tester_constraints(
    model, assignment_vars, shift_list, person_list
):
    """
    Dit zorgt ervoor dat er maximaal 1 eerste tester per shift is, tenzij er geen peers beschikbaar zijn.
    In dat geval is er geen beperking op het aantal eerste testers.
    TODO: Check of dit niet tot conflicten leidt door de max per maand regel
    """
    # Roles in person_list use 'T' (tester/eerste) and 'P' (peer)
    eerste_idx = [i for i, p in enumerate(person_list) if p["role"] == "T"]
    peer_idx = [i for i, p in enumerate(person_list) if p["role"] == "P"]

    for s_idx, shift in enumerate(shift_list):
        # Peers die beschikbaar zijn op deze dag
        beschikbare_peers = [
            t_idx
            for t_idx in peer_idx
            if person_list[t_idx]["availability"].get(shift["date"], True)
        ]

        if not beschikbare_peers:
            # Niemand beschikbaar → geen beperking op aantal eerste testers
            continue

        # Anders: we beperken het aantal eerste testers tot max 1
        model.Add(sum(assignment_vars[(t_idx, s_idx)] for t_idx in eerste_idx) <= 1)
