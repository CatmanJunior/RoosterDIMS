import json
from pathlib import Path

import pandas as pd
import streamlit as st

from persons import csv_to_personlist
from config import get_locations_config


def render_testers_page(ds_conf: dict, project_root: object) -> None:
    """Render the Testers overview. Expects ds_conf from config and project_root (Path or str)."""
    st.title("👥 Testers Overzicht")

    # Laad brondata (altijd) om echte beschikbaarheid te tonen
    try:
        # Prefer uploaded files in preferences directory when available
        pref_dir_rel = ds_conf.get("preferences_dir", "data/preferences")
        prefs_dir = (project_root / pref_dir_rel) if hasattr(project_root, "__truediv__") else None
        uploaded_files = []
        if prefs_dir is not None and prefs_dir.exists():
            uploaded_files = sorted([p.name for p in prefs_dir.glob("uploaded_*.csv")])

        default_csv = ds_conf.get("default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv")

        if uploaded_files:
            choice_label = st.selectbox(
                "Kies geüpload bestand voor testers",
                ["(gebruik default)"] + uploaded_files,
                index=0,
            )
            if choice_label and choice_label != "(gebruik default)":
                csv_path = prefs_dir / choice_label
            else:
                csv_path = project_root / default_csv
        else:
            # No uploaded files – use configured default
            csv_path = project_root / default_csv

        people = csv_to_personlist(str(csv_path))
    except Exception as e:
        st.error(f"Kon testers niet laden: {e}")
        people = []

    if not people:
        st.stop()

    df_people = pd.DataFrame(people)

    # --- Mutual exclusions UI (prevent two people on same day) ---
    st.markdown("### ✋ Mutual exclusions (blokkeer twee personen op dezelfde dag)")
    names = sorted(df_people["name"].tolist())
    col1, col2, col3 = st.columns([3, 3, 2])
    with col1:
        p1 = st.selectbox("Persoon A", options=["(geen)"] + names, key="mutex_p1")
    with col2:
        p2 = st.selectbox("Persoon B", options=["(geen)"] + names, key="mutex_p2")
    with col3:
        if st.button("Voeg exclusie toe"):
            if p1 == "(geen)" or p2 == "(geen)":
                st.warning("Kies twee personen om een exclusie toe te voegen.")
            elif p1 == p2:
                st.warning("Kies twee verschillende personen.")
            else:
                # Persist exclusions to data/mutual_exclusions.json
                data_dir = Path(project_root) / "data"
                data_dir.mkdir(parents=True, exist_ok=True)
                excl_path = data_dir / "mutual_exclusions.json"
                try:
                    existing = []
                    if excl_path.exists():
                        existing = json.loads(excl_path.read_text(encoding="utf-8"))
                    pair = [p1, p2]
                    # Normalize order to avoid duplicates
                    pair_sorted = sorted(pair)
                    if pair_sorted not in existing:
                        existing.append(pair_sorted)
                        excl_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                        st.success(f"Exclusie toegevoegd: {p1} ⇄ {p2}")
                    else:
                        st.info("Deze exclusie bestaat al.")
                except Exception as e:
                    st.error(f"Kon exclusie niet opslaan: {e}")

    # Show existing exclusions with remove buttons
    data_dir = Path(project_root) / "data"
    excl_path = data_dir / "mutual_exclusions.json"
    if excl_path.exists():
        try:
            existing = json.loads(excl_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    else:
        existing = []

    if existing:
        st.markdown("**Huidige exclusies:**")
        for idx, pair in enumerate(existing):
            c1, c2 = st.columns([6, 1])
            with c1:
                st.write(f"{pair[0]} ⇄ {pair[1]}")
            with c2:
                if st.button("Verwijder", key=f"del_excl_{idx}"):
                    try:
                        existing.pop(idx)
                        excl_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Kon exclusie niet verwijderen: {e}")
    st.markdown("---")

    # Verzamel alle datums uit availability en maak een doorlopende reeks
    all_dates_set = set()
    for av in df_people["availability"]:
        if isinstance(av, dict):
            all_dates_set.update(av.keys())
    if not all_dates_set:
        st.info("Geen datums gevonden in availability.")
        st.stop()
    all_dates_sorted = sorted(all_dates_set)
    min_date = pd.to_datetime(all_dates_sorted[0])
    max_date = pd.to_datetime(all_dates_sorted[-1])
    full_range = pd.date_range(min_date, max_date)
    full_range_str = [d.strftime("%Y-%m-%d") for d in full_range]

    # Optioneel: beperk tot datums in rooster.csv
    use_rooster_dates = st.checkbox("Toon alleen datums uit rooster.csv", value=False)
    selected_dates = list(full_range_str)
    if use_rooster_dates:
        try:
            roster = pd.read_csv(ds_conf.get("rooster_csv", "rooster.csv"))
            rooster_dates = sorted(pd.to_datetime(roster["date"]).dt.strftime("%Y-%m-%d").unique())
            selected_dates = [d for d in full_range_str if d in set(rooster_dates)]
        except Exception:
            st.info("Kon rooster.csv niet lezen; toon alle datums.")

    # Extra filter: kies weekdagen
    if selected_dates:
        dt_ser = pd.to_datetime(pd.Series(selected_dates))
        weekday_map = {0: "ma", 1: "di", 2: "wo", 3: "do", 4: "vr", 5: "za", 6: "zo"}
        weekdagen = dt_ser.dt.weekday.map(weekday_map)
        unique_days = list(dict.fromkeys(weekdagen))
        chosen_days = st.multiselect("Filter op weekdag", options=unique_days, default=unique_days)
        selected_dates = [d for d, w in zip(selected_dates, weekdagen) if w in set(chosen_days)]

    # Extra filter: kies weeknummers
    if selected_dates:
        dt_ser = pd.to_datetime(pd.Series(selected_dates))
        weeknrs = dt_ser.dt.isocalendar().week.astype(int).tolist()
        unique_weeks = sorted(set(weeknrs))
        chosen_weeks = st.multiselect("Filter op weeknummer", options=unique_weeks, default=unique_weeks)
        selected_dates = [d for d, wn in zip(selected_dates, weeknrs) if wn in set(chosen_weeks)]

    # Bouw beschikbaarheidsmatrix
    # Basic columns
    base_cols = ["name", "role", "pref_location", "month_max", "month_avg"]
    avail_df = df_people[base_cols].copy()

    # Expand preference flags per configured location (pref_loc_flags is a dict per person)
    try:
        loc_conf = get_locations_config()
        locations = [loc.get("name") for loc in loc_conf.get("locations", [])]
    except Exception:
        locations = []

    pref_cols = []
    for loc in locations:
        # safe column name
        col_name = f"pref_loc_{str(loc).replace(' ', '_')}"
        pref_cols.append(col_name)
        avail_df[col_name] = df_people.get("pref_loc_flags", {}).apply(
            lambda flags, loc=loc: (flags.get(loc) if isinstance(flags, dict) else None)
        )

    # Availability date columns
    for d in selected_dates:
        avail_df[d] = df_people["availability"].apply(
            lambda x: bool(x.get(d, False)) if isinstance(x, dict) else False
        )

    # Samenvatting: aantal beschikbare dagen in selectie
    avail_cols = selected_dates
    avail_df["available_count"] = avail_df[avail_cols].sum(axis=1) if avail_cols else 0

    st.caption("Waar True betekent: beschikbaar. Pref kolommen tonen voorkeuren per locatie (bijv. 0/1/2).")
    st.dataframe(avail_df, use_container_width=True)
