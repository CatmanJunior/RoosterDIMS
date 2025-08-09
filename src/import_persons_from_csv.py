import csv
from datetime import datetime

def csv_to_person_list(csv_path):
    person_list = []
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Ingevuld'].strip().upper() != 'TRUE':
                continue
            naam = row['Naam'].strip()
            rol = 'eerste' if row['Eerste'].strip().upper() == 'TRUE' else 'peer'
            voorkeur = row['Voorkeurslocatie'].strip() if row['Voorkeurslocatie'].strip() else None
            beschikbaar = {}
            for key in row:
                if key not in ['Naam', 'Ingevuld', 'Eerste', 'Voorkeurslocatie']:
                    # Convert date from d-m to yyyy-mm-dd (assume 2023)
                    try:
                        date_obj = datetime.strptime(key.strip(), '%d-%m')
                        date_str = f"2023-{date_obj.month:02d}-{date_obj.day:02d}"
                    except ValueError:
                        date_str = key.strip()
                    beschikbaar[date_str] = row[key].strip().upper() == 'TRUE'
            person = {
                'naam': naam,
                'rol': rol,
                'beschikbaar': beschikbaar,
                'voorkeur': voorkeur
            }
            person_list.append(person)
    return person_list

if __name__ == "__main__":
    person_list = csv_to_person_list("Test_Data_sanitized_oktober.csv")
    for person in person_list:
        print(person)