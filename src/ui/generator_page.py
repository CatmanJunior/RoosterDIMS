import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime as _dt
from typing import Optional
import pandas as pd
import streamlit as st

from persons import csv_to_personlist
from shift_list import build_location_plan, get_weekday_from_date
from config import (
    get_locations_config,
    get_data_sources_config,
    get_weights_config,
    get_departments_config,
    get_department_defaults,
)

def validate_csv_columns(csv_path: Path) -> tuple[bool, list[str], list[str]]:
    """
    Validate that the CSV has required columns.
    Returns: (is_valid, missing_columns, warnings)
    """
    required_columns = ["Name", "Tester", "Month_max", "Month_avg"]
    
    try:
        # Read just the header to check columns
        df = pd.read_csv(csv_path, sep=None, engine="python", nrows=0)
        columns = df.columns.tolist()
        
        # Normalize column names (case-insensitive check)
        columns_lower = [col.lower() for col in columns]
        
        missing = []
        warnings = []
        
        # Check required columns
        for req_col in required_columns:
            if req_col.lower() not in columns_lower and req_col not in columns:
                missing.append(req_col)
        
        # Check if there are any date columns (format: d-m or dd-mm)
        import re
        has_date_columns = any(re.match(r"^(?:0?[1-9]|[12][0-9]|3[01])-(?:0?[1-9]|1[0-2])$", str(col)) for col in columns)
        if not has_date_columns:
            warnings.append("Geen datum kolommen gevonden (verwacht formaat: d-m of dd-mm)")
        
        # Check optional preference location columns
        has_pref_loc = any("Pref_Loc" in str(col) for col in columns)
        if not has_pref_loc:
            warnings.append("Geen locatie voorkeuren kolommen gevonden (Pref_Loc_0, Pref_Loc_1, etc.)")
        
        is_valid = len(missing) == 0
        return is_valid, missing, warnings
        
    except Exception as e:
        return False, [], [f"Fout bij valideren van CSV: {str(e)}"]


def _find_windows_python_in_venv(root: Path) -> Optional[Path]:
    """Find python.exe in current venv or common local venv folders on Windows."""
    venv_env = os.environ.get("VIRTUAL_ENV")
    if venv_env:
        cand = Path(venv_env) / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    for name in (".venv", "venv", "env", ".env"):
        cand = root / name / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    return None


def render_generator_page() -> None:
    st.title("🔁 Roostergenerator")

    root = Path(__file__).resolve().parent.parent.parent  # project root (parent of src)
    base_ds_conf = get_data_sources_config()
    dept_conf = get_departments_config()
    dept_map = dept_conf.get("departments", {}) if isinstance(dept_conf, dict) else {}
    dept_names = list(dept_map.keys())
    selected_department = st.session_state.get("global_department")
    if not selected_department and dept_names:
        default_dept = (
            dept_conf.get("default_department")
            if dept_conf.get("default_department") in dept_names
            else dept_names[0]
        )
        selected_department = default_dept
    if not dept_names:
        st.caption("Geen afdelingen-config gevonden; standaard-instellingen worden gebruikt.")

    dept_defaults = get_department_defaults(selected_department)
    dept_ds_overrides = dept_defaults.get("data_sources", {}) if isinstance(dept_defaults, dict) else {}
    ds_conf = {**base_ds_conf, **dept_ds_overrides}
    locations_config_path = dept_defaults.get("locations_config") if isinstance(dept_defaults, dict) else None
    pref_dir_rel = ds_conf.get("preferences_dir", "data/preferences")
    prefs_dir = root / pref_dir_rel
    prefs_dir.mkdir(parents=True, exist_ok=True)
    plan_dir = root / "data"
    plan_dir.mkdir(exist_ok=True)

    # Year & quarter selector
    current_year = _dt.now().year
    selected_year = st.session_state.get("global_year", current_year)
    selected_quarter = st.session_state.get("global_quarter", "Q1")
    st.info(f"📌 Geselecteerd jaar: **{selected_year}** - Datums in CSV (d-m formaat) worden geïnterpreteerd als {selected_year}")
    st.markdown("---")

    # UI: upload or pick previous
    st.markdown("### 1) Upload CSV met personeelsvoorkeuren")
    uploaded = st.file_uploader("Kies CSV", type=["csv", "txt"])
    prev_choice = None
    try:
        existing = sorted([p.name for p in prefs_dir.glob("uploaded_*.csv")])
        if existing:
            prev_choice = st.selectbox("Of kies eerder geüpload bestand", ["(geen)"] + existing)
    except Exception:
        pass

    csv_path: Optional[Path] = None
    selected_any = False

    if uploaded is not None:
        target_path = prefs_dir / f"uploaded_{uploaded.name}"
        csv_bytes = uploaded.getvalue()
        with open(target_path, "wb") as f:
            f.write(csv_bytes)
        st.success(f"Bestand opgeslagen als {target_path.relative_to(root)}")
        csv_path = target_path
        selected_any = True
    elif prev_choice and prev_choice != "(geen)":
        csv_path = prefs_dir / prev_choice
        selected_any = True

    persons = []
    preview_ok = False
    if selected_any and csv_path is not None:
        # Validate CSV columns
        is_valid, missing_cols, warnings = validate_csv_columns(csv_path)
        
        if not is_valid:
            st.error(f"❌ CSV validatie gefaald! Ontbrekende verplichte kolommen: {', '.join(missing_cols)}")
            st.info("Verplichte kolommen: Name, Tester, Month_max, Month_avg")
            st.info("Datum kolommen in formaat: d-m of dd-mm (bijv. 1-10, 15-11)")
        else:
            if warnings:
                for warning in warnings:
                    st.warning(f"⚠️ {warning}")
        
        # Parse persons
        try:
            persons = csv_to_personlist(
                str(csv_path),
                year=selected_year,
                locations_config_path=locations_config_path,
            )
        except Exception as e:
            st.error(f"Kon CSV niet parsen: {e}")

        # Preview file
        try:
            head_df = pd.read_csv(csv_path, sep=None, engine="python").head(5)
            st.subheader("Bestandsvoorbeeld (eerste 5 rijen)")
            st.dataframe(head_df, use_container_width=True)
            preview_ok = True
        except Exception:
            st.caption("Kon geen tabelvoorbeeld maken; bestand kan tab-delimited zijn.")

        # Build initial per-date, per-location shift plan (from locations config, fallback to weekday defaults)
        try:
            date_keys = set()
            for p in persons if isinstance(persons, list) else []:
                av = p.get("availability", {}) if isinstance(p, dict) else {}
                for k in av.keys():
                    if isinstance(k, str) and len(k) == 10 and k[4] == "-" and k[7] == "-":
                        date_keys.add(k)
            date_list = sorted(date_keys)

            # Seed from locations config teams_per_date if present
            try:
                loc_conf = get_locations_config(locations_config_path)
            except FileNotFoundError:
                st.warning("Locatieconfig voor afdeling niet gevonden; gebruik standaard locaties.")
                loc_conf = get_locations_config()
                locations_config_path = None

            shiftplans_dir = ds_conf.get("shiftplans_dir", "data/shiftplans")
            dept_slug = (selected_department or "default").strip().replace(" ", "_")
            shiftplan_path = root / shiftplans_dir / dept_slug / f"{selected_year}_{selected_quarter}.json"

            locs, initial_plan, dag_teams, loc_defaults = build_location_plan(
                locations_config_path,
                str(shiftplan_path),
            )
            initial_plan = initial_plan or {}
            # add dates present in config
            for d in initial_plan.keys():
                date_list.append(d)
            date_list = sorted(set(date_list))

            # Fill missing dates using weekday defaults
            for d in date_list:
                if d not in initial_plan:
                    try:
                        wd = get_weekday_from_date(_dt.strptime(d, "%Y-%m-%d"))
                    except Exception:
                        continue
                    weekday_counts = dag_teams.get(wd, {})
                    row = {loc: int(weekday_counts.get(loc, 0)) for loc in locs}
                    initial_plan[d] = row

            st.subheader("Shifts per datum en locatie (bewerkbaar)")
            edited_plan = {}
            if initial_plan:
                df_plan = pd.DataFrame.from_dict(initial_plan, orient="index").reset_index()
                df_plan = df_plan.rename(columns={"index": "date"}).sort_values("date")
                try:
                    edited = st.data_editor(
                        df_plan,
                        num_rows="fixed",
                        use_container_width=True,
                        column_config={col: st.column_config.NumberColumn(min_value=0, step=1) for col in df_plan.columns if col != "date"},
                    )
                    for _, row in edited.iterrows():
                        dct = {col: int(row[col]) if pd.notna(row[col]) else 0 for col in df_plan.columns if col != "date"}
                        edited_plan[str(row["date"]) ] = dct
                except Exception:
                    for _, row in df_plan.iterrows():
                        cols = st.columns([2] + [1] * (len(df_plan.columns) - 1))
                        with cols[0]:
                            st.write(row["date"])  # label
                        updates = {}
                        for idx, col in enumerate([c for c in df_plan.columns if c != "date"], start=1):
                            with cols[idx]:
                                updates[col] = st.number_input(
                                    f"{col} {row['date']}",
                                    min_value=0,
                                    step=1,
                                    value=int(row[col]) if pd.notna(row[col]) else 0,
                                )
                        edited_plan[str(row["date"]) ] = {k: int(v) for k, v in updates.items()}
            else:
                st.info("Geen datums gevonden om een shiftplan te maken.")

            # Write edited plan into config/locations.json under teams_per_date per location
            if edited_plan:
                import json as _json
                # Build per-location mapping
                per_loc: dict[str, dict[str, int]] = {loc_name: {} for loc_name in locs}
                for d, row in edited_plan.items():
                    for loc_name in locs:
                        try:
                            val = int(row.get(loc_name, 0) or 0)
                        except Exception:
                            val = 0
                        if val > 0:
                            per_loc[loc_name][d] = val

                # Write shiftplan file
                shiftplan_path.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "year": selected_year,
                    "quarter": selected_quarter,
                    "teams_per_date": {},
                }
                teams_per_date: dict[str, dict[str, int]] = {}
                for loc_name, dmap in per_loc.items():
                    for d, val in dmap.items():
                        teams_per_date.setdefault(d, {})[loc_name] = val
                payload["teams_per_date"] = teams_per_date
                try:
                    shiftplan_path.write_text(
                        _json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    st.success(f"Shiftplan opgeslagen: {shiftplan_path.relative_to(root)}")
                except Exception as e:
                    st.warning(f"Kon shiftplan niet schrijven: {e}")
        except Exception as e:
            st.warning(f"Kon geen bewerkbaar shift-overzicht maken: {e}")

    st.markdown("2) Stel opties in (constraints & doelen) en pas gewichten aan indien gewenst.")

    # Defaults
    default_constraints = [
        "availability",
        "max_per_day",
        "exact_testers",
        "min_first",
        "max_per_week",
        "single_first",
    ]
    default_objectives = [
        "location",
        "fairness",
        "monthly",
        "monthly_avg",
        "weekly_multi",
        "monthly_min_avail",
    ]
    weights_conf = get_weights_config()

    def _apply_department_defaults(dept_defaults: dict) -> None:
        dept_constraints = dept_defaults.get("constraints", default_constraints)
        dept_objectives = dept_defaults.get("objectives", default_objectives)
        dept_weights = dept_defaults.get("weights", {})
        for key in default_constraints:
            st.session_state[f"cons_{key}"] = key in dept_constraints
        for key in default_objectives:
            st.session_state[f"obj_{key}"] = key in dept_objectives
        for key, val in weights_conf.items():
            st.session_state[f"weight_{key}"] = int(dept_weights.get(key, val) or 0)

    applied_key = st.session_state.get("_dept_applied")
    if dept_names and selected_department and applied_key != selected_department:
        _apply_department_defaults(dept_defaults or {})
        st.session_state["_dept_applied"] = selected_department
    elif not dept_names and applied_key != "__default__":
        _apply_department_defaults({})
        st.session_state["_dept_applied"] = "__default__"

    with st.expander("Constraints (harde regels)", expanded=True):
        cols = st.columns(3)
        cons_selected = []
        for idx, key in enumerate(default_constraints):
            with cols[idx % 3]:
                if st.checkbox(key, key=f"cons_{key}"):
                    cons_selected.append(key)

    with st.expander("Doelen/penalties (zachte voorkeuren)", expanded=True):
        cols = st.columns(3)
        obj_selected = []
        for idx, key in enumerate(default_objectives):
            with cols[idx % 3]:
                if st.checkbox(key, key=f"obj_{key}"):
                    obj_selected.append(key)

    with st.expander("Gewichten voor doelen", expanded=True):
        w_inputs = {}
        cols = st.columns(3)
        for idx, (k, v) in enumerate(weights_conf.items()):
            with cols[idx % 3]:
                try:
                    weight_key = f"weight_{k}"
                    if weight_key not in st.session_state:
                        st.session_state[weight_key] = int(v) if isinstance(v, (int, float)) else 0
                    w_inputs[k] = st.number_input(
                        f"{k}",
                        min_value=0,
                        step=1,
                        value=int(st.session_state[weight_key]),
                        key=weight_key,
                    )
                except Exception:
                    w_inputs[k] = v

    st.markdown("3) Controleer de waarden. Als alles goed is, genereer het rooster.")
    rooster_name = st.text_input(
        "Naam van rooster",
        value=st.session_state.get("rooster_name", ""),
        help="Optionele naam. Hiermee wordt het rooster opgeslagen met die naam.",
    )
    st.session_state["rooster_name"] = rooster_name
    disabled = not (selected_any and preview_ok)
    verbose = st.checkbox("Verbose output", value=False)
    if st.button("Genereer rooster (run main.py)", disabled=disabled):
        main_py = root / "src" / "main.py"
        py = _find_windows_python_in_venv(root) or Path(sys.executable)
        cmd = [str(py), "-X", "utf8", str(main_py)]
        if csv_path is not None:
            cmd += ["--csv", str(csv_path)]
        if rooster_name and rooster_name.strip():
            cmd += ["--rooster-name", rooster_name.strip()]
        if selected_department:
            cmd += ["--department", selected_department]
        cmd += ["--quarter", str(selected_quarter)]
        shiftplans_dir = ds_conf.get("shiftplans_dir", "data/shiftplans")
        dept_slug = (selected_department or "default").strip().replace(" ", "_")
        shiftplan_path = root / shiftplans_dir / dept_slug / f"{selected_year}_{selected_quarter}.json"
        if shiftplan_path.exists():
            cmd += ["--shiftplan-path", str(shiftplan_path)]

        # Write weights override to JSON and pass path
        try:
            weights_path = plan_dir / "weights_override.json"
            import json as _json
            weights_path.write_text(_json.dumps(w_inputs, ensure_ascii=False, indent=2), encoding="utf-8")
            cmd += ["--weights", str(weights_path)]
        except Exception:
            pass

        # Pass constraints and objectives selections
        if cons_selected:
            cmd += ["--use-constraints", *cons_selected]
        if obj_selected:
            cmd += ["--use-objectives", *obj_selected]
        if verbose:
            cmd += ["--verbose"]

        with st.spinner("Bezig met genereren van rooster..."):
            result = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        logs_dir = root / "run_logs"
        logs_dir.mkdir(exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        stdout_path = logs_dir / f"stdout_{ts}.log"
        stderr_path = logs_dir / f"stderr_{ts}.log"
        try:
            if result.stdout:
                stdout_path.write_text(result.stdout, encoding="utf-8", errors="ignore")
            if result.stderr:
                stderr_path.write_text(result.stderr, encoding="utf-8", errors="ignore")
        except Exception:
            pass

        st.session_state["last_run"] = {
            "cmd": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "log_paths": {
                "dir": str(logs_dir),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            },
        }

        if result.returncode == 0:
            st.success("Rooster gegenereerd. Ga naar de tab 'Rooster' om het resultaat te bekijken.")
        else:
            st.error(f"Fout bij uitvoeren (code {result.returncode}). Zie output hierboven.")

        st.write("Uitvoer van main.py:")
        st.write(f"Python: {py}")
        if result.stdout:
            st.subheader("stdout")
            st.code(result.stdout)
        if result.stderr:
            st.subheader("stderr")
            st.code(result.stderr)
