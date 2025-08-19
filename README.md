# RoosterDIMS

A CP-SAT based roster generator with a Streamlit UI.

## Quick start

- Install dependencies:
  - Create/activate a virtualenv (optional) and install requirements with `pip install -r requirements.txt`.
- Run the UI:
  - `streamlit run src/ui/app.py`
- test login: u:alice ww:haha
- Generate a roster via the "Generator" tab, then explore results in the other tabs.

## CLI

You can run the solver directly:

- `python -X utf8 src/main.py --csv data/Dummy_Test_Data_sanitized_november.csv [--verbose]`

Set `ROOSTER_VERBOSE=1` to see extra constraint logging.

## Outputs

- `rooster.csv` – the generated roster
- `penalties.csv` and `penalties_summary.csv` – penalty breakdown
- `run_logs/` – captured stdout/stderr from UI runs

## Data

Place input CSVs under `data/`. The UI also persists uploaded files as `data/uploaded_*.csv`.

Shifts per date/location are taken from `config/locations.json` (teams_per_date preferred, falling back to teams_per_day weekday defaults). Use the Generator tab to edit and save these values.
