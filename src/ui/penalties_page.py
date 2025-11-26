import pandas as pd
import streamlit as st


def render_penalties_page(ds_conf: dict, project_root: object) -> None:
    """Render the Penalties overview. Expects ds_conf from config and project_root (Path or str)."""
    st.title("⚖️ Penalty Overzicht")

    # Summary
    try:
        summary = pd.read_csv(ds_conf.get("penalties_summary_csv", "penalties_summary.csv"))
        st.subheader("Samenvatting per component (gewogen)")
        st.dataframe(summary)
        # Exclude total row for charting
        chart_df = summary[summary["component"] != "__total__"].set_index("component")
        st.bar_chart(chart_df)
    except FileNotFoundError:
        st.info("Geen penalties_summary.csv gevonden. Draai eerst het model in main.py.")

    # Details
    st.subheader("Details")
    try:
        df = pd.read_csv(ds_conf.get("penalties_csv", "penalties.csv"))

        # Filters
        people = ["(alle)"] + sorted([p for p in df["person"].dropna().unique() if p != ""])
        components = ["(alle)"] + sorted(df["component"].dropna().unique())
        sel_person = st.selectbox("Filter op persoon", people)
        sel_component = st.selectbox("Filter op component", components)

        f = df.copy()
        if sel_person != "(alle)":
            f = f[f["person"] == sel_person]
        if sel_component != "(alle)":
            f = f[f["component"] == sel_component]

        st.dataframe(f)

        # Per-person breakdown by component
        st.subheader("Per persoon per component (gewogen)")
        if not df.empty:
            pivot = df.groupby(["person", "component"])["weighted"].sum().reset_index()
            pivot_table = pivot.pivot(index="person", columns="component", values="weighted").fillna(0)
            st.dataframe(pivot_table)
            st.bar_chart(pivot_table)
    except FileNotFoundError:
        st.info("Geen penalties.csv gevonden. Draai eerst het model in main.py.")
