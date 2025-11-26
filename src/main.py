from ortools.sat.python import cp_model
import argparse
import sys
from export import export_to_csv
from pathlib import Path
from config import get_data_sources_config, get_weights_config
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
from penalty_terms import apply_objective

default_csv = get_data_sources_config().get(
    "default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv"
)

# Parse CLI arguments early so globals below use the chosen CSV
parser = argparse.ArgumentParser(description="Run roster optimization")
parser.add_argument(
    "--csv",
    dest="csv_file",
    help="Path to the input CSV with persons and dates",
    default=default_csv,
)
# Deprecated: --shift-plan (use config/locations.json teams_per_date via UI)
parser.add_argument(
    "--weights", dest="weights_path", help="Path to weights JSON (overrides default)"
)
parser.add_argument(
    "--use-constraints",
    dest="use_constraints",
    nargs="*",
    default=[
        "availability",
        "max_per_day",
        "exact_testers",
        "min_first",
        "max_per_week",
        "single_first",
    ],
    help=(
        "Constraints to apply: availability, max_per_day, exact_testers, "
        "min_first, max_per_week, single_first"
    ),
)
parser.add_argument(
    "--use-objectives",
    dest="use_objectives",
    nargs="*",
    default=[
        "location",
        "fairness",
        "monthly",
        "monthly_avg",
        "weekly_multi",
        "monthly_min_avail",
    ],
    help=(
        "Objectives/penalties to apply: location, fairness, monthly, monthly_avg, weekly_multi, monthly_min_avail"
    ),
)
parser.add_argument(
    "--verbose",
    action="store_true",
    help="Print extra diagnostic information",
)
parser.add_argument(
    "--year",
    dest="year",
    type=int,
    default=2026,
    help="Year for the roster (default: 2026)",
)
args, _ = parser.parse_known_args(sys.argv[1:])

WEIGHTS = (
    get_weights_config(args.weights_path)
    if getattr(args, "weights_path", None)
    else get_weights_config()
)
# Build only selected objective components by masking weights (module-scope so we can reuse after solving)
_SEL_OBJECTIVES = set(args.use_objectives)
MASKED_WEIGHTS = {
    "location": WEIGHTS.get("location", 0) if "location" in _SEL_OBJECTIVES else 0,
    "fairness": WEIGHTS.get("fairness", 0) if "fairness" in _SEL_OBJECTIVES else 0,
    "monthly": WEIGHTS.get("monthly", 0) if "monthly" in _SEL_OBJECTIVES else 0,
    "monthly_avg": WEIGHTS.get("monthly_avg", 0)
    if "monthly_avg" in _SEL_OBJECTIVES
    else 0,
    "weekly_multi": WEIGHTS.get("weekly_multi", 0)
    if "weekly_multi" in _SEL_OBJECTIVES
    else 0,
    "monthly_min_avail": WEIGHTS.get("monthly_min_avail", 0)
    if "monthly_min_avail" in _SEL_OBJECTIVES
    else 0,
}

model = cp_model.CpModel()
csv_file = args.csv_file

# Build shifts using locations.json configuration (teams_per_date preferred)
shift_list = csv_to_shiftlist(csv_file)
person_list = csv_to_personlist(csv_file, year=args.year)


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
    if "availability" in args.use_constraints:
        add_availability_constraints(model, assignment_vars, person_list, shift_list)

    if "max_per_day" in args.use_constraints:
        add_max_shifts_per_day_constraints(
            model, assignment_vars, person_list, shift_list, max_shifts=1
        )

    if "exact_testers" in args.use_constraints:
        add_exactly_x_testers_per_shift_constraints(
            model, assignment_vars, shift_list, person_list, x=2
        )

    if "min_first" in args.use_constraints:
        add_minimum_first_tester_per_shift_constraints(
            model, assignment_vars, person_list, shift_list
        )

    #TODO dit is een beetje dubbel
    if "max_per_week" in args.use_constraints:
        add_max_x_shifts_per_week_constraints(
            model, assignment_vars, person_list, shift_list, max_shifts_per_week=2
        )

    if "single_first" in args.use_constraints:
        add_single_first_tester_constraints(
            model, assignment_vars, shift_list, person_list
        )

        # Mutual exclusions: prevent two specific people being scheduled on the same day
        try:
            import json
            excl_path = Path("data") / "mutual_exclusions.json"
            if excl_path.exists():
                exclusions = json.loads(excl_path.read_text(encoding="utf-8"))
                if exclusions:
                    # Build a mapping person name -> index
                    name_to_idx = {p["name"]: i for i, p in enumerate(person_list)}
                    # Build date -> shift indices map
                    date_to_shifts = {}
                    for s_idx, shift in enumerate(shift_list):
                        date_to_shifts.setdefault(shift["date"], []).append(s_idx)

                    for pair in exclusions:
                        if not pair or len(pair) < 2:
                            continue
                        a, b = pair[0], pair[1]
                        if a not in name_to_idx or b not in name_to_idx:
                            # skip unknown names
                            continue
                        a_idx = name_to_idx[a]
                        b_idx = name_to_idx[b]
                        # For each date, sum assignments for both persons on that date <= 1
                        for date, shift_idxs in date_to_shifts.items():
                            vars_a = [assignment_vars[(a_idx, s)] for s in shift_idxs if (a_idx, s) in assignment_vars]
                            vars_b = [assignment_vars[(b_idx, s)] for s in shift_idxs if (b_idx, s) in assignment_vars]
                            if not vars_a and not vars_b:
                                continue
                            model.Add(sum(vars_a + vars_b) <= 1)
        except Exception:
            # Don't fail the whole model setup if exclusions can't be read
            pass

    # Delegate all objective building to penalty_terms module
    apply_objective(
        model,
        assignment_vars,
        person_list,
        shift_list,
        weights=MASKED_WEIGHTS,
    )


# All penalty/objective logic is now in penalty_terms.py


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
            weights=MASKED_WEIGHTS,
        )
    else:
        print("Geen oplossing gevonden.")
