from datetime import datetime
import csv
from pathlib import Path
from typing import Dict, Tuple
from config import get_locations_config


class Filled_Shift:
    def __init__(self, location, day, date, weeknummer, team, testers):
        self.location = location
        self.day = day
        self.date = date
        self.weeknummer = weeknummer
        self.team = team
        self.testers = testers

    def __repr__(self):
        return f"Filled_Shift(location={self.location}, day={self.day}, date={self.date}, weeknummer={self.weeknummer}, team={self.team}, testers={self.testers})"

    def to_dict(self):
        return {
            "location": self.location,
            "day": self.day,
            "date": self.date,
            "weeknummer": self.weeknummer,
            "team": self.team,
            "testers": self.testers,
        }


# Map weekday numbers naar Nederlandse dagen
dag_namen = {0: "ma", 1: "di", 2: "wo", 3: "do", 4: "vr", 5: "za", 6: "zo"}


def build_location_plan(
    locations_config_path: str | None = None,
    shiftplan_path: str | None = None,
) -> Tuple[
    list[str],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, int]],
    Dict[str, Dict[str, bool]],
]:
    """Return (locations, plan_from_conf, dag_teams, loc_defaults)."""
    loc_conf = get_locations_config(locations_config_path)
    locations = [loc.get("name") for loc in loc_conf.get("locations", []) if loc.get("name")]

    loc_defaults: Dict[str, Dict[str, bool]] = {}
    for loc in loc_conf.get("locations", []):
        name = loc.get("name")
        if not name:
            continue
        allow_peer = bool(loc.get("allow_peer", int(loc.get("peers", 1)) != 0))
        allow_tester = bool(loc.get("allow_tester", True))
        loc_defaults[name] = {
            "allow_peer": allow_peer,
            "allow_tester": allow_tester,
        }

    # Build a consolidated {date: {location: count}} plan from teams_per_date
    plan_from_conf: Dict[str, Dict[str, int]] = {}
    if shiftplan_path:
        try:
            import json as _json

            plan_payload = _json.loads(Path(shiftplan_path).read_text(encoding="utf-8"))
            teams_per_date = plan_payload.get("teams_per_date", {})
            for date_str, loc_map in (teams_per_date or {}).items():
                try:
                    datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    continue
                if isinstance(loc_map, dict):
                    for loc_name, count in loc_map.items():
                        plan_from_conf.setdefault(date_str, {})[loc_name] = int(count or 0)
        except Exception:
            pass

    if not plan_from_conf:
        for loc in loc_conf.get("locations", []):
            loc_name = loc.get("name")
            if not loc_name:
                continue
            for date_str, entry in (loc.get("teams_per_date") or {}).items():
                try:
                    datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    continue

                if isinstance(entry, dict):
                    teams = int(entry.get("teams", 0) or 0)
                else:
                    teams = int(entry or 0)

                plan_from_conf.setdefault(date_str, {})[loc_name] = teams

    # formatted as "day": {location: team_count}
    dag_teams: Dict[str, Dict[str, int]] = {}
    for loc in loc_conf.get("locations", []):
        name = loc.get("name")
        for day, count in (loc.get("teams_per_day") or {}).items():
            dag_teams.setdefault(day, {})[name] = int(count or 0)

    return locations, plan_from_conf, dag_teams, loc_defaults


# Genereer shifts
def create_shift_dict(location, day, date, team, allow_peer=True, allow_tester=True):
    weeknummer = datetime.strptime(date, "%Y-%m-%d").isocalendar().week
    return {
        "location": location,
        "day": day,
        "date": date,
        "weeknummer": weeknummer,
        "team": team,
        "allow_peer": bool(allow_peer),
        "allow_tester": bool(allow_tester),
    }


def csv_to_shiftlist(
    csv_path: str,
    locations_config_path: str | None = None,
    shiftplan_path: str | None = None,
) -> list[dict[str, int | str]]:
    """
    Build a list of shifts using config/locations.json:
    - Prefer explicit teams_per_date per location
    - Else, infer dates from the uploaded CSV headers and use weekday defaults from teams_per_day
    """
    shift_list: list[dict[str, int | str | bool]] = []
    locations, plan_from_conf, dag_teams, loc_defaults = build_location_plan(
        locations_config_path,
        shiftplan_path,
    )

    # If teams_per_date exists in locations config, use that
    if plan_from_conf:
        for date in sorted(plan_from_conf.keys()):
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                continue
            weekday = get_weekday_from_date(dt)
            counts = plan_from_conf.get(date, {})
            for loc in locations:
                n = int(counts.get(loc, 0) or 0)
                role_info = loc_defaults.get(loc, {})
                for i in range(max(0, n)):
                    shift_list.append(
                        create_shift_dict(
                            loc,
                            weekday,
                            date,
                            i,
                            allow_peer=role_info.get("allow_peer", True),
                            allow_tester=role_info.get("allow_tester", True),
                        )
                    )
        return shift_list

    # Legacy inference path
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader: csv.DictReader = csv.DictReader(csvfile, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError("CSV file must have headers")

        # Heuristic: some files may have a single combined header string; keep old behavior
        raw_header = list(reader.fieldnames)[0]
        date_cells = raw_header.split(",")[5:]
        date_columns: list[str] = []
        for date in date_cells:
            try:
                date_columns.append(
                    datetime.strptime(date.strip(), "%d-%m")
                    .replace(year=2026)
                    .strftime("%Y-%m-%d")
                )
            except Exception:
                # Skip non-date tokens
                continue

        for date in date_columns:
            weekday: str = get_weekday_from_date(datetime.strptime(date, "%Y-%m-%d"))
            # Use configured counts per location for that weekday
            for loc, count in dag_teams.get(weekday, {}).items():
                role_info = loc_defaults.get(loc, {"allow_peer": True, "allow_tester": True})
                for i in range(count):
                    new_shift = create_shift_dict(
                        loc,
                        weekday,
                        date,
                        i,
                        allow_peer=role_info.get("allow_peer", True),
                        allow_tester=role_info.get("allow_tester", True),
                    )
                    shift_list.append(new_shift)

    return shift_list


def get_weekday_from_date(date_obj):
    return dag_namen[date_obj.weekday()]
