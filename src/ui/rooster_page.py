import ast
import pandas as pd
import streamlit as st
from config import get_data_sources_config


def render_rooster_page() -> None:
    st.title("📋 Roosteroverzicht")

    # CSV inladen
    try:
        roster_path = get_data_sources_config().get("roster_csv", "rooster.csv")
        df = pd.read_csv(roster_path)
    except FileNotFoundError:
        st.info("Geen rooster gevonden. Genereer eerst een rooster via de Generator.")
        return

    # Parse 'testers' kolom naar een lijst voor aggregaties/overzichten
    testers_series = df["testers"].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else (x if isinstance(x, (list, tuple)) else [])
    )

    # 1) Overzicht: aantal shifts per persoon; Gem/maand en Max/maand uit voorkeuren
    exploded = df.assign(testers_list=testers_series).explode("testers_list")
    exploded = exploded.dropna(subset=["testers_list"])  # filter leeg
    exploded["testers_list"] = exploded["testers_list"].astype(str)
    exploded = exploded[exploded["testers_list"].str.len() > 0]

    if not exploded.empty:
        shift_counts = (
            exploded["testers_list"]
            .value_counts()
            .rename_axis("Persoon")
            .reset_index(name="Shifts")
        )
    else:
        shift_counts = pd.DataFrame(columns=["Persoon", "Shifts"]) 

    # Voeg voorkeuren toe (month_avg, month_max) op basis van de laatst gebruikte CSV indien bekend
    pref_df = pd.DataFrame(columns=["Persoon", "Gem/maand", "Max/maand"]) 
    try:
        # Zoek CSV pad: 1) uit laatste run (--csv), 2) recentste uploaded_*.csv, 3) fallback dummy files
        from pathlib import Path
        import os
        from persons import csv_to_personlist  # lazy import

        csv_path: str | None = None
        last_run = st.session_state.get("last_run")
        if last_run and isinstance(last_run.get("cmd"), list):
            cmd = last_run["cmd"]
            if "--csv" in cmd:
                try:
                    csv_path = cmd[cmd.index("--csv") + 1]
                except Exception:
                    csv_path = None
        if not csv_path:
            root = Path(__file__).resolve().parents[2]
            data_dir = root / "data"
            try:
                uploaded = sorted(
                    [p for p in data_dir.glob("uploaded_*.csv")],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if uploaded:
                    csv_path = str(uploaded[0])
            except Exception:
                pass
        if not csv_path:
            for candidate in (
                get_data_sources_config().get("default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv"),
            ):
                if os.path.exists(candidate):
                    csv_path = candidate
                    break

        if csv_path:
            persons = csv_to_personlist(csv_path)
            if isinstance(persons, list) and persons:
                pref_df = pd.DataFrame(
                    [
                        {
                            "Persoon": p.get("name"),
                            "Gem/maand": p.get("month_avg"),
                            "Max/maand": p.get("month_max"),
                        }
                        for p in persons
                        if isinstance(p, dict)
                    ]
                )
                # Zorg voor juiste types
                pref_df["Gem/maand"] = pd.to_numeric(pref_df["Gem/maand"], errors="coerce")
                pref_df["Max/maand"] = pd.to_numeric(pref_df["Max/maand"], errors="coerce")
    except Exception:
        pass

    # Merge voorkeuren in de shifts-tabel
    if not shift_counts.empty and not pref_df.empty:
        shift_counts = shift_counts.merge(pref_df, on="Persoon", how="left")
    else:
        # Voeg lege kolommen toe als er geen voorkeuren beschikbaar zijn
        shift_counts["Gem/maand"] = pd.NA
        shift_counts["Max/maand"] = pd.NA

    # Sortering
    if not shift_counts.empty:
        shift_counts = shift_counts.sort_values(by=["Shifts", "Gem/maand"], ascending=[False, False]).reset_index(drop=True)

    # 2) Overzicht: penalties per persoon (gewogen som indien beschikbaar)
    penalties_per_person = pd.DataFrame()
    try:
        p = pd.read_csv(get_data_sources_config().get("penalties_csv", "penalties.csv"))
        if not p.empty:
            if "component" in p.columns:
                if "weighted" in p.columns:
                    agg = p.groupby(["person", "component"])["weighted"].sum().reset_index()
                    value_col = "weighted"
                else:
                    agg = p.groupby(["person", "component"]).size().reset_index(name="count")
                    value_col = "count"

                # Draai naar brede tabel: kolommen per component
                penalties_per_person = agg.pivot(index="person", columns="component", values=value_col).fillna(0)
                # Voeg totaal kolom toe
                penalties_per_person["Totaal"] = penalties_per_person.sum(axis=1)
                penalties_per_person = penalties_per_person.sort_values(by="Totaal", ascending=False).reset_index()
                penalties_per_person = penalties_per_person.rename(columns={"person": "Persoon"})
            else:
                # Geen component kolom, val terug naar totaaltelling
                if "weighted" in p.columns:
                    g = p.groupby("person")["weighted"].sum().reset_index()
                    penalties_per_person = g.rename(columns={"person": "Persoon", "weighted": "Totaal"})
                else:
                    g = p.groupby("person").size().reset_index(name="Totaal")
                    penalties_per_person = g.rename(columns={"person": "Persoon"})
    except FileNotFoundError:
        # Toon lege tabel als penalties nog niet bestaan
        penalties_per_person = pd.DataFrame(columns=["Persoon"]) 

    # Toon de samenvattingstabellen naast elkaar (horizontale grid)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Shifts per persoon")
        st.dataframe(shift_counts, use_container_width=True, height=260, hide_index=True)
    with col2:
        st.subheader("Penalties per persoon (per component)")
        st.dataframe(
            penalties_per_person,
            use_container_width=True,
            height=260,
            hide_index=True,
        )

    # Tabelweergave van het rooster: testers als comma-joined string
    df_display = df.copy()
    df_display["testers"] = testers_series.apply(lambda xs: ", ".join(map(str, xs)) if isinstance(xs, (list, tuple)) else "")
    df_display = df_display.sort_values(by=["date", "location", "team"]).reset_index(drop=True)

    # Simpele tabelweergave
    st.dataframe(
    df_display[["date", "day", "location", "team", "testers"]],
        use_container_width=True,
    )
