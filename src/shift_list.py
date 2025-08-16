from datetime import datetime, timedelta
import csv
from typing import Dict, Optional
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
    

    
shift_list = []

# Load dynamic locations config
_LOC_CONF = get_locations_config()
_LOCATIONS = [loc["name"] for loc in _LOC_CONF.get("locations", [])]
_LOC_TEAMS_PER_DAY = {loc["name"]: loc.get("teams_per_day", {}) for loc in _LOC_CONF.get("locations", [])}

# Geef hier de gewenste weekdagen op en de start/einddatum
weekdagen = ["di", "do"]
startdatum = "2023-10-01"
einddatum = "2023-12-31"

# Map weekday numbers naar Nederlandse dagen
dag_namen = {0: "ma", 1: "di", 2: "wo", 3: "do", 4: "vr", 5: "za", 6: "zo"}

# formatted as "day": {location: team_count}
# Build from config
dag_teams: Dict[str, Dict[str, int]] = {}
for loc in _LOC_CONF.get("locations", []):
    name = loc.get("name")
    for day, count in loc.get("teams_per_day", {}).items():
        dag_teams.setdefault(day, {})[name] = int(count)


# Genereer alle datums tussen start en eind die op weekdagen vallen
def get_dates_by_daynames(start, end, weekdagen):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    result = {dag: [] for dag in weekdagen}

    current = start_dt
    while current <= end_dt:
        dag = dag_namen[current.weekday()]
        if dag in weekdagen:
            result[dag].append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return result


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





def csv_to_shiftlist(csv_path: str, plan: Optional[Dict[str, Dict[str, int]]] = None) -> list[dict[str, int | str]]:
    """
    Build a list of shifts from either:
    - a provided plan: { 'YYYY-MM-DD': {'Utrecht': int, 'Amersfoort': int}, ... }
    - or by inferring dates from the uploaded CSV headers and using dag_teams defaults.
    """
    shift_list: list[dict[str, int | str]] = []

    if plan:
        # Use explicit plan; date keys drive the generation
        for date in sorted(plan.keys()):
            # Validate/normalize date
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                # Ignore invalid dates
                continue
            weekday = get_weekday_from_date(dt)
            counts = plan.get(date, {})
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
                    datetime.strptime(date.strip(), "%d-%m").replace(year=2025).strftime("%Y-%m-%d")
                )
            except Exception:
                # Skip non-date tokens
                continue

        print(f"Date columns found: {date_columns} ")
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


def create_shift_list_from_daterange():
    dates_by_day = get_dates_by_daynames(startdatum, einddatum, weekdagen)
    for location in _LOCATIONS:
        per_day = _LOC_TEAMS_PER_DAY.get(location, {})
        for day, count in per_day.items():
            for date in dates_by_day.get(day, []):
                for team in range(int(count)):
                    shift_list.append(create_shift_dict(location, day, date, team))


# import_shifts_from_preferences("Test_Data_sanitized_oktober.csv")
# create_shift_list_from_daterange()

if __name__ == "__main__":
    # Testprint
    for shift in shift_list:
        print(shift)
