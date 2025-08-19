import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime as _dt
from typing import Optional

import pandas as pd
import streamlit as st

from persons import csv_to_personlist
from shift_list import dag_teams, get_weekday_from_date
from config import get_locations_config, get_data_sources_config, get_weights_config


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
    ds_conf = get_data_sources_config()
    pref_dir_rel = ds_conf.get("preferences_dir", "data/preferences")
    prefs_dir = root / pref_dir_rel
    prefs_dir.mkdir(parents=True, exist_ok=True)
    plan_dir = root / "data"
    plan_dir.mkdir(exist_ok=True)

    # UI: upload or pick previous
    st.markdown("1) Upload een CSV met personeelsvoorkeuren en beschikbaarheid of kies een eerder bestand.")
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
        # Parse persons
        try:
            persons = csv_to_personlist(str(csv_path))
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

            # Seed from locations.json teams_per_date if present
            loc_conf = get_locations_config()
            locs = [loc.get("name") for loc in loc_conf.get("locations", [])]
            initial_plan = {}
            # add dates present in config
            for loc in loc_conf.get("locations", []):
                name = loc.get("name")
                for d, count in (loc.get("teams_per_date") or {}).items():
                    if isinstance(d, str) and len(d) == 10 and d[4] == "-" and d[7] == "-":
                        date_list.append(d)
                        initial_plan.setdefault(d, {loc_name: 0 for loc_name in locs})
                        initial_plan[d][name] = int(count or 0)
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

                # Merge into existing config
                conf_path = root / "config" / "locations.json"
                try:
                    current_conf = _json.loads(conf_path.read_text(encoding="utf-8"))
                except Exception:
                    current_conf = loc_conf
                for loc in current_conf.get("locations", []):
                    name = loc.get("name")
                    if name in per_loc:
                        loc["teams_per_date"] = per_loc[name]
                try:
                    conf_path.write_text(_json.dumps(current_conf, ensure_ascii=False, indent=2), encoding="utf-8")
                    st.success(f"Bijgewerkt: {conf_path.relative_to(root)} (teams_per_date)")
                except Exception as e:
                    st.warning(f"Kon locaties-config niet schrijven: {e}")
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

    with st.expander("Constraints (harde regels)", expanded=True):
        cols = st.columns(3)
        cons_selected = []
        for idx, key in enumerate(default_constraints):
            with cols[idx % 3]:
                if st.checkbox(key, value=True, key=f"cons_{key}"):
                    cons_selected.append(key)

    with st.expander("Doelen/penalties (zachte voorkeuren)", expanded=True):
        cols = st.columns(3)
        obj_selected = []
        for idx, key in enumerate(default_objectives):
            with cols[idx % 3]:
                if st.checkbox(key, value=True, key=f"obj_{key}"):
                    obj_selected.append(key)

    with st.expander("Gewichten voor doelen", expanded=True):
        weights_conf = get_weights_config()
        w_inputs = {}
        cols = st.columns(3)
        for idx, (k, v) in enumerate(weights_conf.items()):
            with cols[idx % 3]:
                try:
                    w_inputs[k] = st.number_input(
                        f"{k}", min_value=0, step=1, value=int(v) if isinstance(v, (int, float)) else 0
                    )
                except Exception:
                    w_inputs[k] = v

    st.markdown("3) Controleer de waarden. Als alles goed is, genereer het rooster.")
    disabled = not (selected_any and preview_ok)
    verbose = st.checkbox("Verbose output", value=False)
    if st.button("Genereer rooster (run main.py)", disabled=disabled):
        main_py = root / "src" / "main.py"
        py = _find_windows_python_in_venv(root) or Path(sys.executable)
        cmd = [str(py), "-X", "utf8", str(main_py)]
        if csv_path is not None:
            cmd += ["--csv", str(csv_path)]

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
