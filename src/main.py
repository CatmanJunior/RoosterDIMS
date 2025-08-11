from ortools.sat.python import cp_model
from datetime import datetime
import argparse
import sys
from export import export_to_csv
from persons import csv_to_personlist
from shift_list import Filled_Shift, csv_to_shiftlist
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
    print_shift_count_per_person,
)
from penalties import export_penalties

# Parse CLI arguments early so globals below use the chosen CSV
parser = argparse.ArgumentParser(description="Run roster optimization")
parser.add_argument(
    "--csv",
    dest="csv_file",
    help="Path to the input CSV with persons and dates",
    default="data/Dummy_Test_Data_sanitized_november.csv",
)
parser.add_argument(
    "--shift-plan",
    dest="shift_plan",
    help="Path to a JSON file with per-date shift counts per location",
)
parser.add_argument(
    "--verbose",
    action="store_true",
    help="Print extra diagnostic information",
)
args, _ = parser.parse_known_args(sys.argv[1:])

EVEN_SHIFTS_WEIGHT = 5
PREF_LOCATION_WEIGHT = 1
MONTHLY_MAX_WEIGHT = 100  # penalty weight for exceeding personal monthly caps
MONTHLY_AVG_WEIGHT = 10  # penalty weight for not reaching personal monthly average

model = cp_model.CpModel()
csv_file = args.csv_file

# Optional: load a user-edited plan for shifts
plan = None
if getattr(args, "shift_plan", None):
    try:
        import json
        with open(args.shift_plan, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
            # Expecting { date: { location: count } }
            if isinstance(loaded, dict):
                plan = loaded
    except Exception:
        plan = None

shift_list = csv_to_shiftlist(csv_file, plan=plan)
person_list = csv_to_personlist(csv_file)

def create_assignment_vars():
    assignment_vars = {}
    # Maak een variabele voor elke combinatie van persoon en shift
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            assignment_vars[(t_idx, s_idx)] = model.NewBoolVar(
                f"{tester['name']}_op_{shift['location']}_{shift['day']}_team{shift['team']}_date_{shift['date']}"
            )

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
        model, assignment_vars, person_list, shift_list, max_shifts_per_week=2
    )

    add_single_first_tester_constraints(model, assignment_vars, shift_list, person_list)


    # Build monthly max-shifts excess variables (aux vars) for penalty
    monthly_excess_vars = build_monthly_max_excess_vars(
        model, assignment_vars, person_list, shift_list
    )

    # Build monthly average shortfall variables (aux vars) for penalty
    monthly_avg_deficit_vars = build_monthly_avg_deficit_vars(
        model, assignment_vars, person_list, shift_list
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
            if shift["location"] != tester["pref_location"]:
                # Boete als iemand niet op z'n voorkeurslocatie werkt
                penalties.append(assignment_vars[(t_idx, s_idx)])

    # Minimaliseer het totaal aantal keren dat mensen niet op hun voorkeurslocatie werken
    model.Minimize(
        # Boetes voor niet-voorkeurslocaties:
        sum(penalties) * PREF_LOCATION_WEIGHT
        +
        # Gelijke verdeling van shifts:
        (max_shifts - min_shifts) * EVEN_SHIFTS_WEIGHT
        +
        # Overschrijding persoonlijke maandlimieten:
    sum(monthly_excess_vars) * MONTHLY_MAX_WEIGHT
    +
    # Niet halen van persoonlijke maandgemiddelde (shortfall):
    sum(monthly_avg_deficit_vars) * MONTHLY_AVG_WEIGHT
    )


def build_monthly_max_excess_vars(model, assignment_vars, person_list, shift_list):
    """Create auxiliary variables representing max(0, assigned_in_month - month_cap)
    for each person and month. Returns a list of IntVars to be summed in the objective.

    Uses AddMaxEquality(excess, [diff, 0]) via a zero-constant IntVar.
    """
    # Map: month (1..12) -> list of shift indices in that month
    month_to_shifts = {}
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts.setdefault(m, []).append(s_idx)

    zero = model.NewIntVar(0, 0, "zero_const")
    excess_vars = []

    for t_idx, tester in enumerate(person_list):
        cap = int(tester.get("month_max", 0))
        for m, month_shifts in month_to_shifts.items():
            m_count = len(month_shifts)

            # diff = (sum assigned in month) - cap ; can be negative
            diff_lb = -cap
            diff_ub = m_count - cap
            diff = model.NewIntVar(diff_lb, diff_ub, f"diff_p{t_idx}_m{m}")
            model.Add(
                diff
                == sum(assignment_vars[(t_idx, s_idx)] for s_idx in month_shifts) - cap
            )

            # excess = max(diff, 0)
            excess_ub = max(0, diff_ub)
            excess = model.NewIntVar(0, excess_ub, f"excess_p{t_idx}_m{m}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)

    return excess_vars


def build_monthly_avg_deficit_vars(model, assignment_vars, person_list, shift_list):
    """Create auxiliary variables representing max(0, month_avg - assigned_in_month)
    for each person and month. Returns a list of IntVars to be summed in the objective.
    This penalizes shortfalls below the person's monthly average.
    """
    # Map: month (1..12) -> list of shift indices in that month
    month_to_shifts = {}
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts.setdefault(m, []).append(s_idx)

    zero = model.NewIntVar(0, 0, "zero_const_avg")
    deficit_vars = []

    for t_idx, tester in enumerate(person_list):
        target = int(tester.get("month_avg", 0))
        for m, month_shifts in month_to_shifts.items():
            m_count = len(month_shifts)
            # diff = target - (sum assigned in month); can be negative if target reached
            diff_lb = target - m_count
            diff_ub = target
            diff = model.NewIntVar(diff_lb, diff_ub, f"avg_diff_p{t_idx}_m{m}")
            model.Add(
                diff
                == target - sum(assignment_vars[(t_idx, s_idx)] for s_idx in month_shifts)
            )
            # deficit = max(diff, 0)
            deficit = model.NewIntVar(0, max(0, diff_ub), f"avg_deficit_p{t_idx}_m{m}")
            model.AddMaxEquality(deficit, [diff, zero])
            deficit_vars.append(deficit)

    return deficit_vars


def run_model():
    solver = cp_model.CpSolver()
    # solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    return solver, status


if __name__ == "__main__":
    # Toggle verbose logging in constraints and other modules if requested
    if args.verbose:
        import os as _os
        _os.environ["ROOSTER_VERBOSE"] = "1"

    if args.verbose:
        print_available_people_for_shifts(shift_list, person_list)

    assignment_vars = create_assignment_vars()
    add_constraints(model, assignment_vars)
    solver, status = run_model()

    filled_shifts = []

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # create a list of filled shifts
        for s_idx, shift in enumerate(shift_list):
            testers = [
                person_list[t_idx]["name"]
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
        # Export penalties breakdown
        export_penalties(
            filepath="penalties.csv",
            assignment_vars=assignment_vars,
            solver=solver,
            person_list=person_list,
            shift_list=shift_list,
            weights={
                "location": PREF_LOCATION_WEIGHT,
                "fairness": EVEN_SHIFTS_WEIGHT,
                "monthly": MONTHLY_MAX_WEIGHT,
                "monthly_avg": MONTHLY_AVG_WEIGHT,
            },
        )
    else:
        print("Geen oplossing gevonden.")
