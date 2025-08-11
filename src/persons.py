import csv
from datetime import datetime
import re


def is_date_field(keyname):
    # Matches day-month like "1-11" or "12-1" (supports 1..31 for day, 1..12 for month, with optional leading 0)
    return bool(re.match(r"^(?:0?[1-9]|[12][0-9]|3[01])-(?:0?[1-9]|1[0-2])$", keyname))


def csv_to_personlist(csv_path):
    person_list = []
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            naam = row["Name"].strip()
            rol = "T" if row["Tester"].strip().upper() == "TRUE" else "P"
            pref_loc = row["Pref_Loc"].strip()
            beschikbaar = {}
            month_max = int(row["Month_max"].strip())
            month_avg = int(row["Month_avg"].strip())

            for key in row:
                if is_date_field(key):
                    try:
                        date_obj = datetime.strptime(key.strip(), "%d-%m")
                        date_str = f"2025-{date_obj.month:02d}-{date_obj.day:02d}"
                    except ValueError:
                        date_str = key.strip()
                    beschikbaar[date_str] = row[key].strip().upper() == "TRUE"

            person = {
                "name": naam,
                "role": rol,
                "availability": beschikbaar,
                "pref_location": pref_loc,
                "month_max": int(month_max),
                "month_avg": int(month_avg),
            }
            person_list.append(person)
    return person_list
