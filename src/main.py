from ortools.sat.python import cp_model
import argparse
import sys
from export import export_to_csv
import csv as _csv
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
    "location_fairness": WEIGHTS.get("location_fairness", 0)
    if "location_fairness" in _SEL_OBJECTIVES
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


def run_model():
    solver = cp_model.CpSolver()
    # solver.parameters.log_search_progress = True

    status = solver.Solve(model)
    return solver, status


def diagnose_unplanned_days(solver, status, assignment_vars):
    """Return a summary of days that cannot be fully planned and simple reasons.

    This is intentionally lightweight: when the model is infeasible or no
    solution is found, we inspect per-date coverage vs. requested teams and
    the number of available people.
    """
    from collections import defaultdict

    diagnostics = {
        "status": int(status),
        "problem": None,
        # list of rows with date/location and constraint flags
        "days": [],
    }

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        diagnostics["problem"] = "Geen oplossing gevonden door de solver."
    # Build helper indexes
    date_loc_required = defaultdict(lambda: defaultdict(int))
    for sh in shift_list:
        date_loc_required[sh["date"]][sh["location"]] += 1

    # Available testers per (date, location), split by role (first tester vs peer)
    date_loc_available_T = defaultdict(lambda: defaultdict(int))  # role 'T'
    date_loc_available_P = defaultdict(lambda: defaultdict(int))  # role 'P'
    for p in person_list:
        role = p.get("role")
        availability = p.get("availability", {})
        pref_locs = p.get("pref_loc_flags", {})
        for date, is_avail in availability.items():
            if not is_avail:
                continue
            # Count available per location where preference flag > 0
            if pref_locs:
                for loc, flag in pref_locs.items():
                    if flag:
                        if role == "T":
                            date_loc_available_T[date][loc] += 1
                        elif role == "P":
                            date_loc_available_P[date][loc] += 1
            else:
                # If no per-location prefs, consider the tester available for all locations
                for loc in date_loc_required.get(date, {}).keys():
                    if role == "T":
                        date_loc_available_T[date][loc] += 1
                    elif role == "P":
                        date_loc_available_P[date][loc] += 1

    # Constraint-based helper summaries per day/location
    # 1) availability / hard location bans
    date_loc_blocked = defaultdict(lambda: defaultdict(int))
    for t_idx, tester in enumerate(person_list):
        flags = tester.get("pref_loc_flags", {})
        availability = tester.get("availability", {})
        for s_idx, shift in enumerate(shift_list):
            d = shift["date"]
            loc = shift["location"]
            if not availability.get(d, True):
                # Not available at all that day for that date
                date_loc_blocked[d][loc] += 1
            else:
                # Hard location ban (Pref_Loc flag == 0)
                loc_flag = flags.get(loc)
                if loc_flag == 0:
                    date_loc_blocked[d][loc] += 1

    # If we have a solution, also look at how many testers were actually assigned
    date_loc_assigned = defaultdict(lambda: defaultdict(int))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (t_idx, s_idx), var in assignment_vars.items():
            if solver.Value(var):
                sh = shift_list[s_idx]
                date_loc_assigned[sh["date"]][sh["location"]] += 1

    # Pre-compute weekly caps to explain max_per_week
    tester_weeks = defaultdict(lambda: defaultdict(int))  # tester -> week -> shifts
    for (t_idx, s_idx), var in assignment_vars.items():
        shift = shift_list[s_idx]
        tester_weeks[t_idx][shift["weeknummer"]] += 1

    # Build per-day diagnostics
    for date, locs in sorted(date_loc_required.items()):
        for loc, required in locs.items():
            assigned = date_loc_assigned[date][loc]
            # total available = first testers + peers
            available_T = date_loc_available_T[date][loc]
            available_P = date_loc_available_P[date][loc]
            available = available_T + available_P
            if required == 0:
                continue
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or assigned < required:
                # Flags for likely problematic constraints
                reason_parts = []
                c_availability = False
                c_max_per_day = False
                c_max_per_week = False
                c_single_first = False
                c_exclusions = False

                if available == 0:
                    reason_parts.append("Geen testers beschikbaar voor deze locatie op deze dag.")
                    c_availability = True
                elif available * 2 < required:  # 2 testers per shift
                    reason_parts.append("Te weinig beschikbare testers t.o.v. aantal teams.")
                    c_availability = True

                # Heuristics for other constraints
                # Max per day: if there are testers who are available on this date for this location
                # but they already have a shift on this date somewhere else
                # we can't easily see that without solving, so flag as "maybe" when partial coverage
                if assigned < required and available > 0:
                    c_max_per_day = True

                # Max per week: if date is in a week where many testers already have multiple shifts
                # (approximate)
                week = None
                for sh in shift_list:
                    if sh["date"] == date and sh["location"] == loc:
                        week = sh["weeknummer"]
                        break
                if week is not None:
                    # If many testers are at or above 2 shifts in this week, flag
                    capped = sum(1 for t_idx in range(len(person_list)) if tester_weeks[t_idx][week] >= 2)
                    if capped and assigned < required:
                        c_max_per_week = True

                # Single_first & exclusions are harder to detect directly, but we can flag when others are not
                if not c_availability and assigned < required:
                    c_single_first = True
                    c_exclusions = True

                if not reason_parts:
                    reason_parts.append(
                        "Mogelijk conflict tussen constraints (max per dag/week, single first, uitsluitingen)."
                    )

                diagnostics["days"].append(
                    {
                        "date": date,
                        "location": loc,
                        "required": int(required),
                        "assigned": int(assigned),
                        "available": int(available),
                        "available_T": int(available_T),
                        "available_P": int(available_P),
                        "reason": " ".join(reason_parts),
                        "c_availability": c_availability,
                        "c_max_per_day": c_max_per_day,
                        "c_max_per_week": c_max_per_week,
                        "c_single_first": c_single_first,
                        "c_exclusions": c_exclusions,
                    }
                )

    return diagnostics


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
        # Toon ook welke dagen/locaties niet planbaar lijken en waarom
        diags = diagnose_unplanned_days(solver, status, assignment_vars)
        if diags.get("days"):
            print("Problemen per dag/locatie:")
            for row in diags["days"]:
                print(
                    f"- {row['date']} @ {row['location']}: vereist={row['required']}, "
                    f"gepland={row['assigned']}, beschikbaar={row['available']} -> {row['reason']}"
                )

            # Schrijf ook een diagnostics CSV zodat de UI deze kan tonen
            ds_conf = get_data_sources_config()
            diag_path = ds_conf.get("diagnostics_csv")
            if not diag_path:
                roster_path = ds_conf.get("roster_csv", "rooster.csv")
                import os as _os

                root, base = _os.path.split(roster_path)
                diag_path = _os.path.join(root, "rooster_diagnostics.csv")
            try:
                with open(diag_path, "w", newline="", encoding="utf-8") as f:
                    writer = _csv.DictWriter(
                        f,
                        fieldnames=[
                            "date",
                            "location",
                            "required",
                            "assigned",
                            "available",
                            "available_T",
                            "available_P",
                            "reason",
                            "c_availability",
                            "c_max_per_day",
                            "c_max_per_week",
                            "c_single_first",
                            "c_exclusions",
                        ],
                    )
                    writer.writeheader()
                    for row in diags["days"]:
                        writer.writerow(row)
                print(f"Diagnostiek geschreven naar {diag_path}")
            except Exception as e:
                print(f"Kon diagnostics CSV niet schrijven: {e}")
