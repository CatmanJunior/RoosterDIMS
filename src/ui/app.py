import sys
from pathlib import Path
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
    from ui.rooster_page import render_rooster_page  # type: ignore
    from ui.generator_page import render_generator_page  # type: ignore
    from ui.testers_page import render_testers_page  # type: ignore
    from ui.penalties_page import render_penalties_page  # type: ignore
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
            st.error(
                "Authenticatie vereist, maar modules ontbreken. Installeer afhankelijkheden of zet enable_auth op false."
            )
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
            st.error(
                "Authenticatieconfiguratie ontbreekt (.streamlit/auth.yaml). Toegang geblokkeerd."
            )
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
        ["Generator", "Rooster", "Testers", "Penalties"],
    )

    if page == "Rooster":
        render_rooster_page()

    elif page == "Testers":
        render_testers_page(ds_conf, _PROJECT_ROOT)

    elif page == "Penalties":
        render_penalties_page(ds_conf, _PROJECT_ROOT)

    elif page == "Generator":
        render_generator_page()


if __name__ == "__main__":
    main()
