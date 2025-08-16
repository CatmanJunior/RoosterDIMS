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
from config import get_locations_config


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

    st.markdown("1) Upload een CSV met personeelsvoorkeuren en beschikbaarheid.")
    uploaded = st.file_uploader("Kies CSV", type=["csv", "txt"])  # allow .csv or .txt (tab-delimited)

    root = Path(__file__).resolve().parent.parent.parent  # project root (parent of src)
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)

    csv_path: Optional[Path] = None
    preview_ok = False

    # Show last run output if available
    last_run = st.session_state.get("last_run")
    if last_run:
        with st.expander(
            "Laatste run-uitvoer (klik om te openen)",
            expanded=True if last_run.get("returncode", 1) != 0 else False,
        ):
            st.write(f"Commando: {' '.join(last_run.get('cmd', []))}")
            st.write(f"Exit code: {last_run.get('returncode')}")
            if last_run.get("stdout"):
                st.subheader("stdout")
                st.code(last_run["stdout"])
            if last_run.get("stderr"):
                st.subheader("stderr")
                st.code(last_run["stderr"])
            if last_run.get("log_paths"):
                lp = last_run["log_paths"]
                st.caption(
                    f"Logbestanden opgeslagen in: {lp.get('dir','')}\n"
                    f"stdout: {lp.get('stdout','')}\n"
                    f"stderr: {lp.get('stderr','')}"
                )

    if uploaded is not None:
        # Persist the uploaded file to data/ so main.py can read it
        csv_path = data_dir / f"uploaded_{uploaded.name}"
        bytes_data = uploaded.getvalue()
        with open(csv_path, "wb") as f:
            f.write(bytes_data)

        st.success(f"Bestand opgeslagen als {csv_path.relative_to(root)}")

        # Try to preview parsed persons and detected date columns
        persons = []
        try:
            persons = csv_to_personlist(str(csv_path))
        except Exception as e:
            st.error(f"Kon CSV niet parsen: {e}")

        # Also show raw head of file to validate delimiters
        try:
            import io

            sample = io.StringIO(bytes_data.decode("utf-8", errors="replace"))
            head_df = pd.read_csv(sample, sep=None, engine="python").head(5)
            st.subheader("Bestandsvoorbeeld (eerste 5 rijen)")
            st.dataframe(head_df, use_container_width=True)
            preview_ok = True
        except Exception:
            st.caption("Kon geen tabelvoorbeeld maken; bestand kan tab-delimited zijn.")
        # Build initial per-date, per-location shift plan from default dag_teams
        try:
            # Infer dates from persons availability for the plan (union of availability keys)
            date_keys = set()
            for p in persons if isinstance(persons, list) else []:
                av = p.get("availability", {}) if isinstance(p, dict) else {}
                for k in av.keys():
                    # Use only plausible YYYY-MM-DD
                    if (
                        isinstance(k, str)
                        and len(k) == 10
                        and k[4] == "-"
                        and k[7] == "-"
                    ):
                        date_keys.add(k)
            # Sort
            date_list = sorted(date_keys)
            # Default counts based on weekday and dag_teams; support arbitrary locations
            initial_plan = {}
            locs = [loc.get("name") for loc in get_locations_config().get("locations", [])]
            for d in date_list:
                try:
                    wd = get_weekday_from_date(_dt.strptime(d, "%Y-%m-%d"))
                except Exception:
                    continue
                # Map for this weekday: {location: count}
                weekday_counts = dag_teams.get(wd, {})
                # Initialize with all known locations
                row = {loc: int(weekday_counts.get(loc, 0)) for loc in locs}
                initial_plan[d] = row

            st.subheader("Shifts per datum en locatie (bewerkbaar)")
            # Editable grid via Streamlit inputs
            edited_plan = {}
            if initial_plan:
                df_plan = (
                    pd.DataFrame.from_dict(initial_plan, orient="index").reset_index()
                )
                df_plan = df_plan.rename(columns={"index": "date"})
                df_plan = df_plan.sort_values("date")
                # Use experimental data_editor if available, else two number_inputs per row
                try:
                    edited = st.data_editor(
                        df_plan,
                        num_rows="fixed",
                        use_container_width=True,
                        column_config={col: st.column_config.NumberColumn(min_value=0, step=1) for col in df_plan.columns if col != "date"},
                    )
                    for _, row in edited.iterrows():
                        dct = {col: int(row[col]) if pd.notna(row[col]) else 0 for col in df_plan.columns if col != "date"}
                        edited_plan[row["date"]] = dct
                except Exception:
                    # Fallback simple editor
                    for _, row in df_plan.iterrows():
                        cols = st.columns([2] + [1] * (len(df_plan.columns) - 1))
                        with cols[0]:
                            st.write(row["date"])  # label
                        updates = {}
                        for idx, col in enumerate([c for c in df_plan.columns if c != "date" ], start=1):
                            with cols[idx]:
                                updates[col] = st.number_input(
                                    f"{col} {row['date']}",
                                    min_value=0,
                                    step=1,
                                    value=int(row[col]) if pd.notna(row[col]) else 0,
                                )
                        edited_plan[row["date"]] = {k: int(v) for k, v in updates.items()}
            else:
                st.info("Geen datums gevonden om een shiftplan te maken.")

            # Persist the edited plan to JSON for main.py
            plan_path = None
            if edited_plan:
                import json

                plan_path = data_dir / "shift_plan.json"
                with open(plan_path, "w", encoding="utf-8") as fh:
                    json.dump(edited_plan, fh, ensure_ascii=False, indent=2)

        except Exception as e:
            st.warning(f"Kon geen bewerkbaar shift-overzicht maken: {e}")

    st.markdown("2) Controleer de waarden. Als alles goed is, genereer het rooster.")
    disabled = not (uploaded is not None and preview_ok)
    # Ensure defined in this scope even if upload block didn't run
    plan_path = locals().get("plan_path", None)
    if st.button("Genereer rooster (run main.py)", disabled=disabled):
        main_py = root / "src" / "main.py"
        py = _find_windows_python_in_venv(root) or Path(sys.executable)
        cmd = [str(py), "-X", "utf8", str(main_py)]
        if csv_path is not None:
            cmd += ["--csv", str(csv_path)]
        # If a plan JSON was created, pass it along
        if plan_path is not None:
            try:
                if getattr(plan_path, "exists", lambda: False)():
                    cmd += ["--shift-plan", str(plan_path)]
            except Exception:
                pass

        with st.spinner("Bezig met genereren van rooster..."):
            result = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        # Persist logs to disk for later inspection
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

        # Store in session_state so it stays visible after reruns
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

        # Show success or error message
        if result.returncode == 0:
            st.success("Rooster gegenereerd. Ga naar de tab 'Rooster' om het resultaat te bekijken.")
        else:
            st.error(f"Fout bij uitvoeren (code {result.returncode}). Zie output hierboven.")

        # Toon de uitvoer van main.py
        st.write("Uitvoer van main.py:")
        st.write(f"Python: {py}")
        if result.stdout:
            st.subheader("stdout")
            st.code(result.stdout)
        if result.stderr:
            st.subheader("stderr")
            st.code(result.stderr)
