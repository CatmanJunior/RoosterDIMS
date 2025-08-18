from ortools.sat.python import cp_model
from datetime import datetime
import argparse
import sys
from export import export_to_csv
from pathlib import Path
from config import get_data_sources_config
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

default_csv = get_data_sources_config().get("default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv")

# Parse CLI arguments early so globals below use the chosen CSV
parser = argparse.ArgumentParser(description="Run roster optimization")
parser.add_argument(
    "--csv",
    dest="csv_file",
    help="Path to the input CSV with persons and dates",
    default=default_csv,
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
MONTHLY_AVG_WEIGHT = 20  # penalty weight for not reaching personal monthly average
WEEKLY_MULTI_WEIGHT = 15  # penalty weight per extra shift beyond 1 per week
MONTHLY_MIN_AVAIL_WEIGHT = 50  # penalty: available in month but assigned 0 shifts

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

    # Build monthly average shortfall cost variables (aux vars) for penalty
    # Computed once over the full roster period per person and using a
    # non-linear (quadratic) cost curve: cost = weight * deficit^2
    monthly_avg_cost_vars = build_monthly_avg_cost_vars(
        model, assignment_vars, person_list, shift_list, MONTHLY_AVG_WEIGHT
    )

    # Build weekly multiple-assignments excess vars: max(0, assigned_in_week - 1)
    weekly_multi_excess_vars = build_weekly_multi_excess_vars(
        model, assignment_vars, person_list, shift_list
    )

    # Build per-person/month indicator vars for missing assignment while available
    monthly_min_avail_missing_vars = build_monthly_min_avail_missing_vars(
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

    # Constraint 6: Voorkeurslocaties met nieuwe flags
    for t_idx, tester in enumerate(person_list):
        for s_idx, shift in enumerate(shift_list):
            flags = tester.get("pref_loc_flags", {})
            flag = flags.get(shift["location"], None)
            if flag is None:
                # Fallback to legacy single preferred location string
                if tester.get("pref_location") and shift["location"] != tester["pref_location"]:
                    penalties.append(assignment_vars[(t_idx, s_idx)])
            else:
                # 0 is handled as hard ban in constraints
                # 1 = penalize assignments on this location
                # 2 = no penalty for this location
                if flag == 1:
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
        # non-linear quadratic cost already scaled by MONTHLY_AVG_WEIGHT
    sum(monthly_avg_cost_vars)
    +
    # Meer dan 1 shift in dezelfde week voor dezelfde persoon
    sum(weekly_multi_excess_vars) * WEEKLY_MULTI_WEIGHT
    +
    # Per-month minimum: if a person was available in that month but got 0 shifts
    sum(monthly_min_avail_missing_vars) * MONTHLY_MIN_AVAIL_WEIGHT
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


def build_monthly_avg_cost_vars(model, assignment_vars, person_list, shift_list, weight: int):
    """Create cost variables for monthly average shortfall per person over the entire roster.

    Steps per person:
    1) deficit = max(0, month_avg * N_months - assigned_total)
    2) cost = weight * deficit^2 (modeled via an Element constraint over a precomputed table)
    Returns a list of cost IntVars to be summed in the objective.
    """
    # Determine distinct year-months present in the roster
    ym_keys = set()
    for shift in shift_list:
        d = datetime.strptime(shift["date"], "%Y-%m-%d")
        ym_keys.add((d.year, d.month))
    n_months = len(ym_keys) if ym_keys else 0

    zero = model.NewIntVar(0, 0, "zero_const_avg_total")
    cost_vars = []

    total_shifts = len(shift_list)

    for t_idx, tester in enumerate(person_list):
        per_month = int(tester.get("month_avg", 0))
        target_total = per_month * n_months

        # diff = target_total - assigned_total
        # assigned_total ranges in [0, total_shifts]
        diff_lb = target_total - total_shifts
        diff_ub = target_total
        diff = model.NewIntVar(diff_lb, diff_ub, f"avg_total_diff_p{t_idx}")
        model.Add(
            diff
            == target_total - sum(assignment_vars[(t_idx, s_idx)] for s_idx in range(total_shifts))
        )

        # deficit = max(diff, 0)
        deficit_ub = max(0, diff_ub)
        deficit = model.NewIntVar(0, deficit_ub, f"avg_total_deficit_p{t_idx}")
        model.AddMaxEquality(deficit, [diff, zero])

        # Non-linear cost via element: cost = weight * deficit^2
        # Build cost table for indices 0..deficit_ub
        costs = [weight * (i * i) for i in range(deficit_ub + 1)]
        # Upper bound for cost var
        cost_ub = costs[-1] if costs else 0
        cost_var = model.NewIntVar(0, cost_ub, f"avg_total_cost_p{t_idx}")
        model.AddElement(deficit, costs, cost_var)
        cost_vars.append(cost_var)

    return cost_vars


def build_weekly_multi_excess_vars(model, assignment_vars, person_list, shift_list):
    """Create auxiliary vars for per-person, per-week extra assignments beyond 1.

    For each person and ISO (year, week):
      diff = (assigned_in_week) - 1
      excess = max(diff, 0)
    Return list of excess vars to be summed in the objective.
    """
    from datetime import datetime as _dt

    # Map: (iso_year, iso_week) -> list of shift indices
    week_to_shifts = {}
    for s_idx, shift in enumerate(shift_list):
        d = _dt.strptime(shift["date"], "%Y-%m-%d")
        iso_year, iso_week, _ = d.isocalendar()
        week_to_shifts.setdefault((iso_year, iso_week), []).append(s_idx)

    zero = model.NewIntVar(0, 0, "zero_const_week")
    excess_vars = []
    for t_idx, _tester in enumerate(person_list):
        for (y, w), week_shifts in week_to_shifts.items():
            mcount = len(week_shifts)
            # diff in [-1, mcount-1]
            diff = model.NewIntVar(-1, max(0, mcount - 1), f"wk_diff_p{t_idx}_{y}w{w}")
            model.Add(diff == sum(assignment_vars[(t_idx, s)] for s in week_shifts) - 1)
            excess = model.NewIntVar(0, max(0, mcount - 1), f"wk_excess_p{t_idx}_{y}w{w}")
            model.AddMaxEquality(excess, [diff, zero])
            excess_vars.append(excess)
    return excess_vars


def build_monthly_min_avail_missing_vars(model, assignment_vars, person_list, shift_list):
    """For each person and each month present in shift_list, if the person has any
    availability True in that month but is assigned zero shifts in that month,
    create a BoolVar 'missing' that is 1; otherwise 0. Return list of these vars.
    """
    # Month -> shift indices in that month
    month_to_shifts = {}
    for s_idx, shift in enumerate(shift_list):
        m = datetime.strptime(shift["date"], "%Y-%m-%d").month
        month_to_shifts.setdefault(m, []).append(s_idx)

    missing_vars = []
    for t_idx, tester in enumerate(person_list):
        avail_map = tester.get("availability", {}) or {}
        # Precompute months where this person has at least one available day
        months_available = set()
        for dstr, ok in avail_map.items():
            try:
                if ok:
                    m = datetime.strptime(dstr, "%Y-%m-%d").month
                    months_available.add(m)
            except Exception:
                continue

        for m, s_indices in month_to_shifts.items():
            if m not in months_available:
                continue  # no requirement if they were never available that month
            # Sum of assignments this month
            assigned_sum = model.NewIntVar(0, len(s_indices), f"ass_sum_p{t_idx}_m{m}")
            model.Add(assigned_sum == sum(assignment_vars[(t_idx, s)] for s in s_indices))
            # missing == 1 iff assigned_sum == 0
            missing = model.NewBoolVar(f"miss_p{t_idx}_m{m}")
            model.Add(assigned_sum == 0).OnlyEnforceIf(missing)
            model.Add(assigned_sum >= 1).OnlyEnforceIf(missing.Not())
            missing_vars.append(missing)

    return missing_vars


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

        # Resolve export paths from config and ensure directory exists
        ds_conf = get_data_sources_config()
        roster_path = ds_conf.get("roster_csv", "rooster.csv")
        penalties_path = ds_conf.get("penalties_csv", "penalties.csv")
        try:
            Path(roster_path).parent.mkdir(parents=True, exist_ok=True)
            Path(penalties_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        export_to_csv([entry.to_dict() for entry in filled_shifts], roster_path)
        # Export penalties breakdown (summary will be written next to penalties_path as *_summary.csv)
        export_penalties(
            filepath=penalties_path,
            assignment_vars=assignment_vars,
            solver=solver,
            person_list=person_list,
            shift_list=shift_list,
            weights={
                "location": PREF_LOCATION_WEIGHT,
                "fairness": EVEN_SHIFTS_WEIGHT,
                "monthly": MONTHLY_MAX_WEIGHT,
                "monthly_avg": MONTHLY_AVG_WEIGHT,
                "weekly_multi": WEEKLY_MULTI_WEIGHT,
                "monthly_min_avail": MONTHLY_MIN_AVAIL_WEIGHT,
            },
        )
    else:
        print("Geen oplossing gevonden.")
