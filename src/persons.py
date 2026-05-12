import csv
from datetime import datetime
import re
from config import get_locations_config


def is_date_field(keyname):
    # Matches day-month like "1-11" or "12-1" (supports 1..31 for day, 1..12 for month, with optional leading 0)
    return bool(re.match(r"^(?:0?[1-9]|[12][0-9]|3[01])-(?:0?[1-9]|1[0-2])$", keyname))


def is_location_only_date_field(keyname):
    # Matches date fields with a trailing 'u' meaning location-2-only restriction, e.g. "11-7u", "9-4u"
    return bool(re.match(r"^(?:0?[1-9]|[12][0-9]|3[01])-(?:0?[1-9]|1[0-2])u$", keyname))


def csv_to_personlist(csv_path, year=2026, locations_config_path: str | None = None):
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

            # Dynamically extract all Pref_Loc_<digit> columns
            loc_conf = get_locations_config(locations_config_path)
            locations = [loc.get("name") for loc in loc_conf.get("locations", [])]
            pref_loc_flags = {}
            for idx, loc_name in enumerate(locations):
                col_key = f"Pref_Loc_{idx}"
                val = row.get(col_key, None)
                # If not present, fallback to 2 (no penalty)
                try:
                    pref_loc_flags[loc_name] = int(val) if val is not None and str(val).strip() != "" else 2
                except Exception:
                    pref_loc_flags[loc_name] = 2

            beschikbaar = {}
            date_loc2_only: dict[str, str] = {}
            date_loc2_banned: dict[str, str] = {}
            loc2_name: str | None = locations[2] if len(locations) > 2 else None
            month_max = _safe_int(row.get("Month_max"), 0)
            month_avg = _safe_int(row.get("Month_avg"), 0)

            for key in row.keys():
                key_str = str(key)
                if is_date_field(key_str):
                    try:
                        date_obj = datetime.strptime(key_str.strip(), "%d-%m")
                        date_str = f"{year}-{date_obj.month:02d}-{date_obj.day:02d}"
                    except ValueError:
                        date_str = key_str.strip()
                    beschikbaar[date_str] = _to_bool(row.get(key))
                elif is_location_only_date_field(key_str) and loc2_name:
                    # Strip trailing 'u' and parse the base date
                    base = key_str.strip().rstrip("u")
                    try:
                        date_obj = datetime.strptime(base, "%d-%m")
                        date_str = f"{year}-{date_obj.month:02d}-{date_obj.day:02d}"
                    except ValueError:
                        date_str = base
                    if _to_bool(row.get(key)):
                        # TRUE: available only at location 2 on this date
                        date_loc2_only[date_str] = loc2_name
                    else:
                        # FALSE: available everywhere except location 2 on this date
                        date_loc2_banned[date_str] = loc2_name

            person = {
                "name": naam,
                "role": rol,
                "availability": beschikbaar,
                "pref_location": pref_loc,
                "pref_loc_flags": pref_loc_flags,
                "date_loc2_only": date_loc2_only,
                "date_loc2_banned": date_loc2_banned,
                "month_max": int(month_max),
                "month_avg": int(month_avg),
            }
            person_list.append(person)
    return person_list
