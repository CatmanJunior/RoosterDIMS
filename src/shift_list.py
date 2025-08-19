from datetime import datetime
import csv
from typing import Dict
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


# Load dynamic locations config
_LOC_CONF = get_locations_config()
_LOCATIONS = [loc["name"] for loc in _LOC_CONF.get("locations", [])]
# New: optional per-date team counts configured per location
_LOC_TEAMS_PER_DATE = {
    loc["name"]: loc.get("teams_per_date", {}) for loc in _LOC_CONF.get("locations", [])
}

# Build a consolidated {date: {location: count}} plan from teams_per_date
_PLAN_FROM_CONF: Dict[str, Dict[str, int]] = {}
for loc_name, date_map in _LOC_TEAMS_PER_DATE.items():
    for date_str, count in (date_map or {}).items():
        try:
            # validate date
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        _PLAN_FROM_CONF.setdefault(date_str, {})[loc_name] = int(count or 0)

# Map weekday numbers naar Nederlandse dagen
dag_namen = {0: "ma", 1: "di", 2: "wo", 3: "do", 4: "vr", 5: "za", 6: "zo"}

# formatted as "day": {location: team_count}
# Build from config
dag_teams: Dict[str, Dict[str, int]] = {}
for loc in _LOC_CONF.get("locations", []):
    name = loc.get("name")
    for day, count in loc.get("teams_per_day", {}).items():
        dag_teams.setdefault(day, {})[name] = int(count)


# Genereer shifts
def create_shift_dict(location, day, date, team):
    weeknummer = datetime.strptime(date, "%Y-%m-%d").isocalendar().week
    return {
        "location": location,
        "day": day,
        "date": date,
        "weeknummer": weeknummer,
        "team": team,
    }


def csv_to_shiftlist(csv_path: str) -> list[dict[str, int | str]]:
    """
    Build a list of shifts using config/locations.json:
    - Prefer explicit teams_per_date per location
    - Else, infer dates from the uploaded CSV headers and use weekday defaults from teams_per_day
    """
    shift_list: list[dict[str, int | str]] = []
    # If teams_per_date exists in locations config, use that
    if _PLAN_FROM_CONF:
        for date in sorted(_PLAN_FROM_CONF.keys()):
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                continue
            weekday = get_weekday_from_date(dt)
            counts = _PLAN_FROM_CONF.get(date, {})
            for loc in _LOCATIONS:
                n = int(counts.get(loc, 0) or 0)
                for i in range(max(0, n)):
                    shift_list.append(create_shift_dict(loc, weekday, date, i))
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
                    .replace(year=2025)
                    .strftime("%Y-%m-%d")
                )
            except Exception:
                # Skip non-date tokens
                continue

        for date in date_columns:
            weekday: str = get_weekday_from_date(datetime.strptime(date, "%Y-%m-%d"))
            # Use configured counts per location for that weekday
            for loc, count in dag_teams.get(weekday, {}).items():
                for i in range(count):
                    new_shift = create_shift_dict(loc, weekday, date, i)
                    shift_list.append(new_shift)

    return shift_list


def get_weekday_from_date(date_obj):
    return dag_namen[date_obj.weekday()]
