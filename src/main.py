from ortools.sat.python import cp_model
import argparse
import sys
import dataclasses
import csv as _csv
from pathlib import Path
from config import (
    get_data_sources_config,
    get_weights_config,
    get_department_defaults,
    get_locations_config,
)
from models import AssignmentVars, DiagnosticDay, SolverContext, SolverResult, Weights
from person_list import csv_to_personlist
from shift_manager import csv_to_shiftlist
from constraints import add_constraints
from debug import (
    print_available_people_for_shifts,
    print_filled_shifts,
    print_shift_count_per_person,
)
from penalties import export_penalties
from export import export_to_csv, sanitize_rooster_name, resolve_roster_base_dir
from diagnostics import diagnose_unplanned_days

_BASE_DS_CONF = get_data_sources_config()
default_csv = _BASE_DS_CONF.get("default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv")

parser = argparse.ArgumentParser(description="Run roster optimization")
parser.add_argument("--csv", dest="csv_file", help="Path to input CSV", default=None)
parser.add_argument("--weights", dest="weights_path", help="Path to weights JSON")
parser.add_argument(
    "--use-constraints", dest="use_constraints", nargs="*",
    default=["availability", "max_per_day", "exact_testers", "min_first", "max_per_week", "single_first"],
)
parser.add_argument(
    "--use-objectives", dest="use_objectives", nargs="*",
    default=["location", "fairness", "monthly", "monthly_avg", "weekly_multi", "monthly_min_avail"],
)
parser.add_argument("--verbose", action="store_true")
parser.add_argument("--year", dest="year", type=int, default=2026)
parser.add_argument("--quarter", dest="quarter", default="Q1")
parser.add_argument("--department", dest="department")
parser.add_argument("--shiftplan-path", dest="shiftplan_path")
parser.add_argument("--rooster-name", dest="rooster_name")
parser.add_argument("--allow-partial", dest="allow_partial", action="store_true", default=False)
args, _ = parser.parse_known_args(sys.argv[1:])

dept_defaults = get_department_defaults(getattr(args, "department", None))
dept_ds_overrides = dept_defaults.get("data_sources", {}) if isinstance(dept_defaults, dict) else {}
DS_CONF = {**_BASE_DS_CONF, **dept_ds_overrides}
LOCATIONS_CONFIG_PATH = dept_defaults.get("locations_config") if isinstance(dept_defaults, dict) else None
if LOCATIONS_CONFIG_PATH:
    try:
        get_locations_config(LOCATIONS_CONFIG_PATH)
    except FileNotFoundError:
        LOCATIONS_CONFIG_PATH = None

if args.csv_file is None:
    args.csv_file = DS_CONF.get("default_persons_csv", default_csv)

_WEIGHTS_CONF = get_weights_config(args.weights_path) if getattr(args, "weights_path", None) else get_weights_config()
WEIGHTS_OBJ = Weights.from_config(_WEIGHTS_CONF, set(args.use_objectives))
if args.allow_partial:
    WEIGHTS_OBJ.enable_coverage(_WEIGHTS_CONF)

model = cp_model.CpModel()
csv_file = args.csv_file

shift_list = csv_to_shiftlist(
    csv_file,
    locations_config_path=LOCATIONS_CONFIG_PATH,
    shiftplan_path=getattr(args, "shiftplan_path", None),
)
person_list = csv_to_personlist(csv_file, year=args.year, locations_config_path=LOCATIONS_CONFIG_PATH)





if __name__ == "__main__":
    import os as _os

    if args.verbose:
        _os.environ["ROOSTER_VERBOSE"] = "1"

    ctx = SolverContext(model=model, persons=person_list, shifts=shift_list, weights=WEIGHTS_OBJ)
    ctx.assignment_vars = AssignmentVars.create(ctx.persons, ctx.shifts, ctx.model)

    if args.verbose:
        print_available_people_for_shifts(ctx)

    add_constraints(ctx, set(args.use_constraints), args.allow_partial)
    solver = cp_model.CpSolver()
    status = solver.Solve(ctx.model)
    result = SolverResult(solver=solver, status=status)
    solver, status = result.solver, result.status

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for shift in ctx.shifts:
            shift.testers = [
                person.name
                for person in ctx.persons
                if solver.Value(ctx.assignment_vars[(person.idx, shift.idx)]) == 1
            ]

        print_filled_shifts(ctx.shifts)
        print_shift_count_per_person(ctx, solver)

        base_dir = resolve_roster_base_dir(DS_CONF, args.year, args.quarter)
        if args.rooster_name:
            safe = sanitize_rooster_name(args.rooster_name)
            roster_path = str(base_dir / f"{safe}.csv")
            penalties_path = str(base_dir / f"{safe}_penalties.csv")
        else:
            roster_path = str(base_dir / "rooster.csv")
            penalties_path = str(base_dir / "penalties.csv")
        Path(roster_path).parent.mkdir(parents=True, exist_ok=True)

        export_to_csv([s.to_dict() for s in ctx.shifts], roster_path)
        export_penalties(ctx, solver, filepath=penalties_path)
    else:
        print("Geen oplossing gevonden.")
        diags = diagnose_unplanned_days(ctx, result)
        for d in diags:
            print(
                f"- {d.date} @ {d.location}: vereist={d.required}, "
                f"gepland={d.assigned}, beschikbaar={d.available} -> {d.reason}"
            )

        base_dir = resolve_roster_base_dir(DS_CONF, args.year, args.quarter)
        diag_path = DS_CONF.get("diagnostics_csv") or str(base_dir / "rooster_diagnostics.csv")
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            fieldnames = [f.name for f in dataclasses.fields(DiagnosticDay)]
            with open(diag_path, "w", newline="", encoding="utf-8") as f:
                writer = _csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for d in diags:
                    writer.writerow(d.to_dict())
            print(f"Diagnostiek geschreven naar {diag_path}")
        except Exception as e:
            print(f"Kon diagnostics CSV niet schrijven: {e}")