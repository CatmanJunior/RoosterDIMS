import ast
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
# Auth libraries are imported lazily inside main() based on config

# Ensure project root is importable when running `streamlit run src/ui/app.py`
_THIS_FILE = Path(__file__).resolve()
_SRC_DIR = _THIS_FILE.parent.parent  # .../src
_PROJECT_ROOT = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Project imports are performed inside main() after sys.path tweaks


def main() -> None:
    st.set_page_config(layout="wide")
    # Import project modules now that sys.path is prepared
    from persons import csv_to_personlist  # type: ignore
    from ui.rooster_page import render_rooster_page  # type: ignore
    from ui.generator_page import render_generator_page  # type: ignore
    from config import get_data_sources_config, get_locations_config  # type: ignore

    # Load configs for visibility
    ds_conf = get_data_sources_config()
    loc_conf = get_locations_config()

    # Auth: require login if enabled in config
    enable_auth = bool(ds_conf.get("enable_auth", False))
    authenticator = None
    name = None
    auth_status = True  # default to allowed when auth is disabled
    username = None
    if enable_auth:
        try:
            import yaml
            from yaml.loader import SafeLoader
            import streamlit_authenticator as stauth
        except Exception:
            st.error("Authenticatie vereist, maar modules ontbreken. Installeer afhankelijkheden of zet enable_auth op false.")
            st.stop()
        try:
            auth_path = _PROJECT_ROOT / ".streamlit" / "auth.yaml"
            with open(auth_path, "r", encoding="utf-8") as f:
                config = yaml.load(f, Loader=SafeLoader)
            authenticator = stauth.Authenticate(
                config.get("credentials", {}),
                config.get("cookie", {}).get("name", "rooster_cookie"),
                config.get("cookie", {}).get("key", "CHANGE_ME"),
                config.get("cookie", {}).get("expiry_days", 7),
            )
            login_result = authenticator.login("sidebar")
            if login_result is None:
                # Some versions set session_state instead of returning tuple
                name = st.session_state.get("name")
                auth_status = st.session_state.get("authentication_status")
                username = st.session_state.get("username")
            else:
                name, auth_status, username = login_result
        except FileNotFoundError:
            st.error("Authenticatieconfiguratie ontbreekt (.streamlit/auth.yaml). Toegang geblokkeerd.")
            st.stop()
        except Exception as e:
            st.error(f"Fout bij laden authenticatie: {e}")
            st.stop()

        if auth_status is False:
            st.error("Onjuiste gebruikersnaam of wachtwoord.")
            st.stop()
        if auth_status is None:
            st.info("Log in om verder te gaan.")
            st.stop()

    with st.sidebar.expander("Config", expanded=False):
        st.caption("Data sources")
        st.json(ds_conf)
        st.caption("Locations")
        st.json(loc_conf)

    if enable_auth and authenticator is not None:
        try:
            authenticator.logout("Uitloggen", location="sidebar")
        except Exception:
            pass
        if name:
            st.sidebar.caption(f"Ingelogd als: {name}")

    page = st.sidebar.radio(
        "📚 Kies weergave",
        ["Rooster", "Statistieken", "Testers", "Penalties", "Generator"],
    )

    if page == "Rooster":
        render_rooster_page()

    elif page == "Statistieken":
        st.title("📊 Shiftoverzicht per tester")
        roster_path = ds_conf.get("roster_csv", "rooster.csv")
        df = pd.read_csv(roster_path)
        df["testers"] = df["testers"].apply(
            lambda x: ast.literal_eval(x) if isinstance(x, str) else x
        )

        # Explode testers → 1 rij per persoon per shift
        exploded_df = df.explode("testers")

        # Groepeer en tel
        counts = exploded_df["testers"].value_counts().reset_index()
        counts.columns = ["Naam", "Aantal Shifts"]

        # Tabel weergeven
        st.dataframe(counts)

        # Optioneel: staafdiagram
        st.bar_chart(counts.set_index("Naam"))

    elif page == "Testers":
        st.title("👥 Testers Overzicht")

        # Laad brondata (altijd) om echte beschikbaarheid te tonen
        try:
            people = csv_to_personlist(ds_conf.get("default_persons_csv", "data/Data_sanitized_OKT-DEC2025.csv"))
        except Exception as e:
            st.error(f"Kon testers niet laden: {e}")
            people = []

        if not people:
            st.stop()

        df_people = pd.DataFrame(people)

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
                rooster = pd.read_csv(ds_conf.get("roster_csv", "rooster.csv"))
                rooster_dates = sorted(pd.to_datetime(rooster["date"]).dt.strftime("%Y-%m-%d").unique())
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
        base_cols = ["name", "role", "pref_location", "month_max", "month_avg"]
        avail_df = df_people[base_cols].copy()
        for d in selected_dates:
            avail_df[d] = df_people["availability"].apply(
                lambda x: bool(x.get(d, False)) if isinstance(x, dict) else False
            )

        # Samenvatting: aantal beschikbare dagen in selectie
        avail_cols = selected_dates
        avail_df["available_count"] = avail_df[avail_cols].sum(axis=1) if avail_cols else 0

        st.caption("Waar True betekent: beschikbaar")
        st.dataframe(avail_df, use_container_width=True)

    elif page == "Penalties":
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
                pivot = (
                    df.groupby(["person", "component"]) ["weighted"].sum().reset_index()
                )
                pivot_table = pivot.pivot(index="person", columns="component", values="weighted").fillna(0)
                st.dataframe(pivot_table)
                st.bar_chart(pivot_table)
        except FileNotFoundError:
            st.info("Geen penalties.csv gevonden. Draai eerst het model in main.py.")

    elif page == "Generator":
        render_generator_page()


if __name__ == "__main__":
    main()
