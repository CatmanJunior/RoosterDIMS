from pathlib import Path

import pandas as pd
import streamlit as st

from config import get_data_sources_config


def _find_diagnostics_files(roster_folder: Path) -> list[Path]:
    """Return all rooster_diagnostics.csv files under roster_folder, newest first."""
    try:
        files = sorted(
            roster_folder.rglob("rooster_diagnostics.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return files
    except Exception:
        return []


def _current_diag_path(
    roster_folder: Path, year: int | None, quarter: str | None
) -> Path | None:
    """Return the expected diagnostics path for the active year/quarter."""
    if year and quarter:
        return roster_folder / str(year) / str(quarter) / "rooster_diagnostics.csv"
    return None


def _load_diag(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"Kon diagnoserbestand niet laden: {e}")
        return pd.DataFrame()


def _style_diag_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-friendly copy with bool flags as symbols."""
    display = df.copy()
    flag_cols = [c for c in df.columns if c.startswith("c_")]
    for col in flag_cols:
        display[col] = display[col].apply(
            lambda v: "✓" if str(v).strip().lower() in ("true", "1", "yes") else "✗"
        )
    return display


def render_diagnose_page() -> None:
    st.title("🔍 Diagnose: niet-planbare dagen")

    root = Path(__file__).resolve().parents[2]

    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else root / path

    ds_conf = get_data_sources_config()
    roster_folder = _resolve(ds_conf.get("roster_folder", "data/generated/roosters"))
    selected_year = st.session_state.get("global_year")
    selected_quarter = st.session_state.get("global_quarter")

    # Current run's expected path
    current_path = _current_diag_path(roster_folder, selected_year, selected_quarter)

    # Scan for all historical diagnostics files
    all_files = _find_diagnostics_files(roster_folder)

    if not all_files and (current_path is None or not current_path.exists()):
        st.info(
            "Geen mislukte roosters gevonden. Diagnostiekbestanden worden aangemaakt wanneer "
            "de generator geen oplossing kan vinden."
        )
        return

    # Build selectbox options
    options: list[Path] = []
    if current_path and current_path.exists() and current_path not in all_files:
        options.append(current_path)
    options.extend(all_files)
    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_options: list[Path] = []
    for p in options:
        if p not in seen:
            seen.add(p)
            unique_options.append(p)

    if not unique_options:
        st.info("Geen diagnoserbestanden gevonden.")
        return

    def _label(p: Path) -> str:
        # Show relative path under roster_folder for readability
        try:
            return str(p.relative_to(roster_folder))
        except ValueError:
            return p.name

    selected_file = st.selectbox(
        "Kies diagnoserbestand",
        options=unique_options,
        index=0,
        format_func=_label,
    )
    st.caption(f"Bestand: `{selected_file}`")

    df = _load_diag(selected_file)
    if df.empty:
        st.info("Geen gegevens gevonden in het geselecteerde diagnoserbestand.")
        return

    # Summary counts
    total_rows = len(df)
    shortage_rows = df[df["assigned"] < df["required"]] if "assigned" in df.columns and "required" in df.columns else df
    n_shortage = len(shortage_rows)
    n_ok = total_rows - n_shortage

    col1, col2, col3 = st.columns(3)
    col1.metric("Totaal dagen/locaties", total_rows)
    col2.metric("Onderbezet", n_shortage, delta=None)
    col3.metric("Volledig gepland", n_ok)

    st.markdown("---")

    # Display table with highlighting
    display_df = _style_diag_df(df)

    # Rename flag columns for display
    rename_map = {
        "c_availability": "Beschikbaarheid",
        "c_max_per_day": "Max/dag",
        "c_max_per_week": "Max/week",
        "c_single_first": "Eerste tester",
        "c_exclusions": "Uitsluitingen",
    }
    display_df = display_df.rename(columns=rename_map)

    def _highlight_shortage(row: pd.Series):
        try:
            if int(row.get("assigned", 0)) < int(row.get("required", 0)):
                return ["background-color: #ffd6d6"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    st.subheader("Overzicht niet-planbare dagen")
    st.dataframe(
        display_df.style.apply(_highlight_shortage, axis=1),
        use_container_width=True,
    )

    # Per-constraint breakdown
    flag_display_cols = [rename_map.get(c, c) for c in ["c_availability", "c_max_per_day", "c_max_per_week", "c_single_first", "c_exclusions"] if rename_map.get(c, c) in display_df.columns]
    if flag_display_cols and n_shortage > 0:
        st.markdown("### Meest voorkomende oorzaken")
        cause_counts = {}
        for col in flag_display_cols:
            n = (display_df.loc[df["assigned"] < df["required"], col] == "✓").sum() if "assigned" in df.columns and "required" in df.columns else (display_df[col] == "✓").sum()
            cause_counts[col] = int(n)
        cause_df = (
            pd.DataFrame.from_dict(cause_counts, orient="index", columns=["Aantal"])
            .sort_values("Aantal", ascending=False)
        )
        st.bar_chart(cause_df)

    st.markdown("---")
    st.caption(
        "Rijen met rode achtergrond hebben minder testers toegewezen dan vereist. "
        "Vink 'Partieel genereren' aan op de Generator pagina om toch een rooster te maken."
    )
