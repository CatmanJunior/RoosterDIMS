from __future__ import annotations

from datetime import datetime as _dt
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from config import (
    get_departments_config,
    get_department_defaults,
    get_locations_config,
    get_data_sources_config,
)


def _resolve_path(root: Path, path_value: str | None) -> Path:
    if not path_value:
        return root / "config" / "locations.json"
    p = Path(path_value)
    return p if p.is_absolute() else (root / p)


def _date_is_valid(value: str) -> bool:
    try:
        _dt.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _dept_slug(name: str | None) -> str:
    return (name or "default").strip().replace(" ", "_")


def _quarter_date_range(year: int, quarter: str) -> list[str]:
    q_map = {
        "Q1": (1, 1, 3, 31),
        "Q2": (4, 1, 6, 30),
        "Q3": (7, 1, 9, 30),
        "Q4": (10, 1, 12, 31),
    }
    start_m, start_d, end_m, end_d = q_map.get(quarter, (1, 1, 3, 31))
    start = _dt(year, start_m, start_d)
    end = _dt(year, end_m, end_d)
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end)]


def _weekday_key(date_str: str) -> str:
    dt = _dt.strptime(date_str, "%Y-%m-%d")
    return ["ma", "di", "wo", "do", "vr", "za", "zo"][dt.weekday()]


def render_shifts_page() -> None:
    st.title("🗓️ Shiftplan bewerken")

    root = Path(__file__).resolve().parent.parent.parent
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

    ds_conf = get_data_sources_config()
    dept_defaults = get_department_defaults(selected_department)
    dept_ds_overrides = (
        dept_defaults.get("data_sources", {}) if isinstance(dept_defaults, dict) else {}
    )
    ds_conf = {**ds_conf, **dept_ds_overrides}
    locations_config_path = (
        dept_defaults.get("locations_config") if isinstance(dept_defaults, dict) else None
    )
    conf_path = _resolve_path(root, locations_config_path)

    try:
        loc_conf = get_locations_config(str(conf_path))
    except FileNotFoundError:
        st.error("Locatieconfig niet gevonden. Maak eerst een configbestand aan.")
        st.stop()

    locations = [loc.get("name") for loc in loc_conf.get("locations", []) if loc.get("name")]

    st.markdown("### 1) Locatie-eisen (peer/tester)")
    loc_rows: list[dict[str, Any]] = []
    for loc in loc_conf.get("locations", []):
        name = loc.get("name")
        if not name:
            continue
        allow_peer = bool(loc.get("allow_peer", int(loc.get("peers", 1)) != 0))
        allow_tester = bool(loc.get("allow_tester", True))
        loc_rows.append(
            {
                "location": name,
                "allow_peer": allow_peer,
                "allow_tester": allow_tester,
            }
        )

    loc_df = pd.DataFrame(loc_rows)
    loc_edited = st.data_editor(
        loc_df,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "location": st.column_config.TextColumn("Locatie"),
            "allow_peer": st.column_config.CheckboxColumn("Peer"),
            "allow_tester": st.column_config.CheckboxColumn("Tester"),
        },
    )

    st.markdown("### 2) Standaard open dagen per locatie")
    weekday_cols = ["ma", "di", "wo", "do", "vr", "za", "zo"]
    day_rows: list[dict[str, Any]] = []
    for loc in loc_conf.get("locations", []):
        name = loc.get("name")
        if not name:
            continue
        defaults = loc.get("teams_per_day", {}) or {}
        row = {"location": name}
        for wd in weekday_cols:
            row[wd] = int(defaults.get(wd, 0) or 0)
        day_rows.append(row)

    day_df = pd.DataFrame(day_rows)
    day_edited = st.data_editor(
        day_df,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "location": st.column_config.TextColumn("Locatie"),
            **{wd: st.column_config.NumberColumn(wd, min_value=0, step=1) for wd in weekday_cols},
        },
    )

    st.markdown("### 3) Teams per datum en locatie")
    current_year = _dt.now().year
    selected_year = st.session_state.get("global_year", current_year)
    selected_quarter = st.session_state.get("global_quarter", "Q1")

    shiftplans_dir = ds_conf.get("shiftplans_dir", "data/shiftplans")
    shiftplan_path = root / shiftplans_dir / _dept_slug(selected_department) / f"{selected_year}_{selected_quarter}.json"
    state_key = f"teams_df_{_dept_slug(selected_department)}_{selected_year}_{selected_quarter}"

    plan_from_conf: dict[str, dict[str, int]] = {}
    if shiftplan_path.exists():
        try:
            import json as _json

            payload = _json.loads(shiftplan_path.read_text(encoding="utf-8"))
            plan_from_conf = payload.get("teams_per_date", {}) or {}
        except Exception:
            plan_from_conf = {}

    if state_key not in st.session_state:
        st.session_state[state_key] = plan_from_conf

    # Build teams table
    working_plan: dict[str, dict[str, int]] = st.session_state.get(state_key, {})
    all_dates = sorted(working_plan.keys())
    rows: list[dict[str, Any]] = []
    for date in all_dates:
        row: dict[str, Any] = {"date": date, "remove": False}
        for loc in locations:
            row[loc] = int(working_plan.get(date, {}).get(loc, 0) or 0)
        rows.append(row)

    teams_df = (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["date", "remove", *locations])
    )
    column_config = {
        "date": st.column_config.TextColumn("date", help="YYYY-MM-DD"),
        "remove": st.column_config.CheckboxColumn("Verwijder"),
    }
    for loc in locations:
        column_config[loc] = st.column_config.NumberColumn(f"{loc} teams", min_value=0, step=1)

    teams_edited = st.data_editor(
        teams_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config=column_config,
    )

    st.markdown("#### Hulpmiddelen")
    col_add, col_gen, col_remove = st.columns([2, 2, 2])
    with col_add:
        new_date = st.date_input("Voeg dag toe", value=_dt.now().date(), key="add_day")
        if st.button("Dag toevoegen") and new_date:
            date_str = new_date.strftime("%Y-%m-%d")
            if date_str not in working_plan:
                # seed using weekday defaults
                day_defaults = {row["location"]: row for _, row in day_edited.iterrows()}
                wd = _weekday_key(date_str)
                working_plan[date_str] = {}
                for loc in locations:
                    default_val = int(day_defaults.get(loc, {}).get(wd, 0) or 0)
                    if default_val > 0:
                        working_plan[date_str][loc] = default_val
                st.session_state[state_key] = working_plan
                st.rerun()
            else:
                st.info("Deze datum bestaat al in het shiftplan.")

    with col_gen:
        if st.button("Genereer op basis van standaarddagen"):
            day_defaults = {row["location"]: row for _, row in day_edited.iterrows()}
            generated: dict[str, dict[str, int]] = {}
            for date_str in _quarter_date_range(selected_year, selected_quarter):
                wd = _weekday_key(date_str)
                for loc in locations:
                    val = int(day_defaults.get(loc, {}).get(wd, 0) or 0)
                    if val > 0:
                        generated.setdefault(date_str, {})[loc] = val
            st.session_state[state_key] = generated
            st.rerun()

    with col_remove:
        if all_dates and st.button("Verwijder gemarkeerde dagen"):
            to_remove = set()
            for _, row in teams_edited.iterrows():
                if bool(row.get("remove", False)):
                    to_remove.add(str(row.get("date", "")).strip())
            for d in to_remove:
                working_plan.pop(d, None)
            st.session_state[state_key] = working_plan
            st.rerun()

    if st.button("Opslaan shiftplan"):
        import json as _json

        invalid_dates = []
        teams_per_date: dict[str, dict[str, int]] = {}
        for _, row in teams_edited.iterrows():
            date_val = str(row.get("date", "")).strip()
            if not date_val:
                continue
            if bool(row.get("remove", False)):
                continue
            if not _date_is_valid(date_val):
                invalid_dates.append(date_val)
                continue
            for loc in locations:
                teams = int(row.get(loc, 0) or 0)
                if teams <= 0:
                    continue
                teams_per_date.setdefault(date_val, {})[loc] = teams

        if invalid_dates:
            st.warning(
                "Ongeldige datums overgeslagen: " + ", ".join(sorted(set(invalid_dates)))
            )

        # Update location requirements
        loc_map = {row["location"]: row for _, row in loc_edited.iterrows()}
        for loc in loc_conf.get("locations", []):
            name = loc.get("name")
            if not name or name not in loc_map:
                continue
            loc["allow_peer"] = bool(loc_map[name].get("allow_peer", True))
            loc["allow_tester"] = bool(loc_map[name].get("allow_tester", True))

        # Update default open days
        day_map = {row["location"]: row for _, row in day_edited.iterrows()}
        for loc in loc_conf.get("locations", []):
            name = loc.get("name")
            if not name or name not in day_map:
                continue
            loc["teams_per_day"] = {
                wd: int(day_map[name].get(wd, 0) or 0) for wd in weekday_cols
            }

        # Save locations config
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        conf_path.write_text(
            _json.dumps(loc_conf, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Save shiftplan file
        shiftplan_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "year": selected_year,
            "quarter": selected_quarter,
            "teams_per_date": teams_per_date,
        }
        shiftplan_path.write_text(
            _json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        st.success(
            f"Shiftplan opgeslagen: {shiftplan_path.relative_to(root)}"
        )

    st.markdown("---")
    st.caption("Tip: gebruik de Generator voor het daadwerkelijke rooster; dit scherm beheert het shiftplan per afdeling.")
