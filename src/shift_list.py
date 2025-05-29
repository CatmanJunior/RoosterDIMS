from datetime import datetime, timedelta

locations = ["Utrecht", "Amersfoort"]
utrecht_days = ["di", "do"]
utrecht_teams = [0, 1]
amersfoort_days = ["do"]
amersfoort_teams = [0]

# Geef hier de gewenste weekdagen op en de start/einddatum
weekdagen = ["di", "do"]
startdatum = "2023-10-01"
einddatum = "2023-12-31"

# Map weekday numbers naar Nederlandse dagen
dag_namen = {
    0: "ma",
    1: "di",
    2: "wo",
    3: "do",
    4: "vr",
    5: "za",
    6: "zo"
}

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
    return {
        "location": location,
        "day": day,
        "date": date,
        "team": team
    }

shift_list = []

def create_shift_list():
    dates_by_day = get_dates_by_daynames(startdatum, einddatum, weekdagen)
    for location in locations:
        if location == "Utrecht":
            for team in utrecht_teams:
                for day in utrecht_days:
                    for date in dates_by_day[day]:
                        shift_list.append(create_shift_dict(location, day, date, team))
        elif location == "Amersfoort":
            for team in amersfoort_teams:
                for day in amersfoort_days:
                    for date in dates_by_day[day]:
                        shift_list.append(create_shift_dict(location, day, date, team))


create_shift_list()

if __name__ == "__main__":
    # Testprint
    for shift in shift_list:
        print(shift)
