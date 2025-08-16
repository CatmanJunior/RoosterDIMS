import csv
from datetime import datetime
import re


def is_date_field(keyname):
    # Matches day-month like "1-11" or "12-1" (supports 1..31 for day, 1..12 for month, with optional leading 0)
    return bool(re.match(r"^(?:0?[1-9]|[12][0-9]|3[01])-(?:0?[1-9]|1[0-2])$", keyname))


def csv_to_personlist(csv_path):
    person_list = []
    # Auto-detect delimiter (comma, semicolon, or tab) and strip BOM if present
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as csvfile:
        sample = csvfile.read(4096)
        csvfile.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",	;")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        reader = csv.DictReader(csvfile, delimiter=delimiter)

        def _safe_str(v: object, default: str = "") -> str:
            return default if v is None else str(v)

        def _safe_int(v: object, default: int = 0) -> int:
            try:
                s = _safe_str(v, "").strip()
                return int(s) if s != "" else default
            except Exception:
                return default

        def _to_bool(v: object) -> bool:
            if isinstance(v, bool):
                return v
            s = _safe_str(v, "").strip().lower()
            return s in {"true", "1", "yes", "y", "ja"}

        for row in reader:
            naam = _safe_str(row.get("Name") or row.get("name"), "").strip()
            if not naam:
                raise ValueError("CSV mist kolom 'Name' of bevat lege namen.")

            tester_val = _safe_str(row.get("Tester") or row.get("tester"), "").strip()
            rol = "T" if tester_val.upper() == "TRUE" or tester_val == "1" else "P"

            # Backward compatibility: optional single preferred location string
            pref_loc = _safe_str(row.get("Pref_Loc"), "").strip()

            # New flags: Pref_Loc_0 (Utrecht), Pref_Loc_1 (Amersfoort)
            def _parse_flag(val, default=2):
                return _safe_int(val, default)

            pref_loc_0 = _parse_flag(row.get("Pref_Loc_0", 2))  # 0=forbidden, 1=penalize, 2=no penalty
            pref_loc_1 = _parse_flag(row.get("Pref_Loc_1", 2))
            pref_loc_flags = {
                "Utrecht": pref_loc_0,
                "Amersfoort": pref_loc_1,
            }

            beschikbaar = {}
            month_max = _safe_int(row.get("Month_max"), 0)
            month_avg = _safe_int(row.get("Month_avg"), 0)

            for key in row.keys():
                if is_date_field(str(key)):
                    try:
                        date_obj = datetime.strptime(str(key).strip(), "%d-%m")
                        date_str = f"2025-{date_obj.month:02d}-{date_obj.day:02d}"
                    except ValueError:
                        date_str = str(key).strip()
                    beschikbaar[date_str] = _to_bool(row.get(key))

            person = {
                "name": naam,
                "role": rol,
                "availability": beschikbaar,
                "pref_location": pref_loc,
                "pref_loc_flags": pref_loc_flags,
                "month_max": int(month_max),
                "month_avg": int(month_avg),
            }
            person_list.append(person)
    return person_list
