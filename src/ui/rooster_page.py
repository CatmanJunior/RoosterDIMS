import ast
import pandas as pd
import streamlit as st
from config import get_data_sources_config


def _read_diagnostics() -> pd.DataFrame:
    """Read optional diagnostics about unplannable days from CSV.

    The CLI can write a small diagnostics file when no solution is found;
    if present, we show it here to explain why dagen niet planbaar zijn.
    """
    ds_conf = get_data_sources_config()
    diag_path = ds_conf.get("diagnostics_csv", None)
    if not diag_path:
        # Default next to rooster.csv
        roster_path = ds_conf.get("rooster_csv", "rooster.csv")
        import os

        root, base = os.path.split(roster_path)
        diag_path = os.path.join(root, "rooster_diagnostics.csv")
    try:
        return pd.read_csv(diag_path)
    except FileNotFoundError:
        return pd.DataFrame()


def render_rooster_page() -> None:
    st.title("📋 Roosteroverzicht")

    # CSV inladen
    try:
        roster_path = get_data_sources_config().get("roster_csv", "rooster.csv")
        df = pd.read_csv(roster_path)
    except FileNotFoundError:
        st.info("Geen rooster gevonden. Genereer eerst een rooster via de Generator.")
        # Probeer uitleg te geven waarom plannen niet gelukt is
        diag_df = _read_diagnostics()
        if not diag_df.empty:
            st.subheader("❗ Niet-planbare dagen/locaties")
            st.dataframe(diag_df, use_container_width=True)
        return

    # Parse 'testers' kolom naar een lijst voor aggregaties/overzichten
    testers_series = df["testers"].apply(
        lambda x: ast.literal_eval(x)
        if isinstance(x, str)
        else (x if isinstance(x, (list, tuple)) else [])
    )

    # 1) Overzicht: aantal shifts per persoon; plus actuele Gem/maand en Max/maand
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

    # Bereken actuele gemiddelde en maximale shifts per maand op basis van het gegenereerde rooster
    if not exploded.empty and "date" in exploded.columns:
        try:
            dates = pd.to_datetime(exploded["date"], errors="coerce")
            exploded = exploded.assign(_month=dates.dt.to_period("M"))
            monthly_counts = (
                exploded.dropna(subset=["_month"])
                .groupby(["testers_list", "_month"])
                .size()
                .reset_index(name="cnt")
            )
            # Gemiddelde en maximum per persoon over de maanden waarin ze shifts hebben
            stats = (
                monthly_counts.groupby("testers_list")["cnt"]
                .agg(avg="mean", max="max")
                .reset_index()
            )
            stats = stats.rename(
                columns={
                    "testers_list": "Persoon",
                    "avg": "Gem/maand (actueel)",
                    "max": "Max/maand (actueel)",
                }
            )
            shift_counts = shift_counts.merge(stats, on="Persoon", how="left")
        except Exception:
            # Als iets misgaat met datum parsing, voeg lege kolommen toe
            shift_counts["Gem/maand (actueel)"] = pd.NA
            shift_counts["Max/maand (actueel)"] = pd.NA
    else:
        shift_counts["Gem/maand (actueel)"] = pd.NA
        shift_counts["Max/maand (actueel)"] = pd.NA

    # Sortering
    if not shift_counts.empty:
        sort_by = [
            c for c in ["Shifts", "Gem/maand (actueel)"] if c in shift_counts.columns
        ]
        if sort_by:
            shift_counts = shift_counts.sort_values(
                by=sort_by, ascending=[False] * len(sort_by)
            ).reset_index(drop=True)

    # 2) Overzicht: penalties per persoon (gewogen som indien beschikbaar)
    penalties_per_person = pd.DataFrame()
    try:
        p = pd.read_csv(get_data_sources_config().get("penalties_csv", "penalties.csv"))
        if not p.empty:
            if "component" in p.columns:
                if "weighted" in p.columns:
                    agg = (
                        p.groupby(["person", "component"])["weighted"]
                        .sum()
                        .reset_index()
                    )
                    value_col = "weighted"
                else:
                    agg = (
                        p.groupby(["person", "component"])
                        .size()
                        .reset_index(name="count")
                    )
                    value_col = "count"

                # Draai naar brede tabel: kolommen per component
                penalties_per_person = agg.pivot(
                    index="person", columns="component", values=value_col
                ).fillna(0)
                # Voeg totaal kolom toe
                penalties_per_person["Totaal"] = penalties_per_person.sum(axis=1)
                penalties_per_person = penalties_per_person.sort_values(
                    by="Totaal", ascending=False
                ).reset_index()
                penalties_per_person = penalties_per_person.rename(
                    columns={"person": "Persoon"}
                )
            else:
                # Geen component kolom, val terug naar totaaltelling
                if "weighted" in p.columns:
                    g = p.groupby("person")["weighted"].sum().reset_index()
                    penalties_per_person = g.rename(
                        columns={"person": "Persoon", "weighted": "Totaal"}
                    )
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
        st.dataframe(
            shift_counts, use_container_width=True, height=260, hide_index=True
        )
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
    df_display["testers"] = testers_series.apply(
        lambda xs: ", ".join(map(str, xs)) if isinstance(xs, (list, tuple)) else ""
    )
    df_display = df_display.sort_values(by=["date", "location", "team"]).reset_index(
        drop=True
    )

    # Simpele tabelweergave
    st.dataframe(
        df_display[["date", "day", "location", "team", "testers"]],
        use_container_width=True,
    )
