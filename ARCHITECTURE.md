# Shock Timer architecture

`run_timer_app.py` is the Streamlit entry point. It owns only the interactive
views: experiment configuration, dialogs, dashboard rendering, and the small
browser-side helpers required by Streamlit.

The reusable application code lives in `shock_timer/`:

- `settings.py` — production/test timing and UI constants.
- `state.py` — the persisted session schema and timer/value helpers.
- `persistence.py` — SQLite/PostgreSQL storage and experiment records.
- `workflow.py` — stage transitions, alerts, measurements, and undo.
- `reporting.py` — audit events and timesheet exports.
- `subjects.py` — profile validation, adding subjects, and ordering.
- `styles.py` — the complete application stylesheet.

The persisted JSON keys are intentionally unchanged, so saved experiments are
compatible with the refactored version. A test suite can import these modules
without importing the Streamlit UI entry point.
