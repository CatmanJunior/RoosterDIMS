import streamlit as st
import pandas as pd
import ast
from persons import person_list
st.set_page_config(layout="wide")
page = st.sidebar.radio("📚 Kies weergave", ["Rooster", "Statistieken","Testers"])

#run the app with `streamlit run src/schedule_app.py`

if page == "Rooster":
    # CSV inladen
    df = pd.read_csv("rooster.csv")

    # Omzetten van 'testers' kolom (string → list)
    df["testers"] = df["testers"].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else x
    )

    # Zet 'date' kolom om naar datetime object
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(by=["date", "location", "team"])

    # 👇 Streamlit UI
    st.title("📋 Roosteroverzicht")

    current_week = 0
    #display current week
    if "current_week" in st.session_state:
        current_week = st.session_state.current_week
    else:
        current_week = df["weeknummer"].min()  # Start met de laatste week in de data
    st.session_state.current_week = current_week


    # Week filter
    weeks = sorted(df["weeknummer"].unique())
    selected_week = st.selectbox("Kies weeknummer", weeks, index=0)

    #next previous buttons
    if st.button("Vorige week"):
        
        selected_week = max(weeks[0], current_week - 1)
        st.session_state.current_week = selected_week

    if st.button("Volgende week"):
        selected_week = min(current_week + 1, weeks[-1])
        st.session_state.current_week = selected_week
        

    



    filtered_df = df[df["weeknummer"] == selected_week].copy()

    # Zet testers als leesbare tekst
    filtered_df["testers"] = filtered_df["testers"].apply(lambda x: ", ".join(x))

    # Toon tabel
    st.dataframe(
        filtered_df[["date", "day", "location", "team", "testers"]]
        .sort_values(by=["date", "location", "team"])
        .reset_index(drop=True)
    )

elif page == "Statistieken":
    st.title("📊 Shiftoverzicht per tester")

    df = pd.read_csv("rooster.csv")
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
    # maak pagine breeder
    
    st.title("👥 Testers Overzicht")
    # Maak een DataFrame van de person_list
    df_testers = pd.DataFrame(person_list)
    # Maak een kolom per datum met beschikbaarheid
    for date in pd.date_range(start="2023-10-01", end="2023-12-31"):
        # if datum is di of do, voeg een kolom toe
        if date.weekday() not in [1, 3]:
            continue
        df_testers[date.strftime("%m-%d")] = df_testers["beschikbaar"].apply(
            lambda x: x.get(date.strftime("%Y-%m-%d"), False)
        )
    # remove the 'beschikbaar' column as it's no longer needed
    df_testers = df_testers.drop(columns=["beschikbaar"])
    # Toon de DataFrame in Streamlit
    # en maak het editbaar
    df_testers = st.data_editor(df_testers, use_container_width=True)
    # Sla de wijzigingen op in een CSV-bestand
    if st.button("Sla wijzigingen op"):
        df_testers.to_csv("testers.csv", index=False)
        st.success("Wijzigingen opgeslagen in testers.csv")