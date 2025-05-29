locations = ["Utrecht", "Amersfoort"]
days = ["di", "do"]
utrecht_days = ["di", "do"]
utrecht_teams = [0,1]
amersfoort_days = ["do"]
amersfoort_teams = [0]
di_dates = ["2023-10-03", "2023-10-10", "2023-10-17"]  
do_dates = ["2023-10-05", "2023-10-12", "2023-10-19"]


def create_shift_dict(location, day, date, team):
    return {
        "location": location,
        "date" : date,
        "day": day,
        "team": team
    }



shifts = []

def create_shift_list():
    for location in locations:
        if location == "Utrecht":
            for team in utrecht_teams:
                for date in di_dates:
                    shift = create_shift_dict(location, "di", date, team)
                    shifts.append(shift)
                for date in do_dates:
                    shift = create_shift_dict(location, "do", date, team)
                    shifts.append(shift)
                    
        elif location == "Amersfoort":
                for team in amersfoort_teams:                  
                    for date in do_dates:
                        shift = create_shift_dict(location, "do", date, team)
                        shifts.append(shift)

create_shift_list()
    