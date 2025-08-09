import csv
from datetime import datetime

dag_namen = {
    0: "ma",
    1: "di",
    2: "wo",
    3: "do",
    4: "vr",
    5: "za",
    6: "zo"
}

startdatum = "2023-10-01"  # adjust as needed

def create_shift_dict(location, day, date, team, testers=None):
    weeknummer = datetime.strptime(date, "%Y-%m-%d").isocalendar().week
    return {
        "location": location,
        "day": day,
        "date": date,
        "weeknummer": weeknummer,
        "team": team,
        "testers": testers if testers else []
    }

shift_list = []

def import_shifts_from_preferences(csv_path):
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter='\t')
        if not reader.fieldnames:
            raise ValueError("CSV file must have headers")
        date_columns = [col for col in reader.fieldnames if col not in ["Naam", "Ingevuld", "Eerste"]]
        for row in reader:
            naam = row["Naam"]
            for date_col in date_columns:
                value = row[date_col]
                if value.strip():
                    try:
                        year = int(startdatum.split("-")[0])
                        date_str = f"{year}-{date_col}"
                        date_full = datetime.strptime(date_str, "%Y-%d-%m")
                    except Exception:
                        continue
                    day = dag_namen[date_full.weekday()]
                    location = "Utrecht"
                    team = 0
                    # For Wednesday or Saturday, only add one shift in Utrecht
                    if day in ["wo", "za"]:
                        shift_list.append(create_shift_dict(location, day, date_full.strftime("%Y-%m-%d"), team, testers=[naam]))
                    else:
                        shift_list.append(create_shift_dict(location, day, date_full.strftime("%Y-%m-%d"), team, testers=[naam]))

if __name__ == "__main__":
    import_shifts_from_preferences("testers.csv")
    for shift in shift_list:
        print(shift)
