import base64
import html
import json
import os
import time
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

# ============================================================
# APP SETTINGS
# ============================================================

# Use "seconds" for quick debugging and "minutes" for production.
TIME_UNIT = "minutes"  # "seconds" or "minutes"

# UI refresh cadence. Timers display to the nearest second.
REFRESH_INTERVAL = 1.0

# Anesthesia timing remains configurable. The procedural stage durations below
# are intentionally fixed and are NOT exposed as editable UI controls.
DEFAULT_ANESTHESIA = 30
DEFAULT_ANESTHESIA_DELAY = 5
FIXED_BOARD_DURATION = 10
FIXED_SHOCK_DURATION = 60
FIXED_RESUSCITATION_DURATION = 20

INITIAL_MOUSE_COUNT = 8

# Warning window before a deadline. Set to 0 to disable early warning.
WARNING_UNITS = 2

# Absolute shock-start clock shown after an experiment is ended.
APP_TIMEZONE = "America/New_York"

# Bump this when changing state structure/defaults during development.
STATE_VERSION = "lab_multitimer_v29_fast_management_auto_export"

# ============================================================
# DERIVED SETTINGS / PAGE CONFIG
# ============================================================

UNIT_SECONDS = 1.0 if TIME_UNIT == "seconds" else 60.0
UNIT_SHORT = "s" if TIME_UNIT == "seconds" else "m"
UNIT_LABEL = "sec" if TIME_UNIT == "seconds" else "min"

st.set_page_config(
    page_title="Shock Timer",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# GLOBAL VISUAL STYLING
# ============================================================

st.markdown(
    """
    <style>
    :root {
        --lab-bg: #0c121b;
        --lab-panel: #151d27;
        --lab-panel-2: #111923;
        --lab-border: rgba(148, 163, 184, 0.22);
        --lab-border-soft: rgba(148, 163, 184, 0.13);
        --lab-text: #f3f4f6;
        --lab-muted: #aab4c2;
        --lab-green: #65c46d;
        --lab-orange: #ff980f;
        --lab-red: #e94d62;
        --lab-gray: #7d8791;
    }

    html, body, [data-testid="stAppViewContainer"], .stApp {
        background: radial-gradient(circle at 52% 0%, #111b28 0%, var(--lab-bg) 45%, #091019 100%);
    }

    [data-testid="stAppViewContainer"] > .main {
        background: transparent;
    }

    .stMainBlockContainer {
        max-width: 100% !important;
        padding: 0.18rem 0.85rem 1rem 0.85rem !important;
    }


    /* Remove Streamlit chrome so the dashboard reads as a purpose-built app. */
    [data-testid="stHeader"], [data-testid="stToolbar"], footer {
        display: none !important;
    }

    /* Compact Streamlit's vertical rhythm. */
    [data-testid="stVerticalBlock"] {
        gap: 0.38rem;
    }
    [data-testid="stHorizontalBlock"] {
        gap: 0.55rem;
    }

    /* Header */
    .lab-header-title {
        font-size: 1.72rem;
        line-height: 1.0;
        font-weight: 790;
        color: var(--lab-text);
        margin: 0;
        letter-spacing: -0.02em;
    }
    .lab-divider {
        height: 1px;
        background: var(--lab-border-soft);
        margin: 0.25rem 0 0.35rem 0;
    }

    /* Table header and rows */
    .lab-column-header {
        color: #aeb8c5;
        font-size: 0.77rem;
        font-weight: 620;
        letter-spacing: 0.01em;
        padding: 0.1rem 0.18rem 0.15rem 0.18rem;
        white-space: nowrap;
    }

    div[class*="st-key-mouse_row_"] {
        background: linear-gradient(180deg, rgba(27, 36, 48, 0.96), rgba(21, 29, 39, 0.96));
        border: 1px solid var(--lab-border) !important;
        border-radius: 0.48rem !important;
        padding: 0.55rem 0.58rem !important;
        margin-bottom: 0.05rem;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.018);
    }

    .lab-cell {
        min-height: 4.05rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
        overflow: hidden;
    }
    .lab-mouse-wrap {
        display: flex;
        align-items: center;
        gap: 0.72rem;
        min-height: 4.05rem;
    }
    .lab-dot {
        width: 0.72rem;
        height: 0.72rem;
        border-radius: 50%;
        flex: 0 0 auto;
        box-shadow: 0 0 0 1px rgba(255,255,255,0.06);
    }
    .lab-dot.green { background: var(--lab-green); }
    .lab-dot.orange { background: var(--lab-orange); }
    .lab-dot.red { background: var(--lab-red); }
    .lab-dot.gray { background: var(--lab-gray); }

    .lab-mouse-name {
        color: var(--lab-text);
        font-weight: 760;
        font-size: 1.02rem;
        white-space: nowrap;
    }

    .lab-primary-text {
        font-size: 0.86rem;
        font-weight: 690;
        color: var(--lab-text);
        line-height: 1.18;
        white-space: nowrap;
    }
    .lab-primary-text.green { color: var(--lab-green); }
    .lab-primary-text.orange { color: var(--lab-orange); }
    .lab-primary-text.red { color: var(--lab-red); }
    .lab-primary-text.gray { color: #88929e; }

    .lab-secondary-text {
        margin-top: 0.25rem;
        color: var(--lab-muted);
        font-size: 0.75rem;
        line-height: 1.15;
        white-space: nowrap;
    }
    .lab-secondary-text.green { color: var(--lab-green); }
    .lab-secondary-text.orange { color: var(--lab-orange); }
    .lab-secondary-text.red { color: var(--lab-red); }

    .lab-total {
        display: flex;
        gap: 0.42rem;
        align-items: center;
        color: #bac3cf;
        font-size: 0.85rem;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .lab-clock {
        opacity: 0.9;
        font-size: 0.9rem;
    }

    /* Four-step workflow */
    .lab-stepper {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr 1fr 1fr 1fr;
        align-items: start;
        position: relative;
        padding-top: 0.05rem;
    }
    .lab-stepper::before {
        content: "";
        position: absolute;
        left: 9%;
        right: 9%;
        top: 0.89rem;
        height: 2px;
        background: #38424e;
        z-index: 0;
    }
    .lab-step {
        min-width: 0;
        text-align: center;
        position: relative;
        z-index: 1;
    }
    .lab-step-circle {
        width: 1.58rem;
        height: 1.58rem;
        margin: 0 auto;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: #222b35;
        border: 1.5px solid #46515d;
        color: #b6c0cc;
        font-size: 0.76rem;
        font-weight: 720;
    }
    .lab-step.complete .lab-step-circle {
        background: var(--lab-green);
        border-color: var(--lab-green);
        color: #102014;
    }
    .lab-step.active .lab-step-circle {
        background: #17251b;
        border-color: var(--lab-green);
        color: #a4eba9;
        box-shadow: 0 0 0 2px rgba(101,196,109,0.08);
    }
    .lab-step.action .lab-step-circle {
        background: #2a1e10;
        border-color: var(--lab-orange);
        color: var(--lab-orange);
    }
    .lab-step.overdue .lab-step-circle {
        background: #2d151b;
        border-color: var(--lab-red);
        color: #ff8392;
    }
    .lab-step-label {
        margin-top: 0.28rem;
        font-size: 0.68rem;
        line-height: 1.12;
        color: #b9c2cd;
        white-space: nowrap;
    }

    /* Compact buttons and popovers inside rows. */
    div[class*="st-key-mouse_row_"] button {
        min-height: 2.15rem !important;
        height: 2.15rem !important;
        padding: 0 0.65rem !important;
        border-radius: 0.4rem !important;
        font-size: 0.78rem !important;
        font-weight: 670 !important;
        white-space: nowrap !important;
    }

    div[class*="st-key-primary_action_"] button {
        border-color: rgba(255, 152, 15, 0.78) !important;
        color: #ffe4bd !important;
        background: rgba(255, 152, 15, 0.07) !important;
    }
    div[class*="st-key-primary_pause_"] button {
        border-color: rgba(148, 163, 184, 0.32) !important;
    }

    /* Native per-mouse action menu. Keep the ellipsis compact while letting
       Streamlit own the dropdown lifecycle so it reliably opens/closes. */
    div[class*="st-key-mouse_action_menu_"] button {
        min-width: 2.15rem !important;
        width: 100% !important;
        padding-left: 0.20rem !important;
        padding-right: 0.20rem !important;
        font-size: 1.05rem !important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button {
        min-height: 1.72rem !important;
        height: 1.72rem !important;
        padding: 0 0.34rem !important;
        margin-top: 0.18rem !important;
        font-size: 0.68rem !important;
        white-space: nowrap !important;
    }
    div[class*="st-key-anesthesia_redose_action_"] button {
        color: #ffe0b3 !important;
        border-color: rgba(255, 152, 15, 0.52) !important;
        background: rgba(255, 152, 15, 0.06) !important;
    }
    div[class*="st-key-anesthesia_delay_action_"] button {
        color: #d6c6ff !important;
        border-color: rgba(191, 90, 242, 0.48) !important;
        background: rgba(191, 90, 242, 0.055) !important;
    }
    /* Before Mouse Start (and while paused/ended), make the anesthesia
       secondary controls unmistakably inactive instead of retaining their
       orange/purple active styling. */
    div[class*="st-key-anesthesia_redose_action_"] button:disabled,
    div[class*="st-key-anesthesia_delay_action_"] button:disabled {
        color: rgba(185, 194, 205, 0.42) !important;
        border-color: rgba(148, 163, 184, 0.16) !important;
        background: rgba(148, 163, 184, 0.035) !important;
        box-shadow: none !important;
        opacity: 0.72 !important;
        cursor: not-allowed !important;
    }

    /* Hover-help tooltips should be discoverable, but not jump onto the screen
       immediately. Streamlit mounts the tooltip only while the pointer remains
       over a help-enabled control, so a delayed reveal gives ~1 second of dwell
       time before the explanation appears. */
    @keyframes lab-tooltip-reveal {
        0%, 99% { opacity: 0 !important; visibility: hidden !important; }
        100% { opacity: 1 !important; visibility: visible !important; }
    }
    [role="tooltip"],
    [data-baseweb="tooltip"],
    [data-baseweb="popover"]:has([role="tooltip"]),
    [data-baseweb="popover"]:has([data-baseweb="tooltip"]) {
        animation: lab-tooltip-reveal 0.01s linear 1s both !important;
    }

    /* A paused subject is deliberately de-emphasized without disabling Resume/menu controls. */
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) {
        background: linear-gradient(180deg, rgba(18, 23, 30, 0.98), rgba(14, 19, 25, 0.98)) !important;
        border-color: rgba(148, 163, 184, 0.14) !important;
        box-shadow: inset 0 0 0 9999px rgba(0,0,0,0.12) !important;
    }
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-dot,
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-primary-text,
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-secondary-text,
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-total,
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-step-circle,
    div[class*="st-key-mouse_row_"]:has([data-lab-row-paused="true"]) .lab-step-label {
        filter: grayscale(1);
        opacity: 0.52;
    }
    /* Keep the subject name in exactly the same vertical position when
       paused. The PAUSED label is layered above it rather than inserted into
       normal document flow. */
    .lab-mouse-cell {
        position: relative;
        min-height: 4.05rem;
    }
    .lab-mouse-cell .lab-mouse-wrap {
        min-height: 4.05rem;
    }
    .lab-paused-label {
        position: absolute;
        top: 0.05rem;
        left: 1.44rem;
        z-index: 2;
        display: flex;
        align-items: center;
        gap: 0.48rem;
        color: #ffffff;
        font-size: 0.86rem;
        line-height: 1.18;
        font-weight: 760;
        letter-spacing: 0;
        text-transform: none;
        margin: 0;
        white-space: nowrap;
        pointer-events: none;
    }
    .lab-paused-time {
        font-variant-numeric: tabular-nums;
        letter-spacing: 0;
        font-weight: 690;
    }

    /* Give the Actions column a little breathing room from anesthesia controls. */
    div[class*="st-key-actions_cell_"] {
        padding-left: 0.30rem;
    }

    /* Hidden native controls used only by modal/dialog workflows. */
    div[class*="st-key-dialog_helper_"] {
        display: none !important;
    }

    /* Comment acceptance is intentionally Apple-style blue rather than the
       app/theme primary red used for urgent/destructive actions. */
    div[class*="st-key-comment_accept_"] button {
        background: #0A84FF !important;
        border-color: #0A84FF !important;
        color: #ffffff !important;
        box-shadow: 0 0 0 1px rgba(10,132,255,0.20) !important;
    }
    div[class*="st-key-comment_accept_"] button:hover {
        background: #1b8cff !important;
        border-color: #1b8cff !important;
    }

    /* Rename is a non-destructive confirmation, so use the same neutral blue. */
    div[class*="st-key-rename_accept_"] button {
        background: #0A84FF !important;
        border-color: #0A84FF !important;
        color: #ffffff !important;
        box-shadow: 0 0 0 1px rgba(10,132,255,0.20) !important;
    }
    div[class*="st-key-rename_accept_"] button:hover {
        background: #1b8cff !important;
        border-color: #1b8cff !important;
    }

    /* Fallback for older Streamlit builds: if a native popover somehow remains
       open while a modal is present, hide every known popover portal shape.
       Current builds close the originating mouse popover through Session State. */
    body:has([data-testid="stDialog"]) [data-baseweb="popover"],
    body:has([data-testid="stDialog"]) [data-testid="stPopoverBody"],
    body:has([data-testid="stDialog"]) [data-testid="stPopover"],
    body:has([role="dialog"]) [data-baseweb="popover"],
    body:has([role="dialog"]) [data-testid="stPopoverBody"],
    body:has([role="dialog"]) [data-testid="stPopover"] {
        visibility: hidden !important;
        pointer-events: none !important;
    }

    /* Completed/ended subjects are grouped at the bottom and visually subdued. */
    .lab-completed-section-title {
        margin: 0.55rem 0 0.24rem 0.1rem;
        color: #c7d0db;
        font-size: 0.82rem;
        font-weight: 760;
        letter-spacing: 0.015em;
        text-transform: uppercase;
    }
    div[class*="st-key-mouse_row_"]:has([data-lab-row-finished="true"]) {
        background: linear-gradient(180deg, rgba(18, 25, 33, 0.93), rgba(14, 20, 27, 0.93)) !important;
        border-color: rgba(148, 163, 184, 0.14) !important;
    }

    /* Lightweight timesheet table avoids the heavier interactive dataframe widget. */
    .lab-timesheet-wrap {
        max-height: 58vh;
        overflow: auto;
        border: 1px solid var(--lab-border);
        border-radius: 0.45rem;
    }
    .lab-timesheet {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.80rem;
    }
    .lab-timesheet th {
        position: sticky;
        top: 0;
        z-index: 1;
        text-align: left;
        background: #1a2330;
        color: #d8dee7;
        padding: 0.52rem 0.62rem;
        border-bottom: 1px solid var(--lab-border);
    }
    .lab-timesheet td {
        padding: 0.48rem 0.62rem;
        border-bottom: 1px solid var(--lab-border-soft);
        color: #d0d7e0;
        vertical-align: top;
    }
    .lab-timesheet tr:last-child td { border-bottom: 0; }

    /* Footer legend */
    .lab-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        padding: 0.35rem 0.2rem 0 0.2rem;
        color: #b3bcc8;
        font-size: 0.73rem;
        flex-wrap: wrap;
    }
    .lab-legend-left, .lab-legend-center, .lab-legend-right {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        flex-wrap: wrap;
    }
    .lab-legend-item {
        display: inline-flex;
        align-items: center;
        gap: 0.36rem;
        white-space: nowrap;
    }
    .lab-legend-dot {
        width: 0.68rem;
        height: 0.68rem;
        border-radius: 50%;
        display: inline-block;
    }

    /* Popover panels must be opaque. Without this, the Settings panel can
       visually sit on top of the live rows with the timer text showing through. */
    [data-testid="stPopoverBody"] {
        background: #0d141d !important;
        border: 1px solid rgba(148, 163, 184, 0.28) !important;
        border-radius: 0.62rem !important;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.46) !important;
        opacity: 1 !important;
    }
    [data-testid="stPopoverBody"] [data-testid="stNumberInput"] input {
        font-size: 0.82rem;
    }

    /* Normal text-entry fields are never destructive. Streamlit's theme can
       otherwise leak its red primary color into the focus ring. Apply one
       neutral treatment to EVERY text input and text area in the app --
       experiment name, comments, subject rename, and any future text boxes. */
    [data-testid="stTextInput"],
    [data-testid="stTextArea"] {
        --primary-color: rgba(148, 163, 184, 0.34) !important;
        --secondary-background-color: #101823 !important;
    }

    [data-testid="stTextInput"] [data-baseweb="input"],
    [data-testid="stTextInput"] [data-baseweb="base-input"],
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] [data-baseweb="textarea"],
    [data-testid="stTextArea"] [data-baseweb="base-input"],
    [data-testid="stTextArea"] textarea {
        background: #101823 !important;
        border-color: rgba(148, 163, 184, 0.34) !important;
        outline: none !important;
        outline-color: transparent !important;
        box-shadow: none !important;
    }

    /* BaseWeb may draw its focus ring on several nested wrappers or pseudo
       elements instead of the input itself. Keep every one of those layers
       neutral while the field is active -- never red. */
    [data-testid="stTextInput"]:focus-within,
    [data-testid="stTextInput"]:focus-within [data-baseweb="input"],
    [data-testid="stTextInput"]:focus-within [data-baseweb="base-input"],
    [data-testid="stTextInput"]:focus-within input,
    [data-testid="stTextArea"]:focus-within,
    [data-testid="stTextArea"]:focus-within [data-baseweb="textarea"],
    [data-testid="stTextArea"]:focus-within [data-baseweb="base-input"],
    [data-testid="stTextArea"]:focus-within textarea {
        border-color: rgba(148, 163, 184, 0.34) !important;
        outline: none !important;
        outline-color: transparent !important;
        box-shadow: none !important;
    }
    [data-testid="stTextInput"]:focus-within *::before,
    [data-testid="stTextInput"]:focus-within *::after,
    [data-testid="stTextArea"]:focus-within *::before,
    [data-testid="stTextArea"]:focus-within *::after {
        border-color: rgba(148, 163, 184, 0.34) !important;
        outline: none !important;
        box-shadow: none !important;
    }

    @media (max-width: 1150px) {
        .stMainBlockContainer { min-width: 1120px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# TIME / DISPLAY HELPERS
# ============================================================


def duration_to_seconds(duration_units):
    return float(duration_units) * UNIT_SECONDS


def warning_seconds():
    return duration_to_seconds(WARNING_UNITS)


def rounded_seconds(seconds):
    return max(0, int(round(seconds)))


def format_timer(seconds):
    """Format a duration as mm:ss, or h:mm:ss if at least one hour."""
    total = rounded_seconds(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_total_elapsed(seconds):
    total = rounded_seconds(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def fixed_duration_label(value):
    return f"{value}{UNIT_SHORT}"


def effective_now(i, wall_now):
    if is_ended(i):
        return st.session_state[f"end_time_{i}"]
    if is_paused(i):
        return st.session_state[f"pause_started_{i}"]
    return wall_now


def elapsed_from(start_time, now):
    if start_time is None:
        return 0.0
    return max(0.0, now - start_time)


def remaining_from_start(start_time, duration_units, now):
    if start_time is None:
        return None
    return start_time + duration_to_seconds(duration_units) - now


# ============================================================
# STATE MANAGEMENT
# ============================================================


def mouse_defaults(i):
    return {
        f"experiment_start_{i}": None,
        f"anesthesia_start_{i}": None,
        # When Delay redose is pressed, this becomes an absolute Unix-epoch
        # deadline calculated from the moment the button was pressed.
        f"anesthesia_due_override_{i}": None,
        f"board_start_{i}": None,
        f"shock_start_{i}": None,
        f"shock_wallclock_{i}": None,
        f"resus_start_{i}": None,
        f"paused_{i}": False,
        f"pause_started_{i}": None,
        f"ended_{i}": False,
        f"end_time_{i}": None,
        f"anesthesia_duration_{i}": DEFAULT_ANESTHESIA,
        f"anesthesia_delay_duration_{i}": DEFAULT_ANESTHESIA_DELAY,
        f"event_log_{i}": [],
        f"subject_name_{i}": f"Mouse {i}",
    }


def initialize_mouse_state(i):
    for key, value in mouse_defaults(i).items():
        if key not in st.session_state:
            # Lists must be unique per mouse rather than shared references.
            st.session_state[key] = list(value) if isinstance(value, list) else value


# ============================================================
# DURABLE EXPERIMENT STORAGE
# ============================================================


def _configured_database_url():
    """Return the one Neon PostgreSQL URL used by both local and cloud runs."""
    # Local development: .streamlit/secrets.toml (included in the local bundle,
    # but intentionally git-ignored). Streamlit Cloud: the same key/value in
    # the app's Secrets settings. Environment variables are also accepted for
    # CI or shell launches, but there is NO SQLite/local-database fallback.
    env_value = os.environ.get("SHOCK_TIMER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if env_value:
        return str(env_value).strip()

    try:
        value = st.secrets.get("SHOCK_TIMER_DATABASE_URL") or st.secrets.get("DATABASE_URL")
        return str(value).strip() if value else None
    except Exception:
        return None


DATABASE_URL = _configured_database_url()
if not DATABASE_URL:
    st.error(
        "Neon database is not configured. Add SHOCK_TIMER_DATABASE_URL to "
        ".streamlit/secrets.toml locally and to Streamlit Cloud Secrets for deployment."
    )
    st.stop()

if not DATABASE_URL.startswith(("postgres://", "postgresql://")):
    st.error("SHOCK_TIMER_DATABASE_URL must be a PostgreSQL/Neon connection URL.")
    st.stop()


def _adapt_sql(sql):
    # Application SQL is written with '?' placeholders for readability. Psycopg
    # uses '%s'. Neon is the only database backend in v24.
    return sql.replace("?", "%s")


def _import_psycopg():
    try:
        import psycopg
        return psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Neon persistence requires psycopg. Add psycopg[binary]>=3.2,<4 to requirements.txt."
        ) from exc


@st.cache_resource(show_spinner=False)
def _db_resource():
    """Keep one hot Neon connection per Streamlit process.

    Opening a new TLS/Postgres connection for every button press added roughly a
    second of avoidable latency. Reusing a live connection keeps writes durable
    before the UI advances while making normal action clicks feel immediate.
    The lock makes the cached connection safe across Streamlit sessions/threads.
    """
    return {"conn": None, "lock": threading.RLock()}


def _new_db_connection():
    psycopg = _import_psycopg()
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )


def _invalidate_db_connection(resource):
    conn = resource.get("conn")
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    resource["conn"] = None


def _db_run(operation):
    """Run a DB operation on the cached connection and reconnect once if stale."""
    psycopg = _import_psycopg()
    resource = _db_resource()

    with resource["lock"]:
        for attempt in range(2):
            conn = resource.get("conn")
            if conn is None or getattr(conn, "closed", True):
                conn = _new_db_connection()
                resource["conn"] = conn

            try:
                result = operation(conn)
                return result
            except (psycopg.OperationalError, psycopg.InterfaceError):
                # Neon can suspend compute or an idle socket can die. Reconnect
                # once transparently; active experiments normally keep this
                # connection hot, so ordinary clicks avoid a TLS handshake.
                try:
                    conn.rollback()
                except Exception:
                    pass
                _invalidate_db_connection(resource)
                if attempt == 1:
                    raise
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise


def _db_execute(sql, params=()):
    def operation(conn):
        with conn.cursor() as cur:
            cur.execute(_adapt_sql(sql), params)
        conn.commit()
    return _db_run(operation)


def _db_execute_many(statements):
    """Execute (sql, params) statements in one transaction."""
    def operation(conn):
        with conn.cursor() as cur:
            for sql, params in statements:
                cur.execute(_adapt_sql(sql), params)
        conn.commit()
    return _db_run(operation)


def _db_query(sql, params=()):
    def operation(conn):
        with conn.cursor() as cur:
            cur.execute(_adapt_sql(sql), params)
            columns = [item[0] for item in cur.description]
            rows = cur.fetchall()
        # End the read transaction promptly while retaining the TCP/TLS socket.
        conn.commit()
        return [dict(zip(columns, row)) for row in rows]
    return _db_run(operation)


@st.cache_resource(show_spinner=False)
def initialize_database():
    statements = [
        (
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mouse_count INTEGER NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL
            )
            """,
            (),
        ),
        (
            """
            CREATE TABLE IF NOT EXISTS subjects (
                experiment_id TEXT NOT NULL,
                mouse_index INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (experiment_id, mouse_index)
            )
            """,
            (),
        ),
        (
            "ALTER TABLE experiments ADD COLUMN IF NOT EXISTS completed_at DOUBLE PRECISION",
            (),
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_experiments_updated_at ON experiments(updated_at)",
            (),
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_experiments_completed_at ON experiments(completed_at)",
            (),
        ),
        (
            """
            UPDATE experiments AS e
            SET completed_at = COALESCE(e.completed_at, e.updated_at)
            WHERE e.completed_at IS NULL
              AND (SELECT COUNT(*) FROM subjects s WHERE s.experiment_id = e.id) >= e.mouse_count
              AND NOT EXISTS (
                  SELECT 1
                  FROM subjects s
                  WHERE s.experiment_id = e.id
                    AND COALESCE(
                        (s.state_json::jsonb ->> ('ended_' || s.mouse_index::text))::boolean,
                        FALSE
                    ) = FALSE
              )
            """,
            (),
        ),
    ]
    _db_execute_many(statements)
    return True


initialize_database()


def _subject_state_payload(i):
    payload = {}
    for key, default in mouse_defaults(i).items():
        value = st.session_state.get(key, default)
        payload[key] = list(value) if isinstance(value, list) else value
    return payload


def _default_subject_payload(i):
    payload = mouse_defaults(i)
    return {key: list(value) if isinstance(value, list) else value for key, value in payload.items()}


def _load_subject_payload_into_session(i, payload):
    defaults = _default_subject_payload(i)
    if isinstance(payload, dict):
        defaults.update({key: value for key, value in payload.items() if key in defaults})
    for key, value in defaults.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


def create_experiment_record(name, count):
    name = (name or "").strip() or f"Experiment {wall_datetime().strftime('%Y-%m-%d %H:%M')}"
    count = max(1, int(count))
    experiment_id = uuid.uuid4().hex
    now = time.time()

    statements = [
        (
            "INSERT INTO experiments (id, name, mouse_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (experiment_id, name, count, now, now),
        )
    ]
    for i in range(1, count + 1):
        statements.append(
            (
                "INSERT INTO subjects (experiment_id, mouse_index, state_json, updated_at) VALUES (?, ?, ?, ?)",
                (experiment_id, i, json.dumps(_default_subject_payload(i), separators=(",", ":")), now),
            )
        )
    _db_execute_many(statements)
    return experiment_id


def list_experiment_records():
    return _db_query(
        "SELECT id, name, mouse_count, created_at, updated_at, completed_at FROM experiments "
        "ORDER BY CASE WHEN completed_at IS NULL THEN 0 ELSE 1 END, updated_at DESC, created_at DESC"
    )


def get_experiment_record(experiment_id):
    rows = _db_query(
        "SELECT id, name, mouse_count, created_at, updated_at, completed_at FROM experiments WHERE id = ?",
        (experiment_id,),
    )
    return rows[0] if rows else None


def get_subject_records(experiment_id):
    return _db_query(
        "SELECT mouse_index, state_json, updated_at FROM subjects WHERE experiment_id = ? ORDER BY mouse_index",
        (experiment_id,),
    )


def rename_experiment_record(experiment_id, new_name):
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    now = time.time()
    _db_execute(
        "UPDATE experiments SET name = ?, updated_at = ? WHERE id = ?",
        (new_name, now, experiment_id),
    )
    return True


def delete_experiment_record(experiment_id):
    """Delete an experiment and its subjects in a single Neon command."""
    _db_execute(
        """
        WITH deleted_subjects AS (
            DELETE FROM subjects
            WHERE experiment_id = ?
            RETURNING mouse_index
        )
        DELETE FROM experiments
        WHERE id = ?
        """,
        (experiment_id, experiment_id),
    )
    return True


def _append_event_to_payload(payload, i, event_name, details, when_dt):
    key = f"event_log_{i}"
    log = list(payload.get(key, []))
    log.append(
        {
            "Event": event_name,
            "Absolute time": when_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "Details": details,
        }
    )
    payload[key] = log


def end_experiment_record(experiment_id, details="Ended from experiments page"):
    """Force every subject ended and mark complete with one Neon round trip.

    The subject JSON is updated directly in PostgreSQL, including the end event,
    so the management page does not need to download/parse/re-upload every mouse.
    """
    now = time.time()
    absolute_time = datetime.fromtimestamp(now, ZoneInfo(APP_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

    _db_execute(
        """
        WITH updated_subjects AS (
            UPDATE subjects
            SET state_json = (
                (
                    state_json::jsonb
                    || jsonb_build_object(
                        'ended_' || mouse_index::text, TRUE,
                        'end_time_' || mouse_index::text, ?,
                        'paused_' || mouse_index::text, FALSE,
                        'pause_started_' || mouse_index::text, NULL
                    )
                )
                || jsonb_build_object(
                    'event_log_' || mouse_index::text,
                    COALESCE(
                        state_json::jsonb -> ('event_log_' || mouse_index::text),
                        '[]'::jsonb
                    )
                    || jsonb_build_array(
                        jsonb_build_object(
                            'Event', 'Experiment ended',
                            'Absolute time', ?,
                            'Details', ?
                        )
                    )
                )
            )::text,
            updated_at = ?
            WHERE experiment_id = ?
              AND COALESCE(
                    (state_json::jsonb ->> ('ended_' || mouse_index::text))::boolean,
                    FALSE
                  ) = FALSE
            RETURNING mouse_index
        )
        UPDATE experiments
        SET completed_at = COALESCE(completed_at, ?), updated_at = ?
        WHERE id = ?
        """,
        (now, absolute_time, details, now, experiment_id, now, now, experiment_id),
    )
    return True


def reconcile_experiment_completion_flags():
    """Legacy/manual backfill without downloading subject JSON into Python."""
    now = time.time()
    _db_execute(
        """
        UPDATE experiments AS e
        SET completed_at = COALESCE(e.completed_at, ?), updated_at = GREATEST(e.updated_at, ?)
        WHERE e.completed_at IS NULL
          AND (SELECT COUNT(*) FROM subjects s WHERE s.experiment_id = e.id) >= e.mouse_count
          AND NOT EXISTS (
              SELECT 1
              FROM subjects s
              WHERE s.experiment_id = e.id
                AND COALESCE(
                    (s.state_json::jsonb ->> ('ended_' || s.mouse_index::text))::boolean,
                    FALSE
                ) = FALSE
          )
        """,
        (now, now),
    )


def persist_subject(i):
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return True

    now = time.time()
    payload = json.dumps(_subject_state_payload(i), separators=(",", ":"))
    try:
        _db_execute_many(
            [
                (
                    """
                    INSERT INTO subjects (experiment_id, mouse_index, state_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (experiment_id, mouse_index)
                    DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
                    """,
                    (experiment_id, int(i), payload, now),
                ),
                (
                    """
                    UPDATE experiments
                    SET mouse_count = ?,
                        updated_at = ?,
                        completed_at = CASE
                            WHEN ? THEN COALESCE(completed_at, ?)
                            ELSE completed_at
                        END
                    WHERE id = ?
                    """,
                    (
                        mouse_count(),
                        now,
                        all(bool(st.session_state.get(f"ended_{idx}", False)) for idx in range(1, mouse_count() + 1)),
                        now,
                        experiment_id,
                    ),
                ),
            ]
        )
    except Exception as exc:
        pending = set(st.session_state.get("_unsaved_subjects", []))
        pending.add(int(i))
        st.session_state["_unsaved_subjects"] = sorted(pending)
        st.session_state["_storage_error"] = str(exc)
        return False

    st.session_state[f"_db_subject_updated_{i}"] = now
    st.session_state["_db_experiment_updated"] = now
    pending = set(st.session_state.get("_unsaved_subjects", []))
    pending.discard(int(i))
    st.session_state["_unsaved_subjects"] = sorted(pending)
    if not pending:
        st.session_state.pop("_storage_error", None)
    return True


def retry_unsaved_subjects():
    pending = list(st.session_state.get("_unsaved_subjects", []))
    for i in pending:
        persist_subject(int(i))

    # If End all was the action that failed, complete its promised automatic
    # export once the delayed Neon save is finally confirmed.
    if pending and not st.session_state.get("_unsaved_subjects"):
        if mouse_count() > 0 and all(bool(st.session_state.get(f"ended_{idx}", False)) for idx in range(1, mouse_count() + 1)):
            queue_timesheet_auto_download()


def load_experiment_into_session(experiment_id):
    experiment = get_experiment_record(experiment_id)
    if not experiment:
        return False

    subject_rows = {int(row["mouse_index"]): row for row in get_subject_records(experiment_id)}
    st.session_state.clear()
    st.session_state["_state_version"] = STATE_VERSION
    st.session_state["_active_experiment_id"] = str(experiment["id"])
    st.session_state["_experiment_name"] = str(experiment["name"])
    st.session_state["_mouse_count"] = int(experiment["mouse_count"])
    st.session_state["_db_experiment_updated"] = float(experiment["updated_at"])
    st.session_state["_sticky_alerts"] = {}
    st.session_state["_pending_dialog"] = None
    st.session_state["_needs_full_rerun"] = False
    st.session_state["_unsaved_subjects"] = []

    for i in range(1, int(experiment["mouse_count"]) + 1):
        row = subject_rows.get(i)
        payload = {}
        if row:
            try:
                payload = json.loads(row["state_json"])
            except Exception:
                payload = {}
        _load_subject_payload_into_session(i, payload)
        st.session_state[f"_db_subject_updated_{i}"] = float(row["updated_at"]) if row else 0.0
    return True


def sync_active_experiment_from_database():
    """Manually pull newer per-subject records from Neon when explicitly requested."""
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return True

    experiment = get_experiment_record(experiment_id)
    if not experiment:
        st.session_state["_active_experiment_missing"] = True
        return False

    remote_count = int(experiment["mouse_count"])
    local_count = int(st.session_state.get("_mouse_count", 0))
    if remote_count > local_count:
        st.session_state["_mouse_count"] = remote_count
        for i in range(local_count + 1, remote_count + 1):
            initialize_mouse_state(i)

    st.session_state["_experiment_name"] = str(experiment["name"])
    st.session_state["_db_experiment_updated"] = float(experiment["updated_at"])

    for row in get_subject_records(experiment_id):
        i = int(row["mouse_index"])
        remote_updated = float(row["updated_at"])
        local_updated = float(st.session_state.get(f"_db_subject_updated_{i}", 0.0))
        if i in set(st.session_state.get("_unsaved_subjects", [])):
            continue
        if remote_updated > local_updated + 1e-6:
            try:
                payload = json.loads(row["state_json"])
            except Exception:
                continue
            _load_subject_payload_into_session(i, payload)
            st.session_state[f"_db_subject_updated_{i}"] = remote_updated

    if not st.session_state.get("_unsaved_subjects"):
        st.session_state.pop("_storage_error", None)
    return True


def initialize_state():
    # Persistent experiment state is loaded explicitly from the database. Do not
    # clear it merely because code/state versions changed; defaults are merged
    # into stored subject payloads instead.
    st.session_state["_state_version"] = STATE_VERSION
    st.session_state.setdefault("_mouse_count", INITIAL_MOUSE_COUNT)
    st.session_state.setdefault("_sticky_alerts", {})
    st.session_state.setdefault("_pending_dialog", None)
    st.session_state.setdefault("_needs_full_rerun", False)
    st.session_state.setdefault("_unsaved_subjects", [])

    for i in range(1, st.session_state["_mouse_count"] + 1):
        initialize_mouse_state(i)

    # v22 targeted repair retained for old idle records that may have inherited
    # number_input's minimum instead of the code defaults.
    if not st.session_state.get("_v22_settings_default_repair_done", False):
        repaired = False
        for i in range(1, st.session_state["_mouse_count"] + 1):
            if st.session_state.get(f"experiment_start_{i}") is None:
                if st.session_state.get(f"anesthesia_duration_{i}") == 1:
                    st.session_state[f"anesthesia_duration_{i}"] = DEFAULT_ANESTHESIA
                    repaired = True
                if st.session_state.get(f"anesthesia_delay_duration_{i}") == 1:
                    st.session_state[f"anesthesia_delay_duration_{i}"] = DEFAULT_ANESTHESIA_DELAY
                    repaired = True
        st.session_state["_v22_settings_default_repair_done"] = True
        if repaired:
            for i in range(1, st.session_state["_mouse_count"] + 1):
                persist_subject(i)


def mouse_count():
    return int(st.session_state.get("_mouse_count", INITIAL_MOUSE_COUNT))


def subject_name(i):
    """Return the display name for a subject, preserving Mouse N as the default."""
    value = str(st.session_state.get(f"subject_name_{i}", f"Mouse {i}")).strip()
    return value or f"Mouse {i}"


def add_mouse_subject():
    new_mouse = mouse_count() + 1
    st.session_state["_mouse_count"] = new_mouse
    initialize_mouse_state(new_mouse)
    # The Add subject control lives inside the live timer fragment. Escalate
    # once so static header controls (Settings/export) immediately include the
    # newly added subject too.
    persist_subject(new_mouse)
    st.session_state["_needs_full_rerun"] = True


def wall_datetime():
    return datetime.now(ZoneInfo(APP_TIMEZONE))



def save_comment(i, comment):
    comment = (comment or "").strip()
    if not comment:
        return False
    log_event(i, "Comment", comment)
    return True


def rename_subject(i, new_name):
    """Rename a subject without adding the rename itself to the timesheet."""
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    st.session_state[f"subject_name_{i}"] = new_name
    persist_subject(i)
    return True


def log_event(i, event_name, details="", when=None):
    """Append an absolute timestamped event to a mouse's timesheet."""
    when = when or wall_datetime()
    key = f"event_log_{i}"

    # Reassign rather than only mutating the existing list in place. This makes
    # writes originating inside an st.dialog fragment unambiguous to Session
    # State and guarantees that comments are visible the next time the
    # timesheet is opened.
    updated_log = list(st.session_state.get(key, []))
    updated_log.append(
        {
            "Event": event_name,
            "Absolute time": when.strftime("%Y-%m-%d %H:%M:%S"),
            "Details": details,
        }
    )
    st.session_state[key] = updated_log
    # Persist before returning so a displayed state transition is already durable.
    # Do NOT force a full-app rerun here: the originating timer fragment reruns
    # immediately after its callback and can display the new timer without the
    # extra full-page render that previously added perceptible click latency.
    persist_subject(i)
    return when


def build_all_timesheets_text():
    """Return one plain-text export containing every subject timesheet."""
    lines = [
        "Shock Timer - Aggregated Timesheets",
        f"Experiment: {st.session_state.get('_experiment_name', 'Experiment')}",
        f"Experiment ID: {st.session_state.get('_active_experiment_id', '')}",
        f"Timezone: {APP_TIMEZONE}",
        f"Exported: {wall_datetime().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for i in range(1, mouse_count() + 1):
        name = subject_name(i)
        lines.append("=" * 72)
        lines.append(f"{name} (Mouse {i})")
        lines.append("=" * 72)
        log = st.session_state.get(f"event_log_{i}", [])

        if not log:
            lines.append("No events recorded.")
        else:
            for entry in log:
                event = str(entry.get("Event", ""))
                absolute_time = str(entry.get("Absolute time", ""))
                details = str(entry.get("Details", "")).strip()
                line = f"{absolute_time} | {event}"
                if details:
                    line += f" | {details}"
                lines.append(line)

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def alert_key(i, event_name):
    return f"{i}:{event_name}"


def clear_alert(i, event_name):
    st.session_state.get("_sticky_alerts", {}).pop(alert_key(i, event_name), None)


def clear_mouse_alerts(i):
    alerts = st.session_state.get("_sticky_alerts", {})
    prefix = f"{i}:"
    for key in list(alerts):
        if key.startswith(prefix):
            alerts.pop(key, None)


def is_paused(i):
    return st.session_state[f"paused_{i}"]


def is_ended(i):
    return st.session_state[f"ended_{i}"]


def mouse_is_running(i):
    return not is_paused(i) and not is_ended(i)


def ensure_experiment_started(i, timestamp):
    key = f"experiment_start_{i}"
    if st.session_state[key] is None:
        st.session_state[key] = timestamp


def anesthesia_due_time(i):
    override = st.session_state[f"anesthesia_due_override_{i}"]
    if override is not None:
        return override

    start = st.session_state[f"anesthesia_start_{i}"]
    if start is None:
        return None
    return start + duration_to_seconds(st.session_state[f"anesthesia_duration_{i}"])


def anesthesia_remaining(i, now):
    due = anesthesia_due_time(i)
    return None if due is None else due - now


def start_or_redose_anesthesia(i):
    if not mouse_is_running(i):
        return

    was_started = st.session_state[f"anesthesia_start_{i}"] is not None
    timestamp = time.time()
    ensure_experiment_started(i, timestamp)
    st.session_state[f"anesthesia_start_{i}"] = timestamp
    st.session_state[f"anesthesia_due_override_{i}"] = None

    log_event(i, "Anesthesia redose" if was_started else "Anesthesia started")
    clear_alert(i, "Anesthesia redose")


def delay_anesthesia_reminder(i):
    """Set the next redose reminder to DELAY units from the button press time."""
    if not mouse_is_running(i):
        return
    if st.session_state[f"anesthesia_start_{i}"] is None:
        return

    now = time.time()
    delay_seconds = duration_to_seconds(st.session_state[f"anesthesia_delay_duration_{i}"])
    st.session_state[f"anesthesia_due_override_{i}"] = now + delay_seconds

    wall_now = wall_datetime()
    wall_due = wall_now + timedelta(seconds=delay_seconds)
    log_event(
        i,
        "Redose delayed",
        f"Next redose due {wall_due.strftime('%Y-%m-%d %H:%M:%S')}",
        when=wall_now,
    )
    clear_alert(i, "Anesthesia redose")


def start_board(i):
    if not mouse_is_running(i):
        return
    if st.session_state[f"anesthesia_start_{i}"] is None:
        return

    timestamp = time.time()
    ensure_experiment_started(i, timestamp)
    if st.session_state[f"board_start_{i}"] is None:
        st.session_state[f"board_start_{i}"] = timestamp
        log_event(i, "Board acclimation started")


def board_is_complete(i, now):
    start = st.session_state[f"board_start_{i}"]
    if start is None:
        return False
    return remaining_from_start(start, FIXED_BOARD_DURATION, now) <= 0


def shock_is_complete(i, now):
    start = st.session_state[f"shock_start_{i}"]
    if start is None:
        return False
    return remaining_from_start(start, FIXED_SHOCK_DURATION, now) <= 0


def resus_is_complete(i, now):
    start = st.session_state[f"resus_start_{i}"]
    if start is None:
        return False
    return remaining_from_start(start, FIXED_RESUSCITATION_DURATION, now) <= 0


def start_shock(i):
    if not mouse_is_running(i):
        return

    now = time.time()
    if not board_is_complete(i, now):
        return

    ensure_experiment_started(i, now)
    if st.session_state[f"shock_start_{i}"] is None:
        wall_now = wall_datetime()
        st.session_state[f"shock_start_{i}"] = now
        st.session_state[f"shock_wallclock_{i}"] = wall_now.strftime("%H:%M:%S")
        log_event(i, "Shock started", when=wall_now)
        clear_alert(i, "Shock")


def start_resuscitation(i):
    if not mouse_is_running(i):
        return

    now = time.time()
    if not shock_is_complete(i, now):
        return

    ensure_experiment_started(i, now)
    if st.session_state[f"resus_start_{i}"] is None:
        st.session_state[f"resus_start_{i}"] = now
        log_event(i, "Resuscitation started")
        clear_alert(i, "Resuscitation")


def toggle_pause(i):
    if is_ended(i) or st.session_state[f"experiment_start_{i}"] is None:
        return

    if not is_paused(i):
        st.session_state[f"paused_{i}"] = True
        st.session_state[f"pause_started_{i}"] = time.time()
        log_event(i, "Paused")
        return

    resume_time = time.time()
    pause_started = st.session_state[f"pause_started_{i}"]
    pause_duration = max(0.0, resume_time - pause_started)

    for key in (
        f"experiment_start_{i}",
        f"anesthesia_start_{i}",
        f"anesthesia_due_override_{i}",
        f"board_start_{i}",
        f"shock_start_{i}",
        f"resus_start_{i}",
    ):
        if st.session_state[key] is not None:
            st.session_state[key] += pause_duration

    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None
    log_event(i, "Resumed")


def end_mouse(i):
    if is_ended(i) or st.session_state[f"experiment_start_{i}"] is None:
        return

    end_time = (
        st.session_state[f"pause_started_{i}"]
        if is_paused(i)
        else time.time()
    )
    st.session_state[f"ended_{i}"] = True
    st.session_state[f"end_time_{i}"] = end_time
    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None
    clear_mouse_alerts(i)
    # Log last so the subject state + end event are committed together in the
    # same per-subject JSON write.
    log_event(i, "Experiment ended")


def end_all_subjects_current_experiment():
    """End all remaining subjects and save them with one Neon round trip."""
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return False

    now = time.time()
    when_dt = datetime.fromtimestamp(now, ZoneInfo(APP_TIMEZONE))
    changed = []

    for i in range(1, mouse_count() + 1):
        if is_ended(i):
            continue
        st.session_state[f"ended_{i}"] = True
        st.session_state[f"end_time_{i}"] = now
        st.session_state[f"paused_{i}"] = False
        st.session_state[f"pause_started_{i}"] = None
        clear_mouse_alerts(i)
        key = f"event_log_{i}"
        updated_log = list(st.session_state.get(key, []))
        updated_log.append(
            {
                "Event": "Experiment ended",
                "Absolute time": when_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Details": "Ended with End all subjects",
            }
        )
        st.session_state[key] = updated_log
        changed.append(i)

    if not changed:
        return True

    value_groups = ", ".join(["(?, ?, ?)"] * len(changed))
    params = []
    for i in changed:
        params.extend(
            [
                i,
                json.dumps(_subject_state_payload(i), separators=(",", ":")),
                now,
            ]
        )
    params.extend([experiment_id, now, now, experiment_id])

    sql = f"""
        WITH payloads(mouse_index, state_json, updated_at) AS (
            VALUES {value_groups}
        ),
        updated_subjects AS (
            UPDATE subjects AS s
            SET state_json = p.state_json, updated_at = p.updated_at
            FROM payloads AS p
            WHERE s.experiment_id = ?
              AND s.mouse_index = p.mouse_index
            RETURNING s.mouse_index
        )
        UPDATE experiments
        SET completed_at = COALESCE(completed_at, ?), updated_at = ?
        WHERE id = ?
    """

    try:
        _db_execute(sql, tuple(params))
    except Exception as exc:
        pending = set(st.session_state.get("_unsaved_subjects", []))
        pending.update(changed)
        st.session_state["_unsaved_subjects"] = sorted(pending)
        st.session_state["_storage_error"] = str(exc)
        return False

    for i in changed:
        st.session_state[f"_db_subject_updated_{i}"] = now
    st.session_state["_db_experiment_updated"] = now
    pending = set(st.session_state.get("_unsaved_subjects", []))
    pending.difference_update(changed)
    st.session_state["_unsaved_subjects"] = sorted(pending)
    if not pending:
        st.session_state.pop("_storage_error", None)
    return True


def queue_timesheet_auto_download():
    """Queue the same aggregated timesheet export for browser auto-download."""
    st.session_state["_pending_auto_download"] = {
        "token": uuid.uuid4().hex,
        "filename": f"shock_timer_timesheets_{wall_datetime().strftime('%Y-%m-%d')}.txt",
        "content_b64": base64.b64encode(build_all_timesheets_text().encode("utf-8")).decode("ascii"),
    }


def render_pending_auto_download_marker():
    pending = st.session_state.get("_pending_auto_download")
    if not pending:
        return
    token = html.escape(str(pending.get("token", "")), quote=True)
    filename = html.escape(str(pending.get("filename", "shock_timer_timesheets.txt")), quote=True)
    content_b64 = str(pending.get("content_b64", ""))
    st.html(
        f'<div data-lab-auto-download-token="{token}" '
        f'data-lab-auto-download-filename="{filename}" '
        f'data-lab-auto-download-content="{content_b64}" '
        'style="display:none !important;"></div>'
    )


def all_subjects_ended():
    return mouse_count() > 0 and all(is_ended(i) for i in range(1, mouse_count() + 1))


def _format_experiment_timestamp(epoch_value):
    try:
        dt = datetime.fromtimestamp(float(epoch_value), ZoneInfo(APP_TIMEZONE))
        return dt.strftime("%b %d, %Y · %I:%M:%S %p")
    except Exception:
        return "Unknown"


@st.dialog("Rename experiment")
def rename_experiment_dialog(experiment_id, current_name):
    value = st.text_input(
        "Experiment name",
        value=str(current_name),
        key=f"rename_experiment_text_{experiment_id}",
    )
    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key=f"cancel_rename_experiment_{experiment_id}", use_container_width=True):
            st.rerun()
    with right:
        if st.button("Save", key=f"save_rename_experiment_{experiment_id}", use_container_width=True):
            if not value.strip():
                st.warning("Experiment name cannot be blank.")
            else:
                try:
                    rename_experiment_record(experiment_id, value)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not rename experiment: {exc}")


@st.dialog("End experiment")
def end_experiment_home_dialog(experiment_id, experiment_name):
    st.markdown(f"### End {html.escape(str(experiment_name))}?", unsafe_allow_html=True)
    st.write(
        "This will mark every remaining subject as ended and move the experiment to Completed experiments. "
        "Existing timesheets will be preserved."
    )
    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key=f"cancel_end_experiment_home_{experiment_id}", use_container_width=True):
            st.rerun()
    with right:
        if st.button("End experiment", key=f"confirm_end_experiment_home_{experiment_id}", use_container_width=True, type="primary"):
            try:
                end_experiment_record(experiment_id)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not end experiment: {exc}")


@st.dialog("Delete experiment")
def delete_experiment_dialog(experiment_id, experiment_name):
    st.markdown(f"### Delete {html.escape(str(experiment_name))}?", unsafe_allow_html=True)
    st.write("This permanently deletes the experiment and all of its saved subject timesheets. This cannot be undone.")
    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key=f"cancel_delete_experiment_{experiment_id}", use_container_width=True):
            st.rerun()
    with right:
        if st.button("Delete permanently", key=f"confirm_delete_experiment_{experiment_id}", use_container_width=True, type="primary"):
            try:
                delete_experiment_record(experiment_id)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete experiment: {exc}")


def _render_experiment_card(experiment, completed=False):
    exp_id = str(experiment["id"])
    name = str(experiment["name"])
    with st.container(border=True):
        if completed:
            row = st.columns([4.9, 1.0, 1.0, 1.0], vertical_alignment="center")
        else:
            row = st.columns([4.6, 0.95, 0.95, 0.95, 0.95], vertical_alignment="center")

        with row[0]:
            st.markdown(f"**{html.escape(name)}**", unsafe_allow_html=True)
            if completed:
                st.caption(
                    f"{int(experiment['mouse_count'])} mice · Completed {_format_experiment_timestamp(experiment['completed_at'])} · "
                    f"Last saved {_format_experiment_timestamp(experiment['updated_at'])}"
                )
            else:
                st.caption(
                    f"{int(experiment['mouse_count'])} mice · Last saved action {_format_experiment_timestamp(experiment['updated_at'])} · "
                    f"Created {_format_experiment_timestamp(experiment['created_at'])}"
                )

        with row[1]:
            if st.button(
                "Open" if completed else "Resume",
                key=f"resume_experiment_{exp_id}",
                use_container_width=True,
                type="primary" if not completed else "secondary",
            ):
                if load_experiment_into_session(exp_id):
                    st.rerun()
                st.error("That experiment could not be loaded.")

        with row[2]:
            if st.button("Rename", key=f"rename_experiment_{exp_id}", use_container_width=True):
                rename_experiment_dialog(exp_id, name)

        if completed:
            with row[3]:
                if st.button("Delete", key=f"delete_experiment_{exp_id}", use_container_width=True):
                    delete_experiment_dialog(exp_id, name)
        else:
            with row[3]:
                if st.button("End", key=f"end_experiment_{exp_id}", use_container_width=True):
                    end_experiment_home_dialog(exp_id, name)
            with row[4]:
                if st.button("Delete", key=f"delete_experiment_{exp_id}", use_container_width=True):
                    delete_experiment_dialog(exp_id, name)


def render_experiment_home():
    st.markdown('<div class="lab-header-title" style="font-size:2.05rem;margin-top:0.4rem;">Shock Timer</div>', unsafe_allow_html=True)
    st.caption("Create a new experiment or resume a saved session.")

    st.success(
        "Neon cloud persistence connected. All experiment data are automatically saved to the cloud and can be resumed from any device."
    )

    with st.container(border=True):
        st.markdown("### New experiment")
        with st.form("create_experiment_form", clear_on_submit=False):
            form_cols = st.columns([3.6, 1.15, 1.35], vertical_alignment="bottom")
            with form_cols[0]:
                experiment_name = st.text_input(
                    "Experiment name",
                    placeholder="e.g. Plasma resuscitation 08-18-2026",
                )
            with form_cols[1]:
                requested_mice = st.number_input(
                    "Number of mice",
                    min_value=1,
                    max_value=64,
                    value=INITIAL_MOUSE_COUNT,
                    step=1,
                )
            with form_cols[2]:
                submitted = st.form_submit_button("Create experiment", use_container_width=True, type="primary")

        if submitted:
            if not experiment_name.strip():
                st.error("Enter an experiment name.")
            else:
                experiment_id = create_experiment_record(experiment_name, int(requested_mice))
                load_experiment_into_session(experiment_id)
                st.rerun()

    # Completion is maintained transactionally by end actions. Legacy rows are
    # backfilled once during database initialization rather than rescanned here.
    experiments = list_experiment_records()
    active = [exp for exp in experiments if exp.get("completed_at") is None]
    completed = [exp for exp in experiments if exp.get("completed_at") is not None]

    st.markdown("### Active experiments")
    if not active:
        st.info("No active experiments.")
    else:
        for experiment in active:
            _render_experiment_card(experiment, completed=False)

    st.markdown("### Completed experiments")
    if not completed:
        st.caption("Completed experiments will appear here once every subject is ended or the experiment is ended outright.")
    else:
        for experiment in completed:
            _render_experiment_card(experiment, completed=True)


def return_to_experiment_home():
    # Every meaningful action is committed immediately. Returning home simply
    # discards this browser's in-memory copy and leaves the durable DB intact.
    st.session_state.clear()
    st.rerun()


if not st.session_state.get("_active_experiment_id"):
    render_experiment_home()
    st.stop()

initialize_state()
# IMPORTANT: do not perform Neon network I/O on ordinary one-second timer reruns.
# Experiment state is loaded from Neon when Resume/Create is used. Meaningful
# user actions are committed synchronously through a retained hot connection,
# so the state is durable before the UI advances without reconnecting on every click.


# ============================================================
# NATIVE MODALS
# ============================================================


def timesheet_table_html(log):
    rows = []
    for entry in log:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('Event', '')))}</td>"
            f"<td style=\"white-space:nowrap;\">{html.escape(str(entry.get('Absolute time', '')))}</td>"
            f"<td>{html.escape(str(entry.get('Details', '')))}</td>"
            "</tr>"
        )
    return (
        '<div class="lab-timesheet-wrap"><table class="lab-timesheet">'
        '<thead><tr><th>Event</th><th>Absolute time</th><th>Details</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


@st.dialog("Timesheet", width="large")
def timesheet_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} timesheet", unsafe_allow_html=True)
    st.caption(f"Absolute event times · {APP_TIMEZONE}")

    log = st.session_state.get(f"event_log_{i}", [])
    if log:
        st.markdown(timesheet_table_html(log), unsafe_allow_html=True)
    else:
        st.info("No events have been recorded for this subject yet.")

    if st.button("Close", key=f"close_timesheet_dialog_{i}", use_container_width=True):
        # Per Streamlit's dialog behavior, an app rerun closes a dialog when the
        # dialog function is not called again on the new script run.
        st.rerun()


def _close_dialog_on_next_dialog_rerun(flag_key):
    """Close a dialog after one of its callbacks has completed successfully."""
    if st.session_state.pop(flag_key, False):
        # This rerun is already a full-app rerun, so the static header/export
        # will be refreshed without needing the fragment bridge to rerun again.
        st.session_state["_needs_full_rerun"] = False
        st.rerun()


def _cancel_comment_dialog(i):
    st.session_state[f"_close_comment_dialog_{i}"] = True


def _accept_comment_dialog(i):
    text_key = f"comment_text_{i}"
    comment = str(st.session_state.get(text_key, "")).strip()
    if not comment:
        st.session_state[f"_comment_error_{i}"] = "Enter a comment before clicking Accept."
        return

    # Write to Session State in the button callback. The callback executes
    # before Streamlit reruns the dialog, so the event is already persisted
    # when the rerun begins and cannot be lost by the dialog refresh.
    save_comment(i, comment)
    st.session_state.pop(f"_comment_error_{i}", None)
    st.session_state[f"_close_comment_dialog_{i}"] = True


@st.dialog("Add comment")
def comment_dialog(i):
    close_flag = f"_close_comment_dialog_{i}"
    _close_dialog_on_next_dialog_rerun(close_flag)

    st.markdown(f"**{html.escape(subject_name(i))}**", unsafe_allow_html=True)
    st.caption("The comment will be timestamped automatically and added to the timesheet.")

    st.text_area(
        "Comment",
        placeholder="Enter comment…",
        height=130,
        key=f"comment_text_{i}",
    )

    error = st.session_state.pop(f"_comment_error_{i}", None)
    if error:
        st.warning(error)

    left, right = st.columns(2)
    with left:
        st.button(
            "Cancel",
            key=f"cancel_comment_dialog_{i}",
            use_container_width=True,
            on_click=_cancel_comment_dialog,
            args=(i,),
        )
    with right:
        with st.container(key=f"comment_accept_{i}"):
            st.button(
                "Accept",
                key=f"accept_comment_dialog_{i}",
                use_container_width=True,
                type="secondary",
                on_click=_accept_comment_dialog,
                args=(i,),
            )


def _cancel_rename_dialog(i):
    st.session_state[f"_close_rename_dialog_{i}"] = True


def _accept_rename_dialog(i):
    value = str(st.session_state.get(f"rename_text_{i}", "")).strip()
    if not value:
        st.session_state[f"_rename_error_{i}"] = "Subject name cannot be blank."
        return

    rename_subject(i, value)
    st.session_state.pop(f"_rename_error_{i}", None)
    st.session_state[f"_close_rename_dialog_{i}"] = True


@st.dialog("Rename subject")
def rename_subject_dialog(i):
    close_flag = f"_close_rename_dialog_{i}"
    _close_dialog_on_next_dialog_rerun(close_flag)

    st.caption(f"Default name: Mouse {i}")
    st.text_input("Subject name", key=f"rename_text_{i}")

    error = st.session_state.pop(f"_rename_error_{i}", None)
    if error:
        st.warning(error)

    left, right = st.columns(2)
    with left:
        st.button(
            "Cancel",
            key=f"cancel_rename_dialog_{i}",
            use_container_width=True,
            on_click=_cancel_rename_dialog,
            args=(i,),
        )
    with right:
        with st.container(key=f"rename_accept_{i}"):
            st.button(
                "Accept",
                key=f"accept_rename_dialog_{i}",
                use_container_width=True,
                type="secondary",
                on_click=_accept_rename_dialog,
                args=(i,),
            )


def _sync_settings_interval(i):
    """Copy the Settings-dialog widget value into persistent timer state."""
    widget_key = f"settings_anesthesia_duration_{i}"
    st.session_state[f"anesthesia_duration_{i}"] = int(
        st.session_state.get(widget_key, DEFAULT_ANESTHESIA)
    )
    persist_subject(i)


def _sync_settings_delay(i):
    """Copy the Settings-dialog delay widget into persistent timer state."""
    widget_key = f"settings_anesthesia_delay_duration_{i}"
    st.session_state[f"anesthesia_delay_duration_{i}"] = int(
        st.session_state.get(widget_key, DEFAULT_ANESTHESIA_DELAY)
    )
    persist_subject(i)


@st.dialog("Settings", width="large")
def settings_dialog():
    """Edit anesthesia reminder settings in an opaque modal dialog."""
    st.markdown("### Anesthesia reminders")
    st.caption(
        "Board acclimation, shock, and resuscitation are fixed at "
        f"{FIXED_BOARD_DURATION}, {FIXED_SHOCK_DURATION}, and "
        f"{FIXED_RESUSCITATION_DURATION} {UNIT_LABEL}, respectively."
    )

    setting_cols = st.columns(2)
    for i in range(1, mouse_count() + 1):
        with setting_cols[(i - 1) % 2]:
            with st.container(border=True):
                st.markdown(
                    f"**{html.escape(subject_name(i))}**",
                    unsafe_allow_html=True,
                )
                # Use dialog-only widget keys. If the Settings dialog is not
                # rendered, Streamlit may clean up widget-owned state; keeping
                # these separate from the timer model prevents that lifecycle
                # from replacing the code defaults with number_input's minimum (1).
                interval_widget_key = f"settings_anesthesia_duration_{i}"
                delay_widget_key = f"settings_anesthesia_delay_duration_{i}"
                if interval_widget_key not in st.session_state:
                    st.session_state[interval_widget_key] = int(
                        st.session_state.get(f"anesthesia_duration_{i}", DEFAULT_ANESTHESIA)
                    )
                if delay_widget_key not in st.session_state:
                    st.session_state[delay_widget_key] = int(
                        st.session_state.get(
                            f"anesthesia_delay_duration_{i}", DEFAULT_ANESTHESIA_DELAY
                        )
                    )

                mini = st.columns(2)
                with mini[0]:
                    st.number_input(
                        f"Interval ({UNIT_LABEL})",
                        min_value=1,
                        step=1,
                        key=interval_widget_key,
                        on_change=_sync_settings_interval,
                        args=(i,),
                    )
                with mini[1]:
                    st.number_input(
                        f"Delay ({UNIT_LABEL})",
                        min_value=1,
                        step=1,
                        key=delay_widget_key,
                        on_change=_sync_settings_delay,
                        args=(i,),
                    )

    if st.button("Close", key="close_settings_dialog", use_container_width=True):
        st.rerun()


@st.dialog("Confirm end")
def end_confirmation_dialog(i):
    name = subject_name(i)
    st.markdown(f"### End {html.escape(name)}?", unsafe_allow_html=True)
    st.write(
        "This will freeze the subject timers and clear its active reminders. "
        "The recorded timesheet will be preserved."
    )

    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key=f"cancel_end_dialog_{i}", use_container_width=True):
            st.rerun()
    with right:
        if st.button(
            "End experiment",
            key=f"confirm_end_dialog_{i}",
            use_container_width=True,
            type="primary",
        ):
            end_mouse(i)
            st.session_state["_needs_full_rerun"] = False
            st.rerun()


@st.dialog("End all subjects")
def end_all_subjects_dialog():
    remaining = [subject_name(i) for i in range(1, mouse_count() + 1) if not is_ended(i)]
    st.markdown("### End all subjects?")
    st.write(
        f"This will immediately mark {len(remaining)} remaining subject{'s' if len(remaining) != 1 else ''} as ended, "
        "clear their active reminders, and mark the experiment complete. Timesheets are preserved."
    )
    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key="cancel_end_all_subjects", use_container_width=True):
            st.rerun()
    with right:
        if st.button("End all subjects", key="confirm_end_all_subjects", use_container_width=True, type="primary"):
            if end_all_subjects_current_experiment():
                queue_timesheet_auto_download()
                st.session_state["_needs_full_rerun"] = False
                st.rerun()
            else:
                st.error("The subjects were ended locally, but Neon has not confirmed the save yet. Retry the save before closing or refreshing the page.")


def request_dialog(i, kind):
    """Queue a dialog for the next full-app rerun."""
    # The per-mouse action control is a native st.menu_button. Selecting an
    # option closes that menu automatically before the selection rerun. We only
    # need to persist which dialog should open on the ensuing full-app rerun.

    # Initialize dialog inputs BEFORE their widgets are rendered. This avoids
    # stale values and lets a normal mouse click on Accept submit the current
    # text without requiring Enter/Tab or any other keyboard action.
    if kind == "comment":
        st.session_state[f"comment_text_{i}"] = ""
        st.session_state.pop(f"_comment_error_{i}", None)
    elif kind == "rename":
        st.session_state[f"rename_text_{i}"] = subject_name(i)
        st.session_state.pop(f"_rename_error_{i}", None)

    st.session_state["_pending_dialog"] = {"kind": kind, "mouse": int(i)}


def render_pending_dialog():
    """Render a queued modal outside the originating popover's render context."""
    request = st.session_state.pop("_pending_dialog", None)
    if not request:
        return

    i = int(request.get("mouse", 0))
    kind = request.get("kind")
    if i < 1 or i > mouse_count():
        return

    if kind == "timesheet":
        timesheet_dialog(i)
    elif kind == "comment":
        comment_dialog(i)
    elif kind == "rename":
        rename_subject_dialog(i)
    elif kind == "end":
        end_confirmation_dialog(i)


# Dialogs must be opened from the full app run, not from the one-second timer
# fragment. Mouse-menu callbacks queue the request, the fragment immediately
# escalates to a full rerun, and this top-level call opens the requested modal.
render_pending_dialog()


# ============================================================
# DEADLINES / ATTENTION STATE
# ============================================================


def urgency_for_remaining(remaining):
    if remaining is None:
        return "normal"
    if remaining <= 0:
        return "red"
    if warning_seconds() > 0 and remaining <= warning_seconds():
        return "orange"
    return "normal"


def get_upcoming_events(i, now):
    if is_ended(i):
        return []

    upcoming = []
    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    board_start = st.session_state[f"board_start_{i}"]
    shock_start = st.session_state[f"shock_start_{i}"]
    resus_start = st.session_state[f"resus_start_{i}"]

    if anesthesia_start is not None:
        upcoming.append(("Anesthesia redose", anesthesia_remaining(i, now)))

    if board_start is not None and shock_start is None:
        upcoming.append(
            (
                "Shock",
                remaining_from_start(board_start, FIXED_BOARD_DURATION, now),
            )
        )

    if shock_start is not None and resus_start is None:
        upcoming.append(
            (
                "Resuscitation",
                remaining_from_start(shock_start, FIXED_SHOCK_DURATION, now),
            )
        )

    if resus_start is not None:
        upcoming.append(
            (
                "Resuscitation complete",
                remaining_from_start(resus_start, FIXED_RESUSCITATION_DURATION, now),
            )
        )

    return upcoming


def action_targets_for_alert(i, event_name, remaining):
    if is_ended(i) or is_paused(i):
        return []

    if event_name == "Anesthesia redose":
        if st.session_state[f"anesthesia_start_{i}"] is None:
            return []
        return [
            {"key": f"anesthesia_redose_action_{i}", "style": "primary"},
            {"key": f"anesthesia_delay_action_{i}", "style": "delay"},
        ]

    if remaining > 0:
        return []

    if event_name == "Shock" and st.session_state[f"shock_start_{i}"] is None:
        return [{"key": f"primary_action_{i}", "style": "primary"}]

    if event_name == "Resuscitation" and st.session_state[f"resus_start_{i}"] is None:
        return [{"key": f"primary_action_{i}", "style": "primary"}]

    if event_name == "Resuscitation complete":
        return [{"key": f"primary_action_{i}", "style": "primary"}]

    return []


def collect_attention_items(wall_now):
    sticky = st.session_state["_sticky_alerts"]
    active_keys = set()

    for i in range(1, mouse_count() + 1):
        if is_ended(i):
            clear_mouse_alerts(i)
            continue

        now = effective_now(i, wall_now)
        for event_name, remaining in get_upcoming_events(i, now):
            key = alert_key(i, event_name)
            active_keys.add(key)
            level = urgency_for_remaining(remaining)

            if level in ("orange", "red"):
                sticky[key] = {
                    "mouse": i,
                    "event": event_name,
                    "remaining": remaining,
                    "level": level,
                }

    for key in list(sticky):
        if key not in active_keys:
            sticky.pop(key, None)

    items = []
    for item in sticky.values():
        copied = dict(item)
        copied["targets"] = action_targets_for_alert(
            copied["mouse"], copied["event"], copied["remaining"]
        )
        items.append(copied)

    items.sort(
        key=lambda item: (
            0 if item["level"] == "red" else 1,
            item["remaining"],
        )
    )
    return items


def encode_attention_snapshot(items):
    payload = []
    for item in items:
        payload.append(
            {
                "mouse": item["mouse"],
                "subject": subject_name(item["mouse"]),
                "event": item["event"],
                "level": item["level"],
                "targets": item.get("targets", []),
            }
        )
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def render_attention_snapshot(items):
    encoded = encode_attention_snapshot(items)
    st.html(
        f'<div data-lab-attention-snapshot="{encoded}" '
        'style="display:none !important;"></div>'
    )




# ============================================================
# PERSISTENT BROWSER-OWNED ATTENTION BAR / BUTTON HIGHLIGHTS
# ============================================================


def install_browser_helpers():
    st.iframe(
        r''' 
        <script>
        (() => {
            const parentDoc = window.parent.document;
            const BAR_ID = "lab-attention-overlay-v28";
            const STYLE_ID = "lab-attention-overlay-style-v28";
            const PRIMARY_CLASS = "lab-next-action-primary-v28";
            const DELAY_CLASS = "lab-next-action-delay-v28";

            [
                "lab-attention-overlay-v16",
                "lab-attention-overlay-style-v16",
                "lab-attention-overlay-v12",
                "lab-attention-overlay-style-v12",
                "lab-attention-overlay-v10",
                "lab-attention-overlay-style-v10",
                "lab-attention-overlay-v9",
                "lab-attention-overlay-style-v9"
            ].forEach((id) => {
                const oldNode = parentDoc.getElementById(id);
                if (oldNode) oldNode.remove();
            });

            let style = parentDoc.getElementById(STYLE_ID);
            if (!style) {
                style = parentDoc.createElement("style");
                style.id = STYLE_ID;
                style.textContent = `
                    .${PRIMARY_CLASS} button {
                        border-color: rgba(255, 152, 15, 0.95) !important;
                        background: rgba(255, 152, 15, 0.12) !important;
                        box-shadow: 0 0 0 2px rgba(255, 152, 15, 0.10) !important;
                        color: #ffe7c2 !important;
                    }
                    .${DELAY_CLASS} button {
                        border-color: rgba(191, 90, 242, 0.78) !important;
                        background: rgba(191, 90, 242, 0.09) !important;
                        box-shadow: 0 0 0 2px rgba(191, 90, 242, 0.08) !important;
                    }
                `;
                parentDoc.head.appendChild(style);
            }

            let bar = parentDoc.getElementById(BAR_ID);
            if (!bar) {
                bar = parentDoc.createElement("div");
                bar.id = BAR_ID;
                Object.assign(bar.style, {
                    position: "fixed",
                    left: "1rem",
                    right: "1rem",
                    bottom: "0.75rem",
                    zIndex: "999999",
                    boxSizing: "border-box",
                    height: "2.18rem",
                    minHeight: "2.18rem",
                    maxHeight: "2.18rem",
                    overflowX: "hidden",
                    overflowY: "hidden",
                    display: "flex",
                    alignItems: "center",
                    padding: "0.32rem 2.85rem 0.32rem 0.62rem",
                    background: "rgba(22, 28, 37, 0.97)",
                    color: "white",
                    border: "1px solid rgba(148, 163, 184, 0.28)",
                    borderRadius: "0.48rem",
                    boxShadow: "0 7px 24px rgba(0,0,0,0.24)",
                    contain: "layout paint",
                    transform: "translateZ(0)",
                    opacity: "0",
                    visibility: "hidden",
                    pointerEvents: "none"
                });
                parentDoc.body.appendChild(bar);
            }

            let lastEncoded = bar.dataset.lastSnapshot || null;
            let currentTargets = [];
            let dismissedSnapshot = bar.dataset.dismissedSnapshot || null;

            const shortNames = {
                "Anesthesia redose": "Anesthesia redose",
                "Shock": "Shock due",
                "Resuscitation": "Resus due",
                "Resuscitation complete": "Resus complete"
            };

            function escapeHtml(value) {
                const div = parentDoc.createElement("div");
                div.textContent = String(value);
                return div.innerHTML;
            }

            function decodeSnapshot(encoded) {
                try {
                    return JSON.parse(atob(encoded));
                } catch (err) {
                    return null;
                }
            }

            function hideBar() {
                bar.style.opacity = "0";
                bar.style.visibility = "hidden";
                bar.style.pointerEvents = "none";
            }

            function rebuildBar(items, encoded) {
                if (!items || items.length === 0 || dismissedSnapshot === encoded) {
                    hideBar();
                    return;
                }

                const mouseCount = new Set(items.map((item) => item.mouse)).size;
                const noun = mouseCount === 1 ? "mouse" : "mice";

                let body = `
                    <div style="display:flex;align-items:center;width:100%;overflow-x:auto;overflow-y:hidden;padding-right:0.4rem;box-sizing:border-box;">
                    <span style="font-size:1.08rem;margin-right:0.7rem;color:#f4f6f8;">⚠</span>
                    <span style="font-size:0.91rem;font-weight:760;white-space:nowrap;margin-right:0.9rem;">Attention required</span>
                    <span style="font-size:0.82rem;color:#b8c1cc;white-space:nowrap;margin-right:0.8rem;">${mouseCount} ${noun} need action</span>
                `;

                for (const item of items) {
                    const overdue = item.level === "red";
                    const border = overdue ? "rgba(233,77,98,0.88)" : "rgba(255,152,15,0.88)";
                    const background = overdue ? "rgba(233,77,98,0.20)" : "rgba(255,152,15,0.18)";
                    const text = overdue ? "#ff9aa6" : "#ffc36b";
                    const dot = overdue ? "#e94d62" : "#ff980f";

                    let shortEvent = shortNames[item.event] || item.event;
                    if (!overdue) {
                        if (item.event === "Shock") shortEvent = "Shock soon";
                        if (item.event === "Resuscitation") shortEvent = "Resus soon";
                        if (item.event === "Resuscitation complete") shortEvent = "Resus ending";
                        if (item.event === "Anesthesia redose") shortEvent = "Anesthesia redose soon";
                    }

                    body += `
                        <span title="${escapeHtml(item.event)}" style="
                            display:inline-flex;
                            align-items:center;
                            border:1px solid ${border};
                            background:${background};
                            border-radius:999px;
                            padding:0.25rem 0.66rem;
                            margin:0 0.22rem;
                            font-size:0.76rem;
                            white-space:nowrap;
                        ">
                            <span style="width:0.44rem;height:0.44rem;border-radius:50%;background:${dot};margin-right:0.42rem;flex:0 0 auto;"></span>
                            <strong style="margin-right:0.34rem;color:#f5f7f9;">${escapeHtml(item.subject || `Mouse ${item.mouse}`)}</strong>
                            <span style="color:${text};font-weight:670;">${escapeHtml(shortEvent)}</span>
                        </span>
                    `;
                }

                body += `
                    </div>
                    <button id="lab-attention-close-v28" aria-label="Dismiss attention banner" style="
                        position:absolute;
                        right:0.48rem;
                        top:50%;
                        transform:translateY(-50%);
                        z-index:3;
                        width:2.05rem;
                        height:1.8rem;
                        border:0;
                        border-radius:0.35rem;
                        background:rgba(22,28,37,0.98);
                        color:#eef2f6;
                        font-size:1.35rem;
                        line-height:1;
                        padding:0;
                        cursor:pointer;
                    ">×</button>
                `;

                bar.innerHTML = body;
                bar.style.visibility = "visible";
                bar.style.opacity = "1";
                bar.style.pointerEvents = "auto";

                const closeButton = parentDoc.getElementById("lab-attention-close-v28");
                if (closeButton) {
                    closeButton.onclick = () => {
                        dismissedSnapshot = encoded;
                        bar.dataset.dismissedSnapshot = encoded;
                        hideBar();
                    };
                }
            }

            function reapplyHighlights() {
                const desired = new Map();
                for (const target of currentTargets) {
                    if (!target || !target.key) continue;
                    desired.set(
                        target.key,
                        target.style === "delay" ? DELAY_CLASS : PRIMARY_CLASS
                    );
                }

                parentDoc.querySelectorAll(`.${PRIMARY_CLASS}, .${DELAY_CLASS}`).forEach((node) => {
                    const keyClass = Array.from(node.classList).find((name) => name.startsWith("st-key-"));
                    const key = keyClass ? keyClass.slice(7) : null;
                    const wantedClass = key ? desired.get(key) : null;
                    if (!wantedClass || !node.classList.contains(wantedClass)) {
                        node.classList.remove(PRIMARY_CLASS, DELAY_CLASS);
                    }
                });

                for (const [key, cls] of desired.entries()) {
                    parentDoc.querySelectorAll(`.st-key-${key}`).forEach((node) => {
                        const button = node.querySelector("button");
                        if (button && !button.disabled && !node.classList.contains(cls)) {
                            node.classList.remove(PRIMARY_CLASS, DELAY_CLASS);
                            node.classList.add(cls);
                        }
                    });
                }
            }

            function applyEncoded(encoded) {
                const items = decodeSnapshot(encoded);
                if (items === null) return;

                if (encoded !== lastEncoded) {
                    dismissedSnapshot = null;
                    delete bar.dataset.dismissedSnapshot;
                }

                lastEncoded = encoded;
                bar.dataset.lastSnapshot = encoded;
                currentTargets = [];

                for (const item of items) {
                    for (const target of (item.targets || [])) {
                        if (!currentTargets.some((x) => x.key === target.key && x.style === target.style)) {
                            currentTargets.push(target);
                        }
                    }
                }

                rebuildBar(items, encoded);
            }

            function hideOriginatingPopoversWhileDialogOpen() {
                const dialog = parentDoc.querySelector('[data-testid="stDialog"], [role="dialog"]');
                const dialogOpen = !!dialog;

                const hideNode = (node) => {
                    if (!node || (dialog && dialog.contains(node))) return;
                    if (!node.dataset.labHiddenForDialog) {
                        node.dataset.labHiddenForDialog = "1";
                        node.dataset.labPrevDisplay = node.style.display || "";
                        node.dataset.labPrevVisibility = node.style.visibility || "";
                        node.dataset.labPrevPointerEvents = node.style.pointerEvents || "";
                    }
                    node.style.display = "none";
                    node.style.visibility = "hidden";
                    node.style.pointerEvents = "none";
                };

                if (dialogOpen) {
                    // First cover Streamlit/BaseWeb's known popover portal shapes.
                    parentDoc.querySelectorAll(
                        '[data-baseweb="popover"], [data-testid="stPopoverBody"], [data-testid="stPopover"]'
                    ).forEach(hideNode);

                    // Fallback for frontend DOM changes: locate the visible mouse
                    // menu by its unique action labels, then hide the nearest
                    // floating/portal ancestor. This is visual-only and DOES NOT
                    // click the ⋮ trigger, so it cannot cause a rerun that would
                    // dismiss the newly opened dialog.
                    const menuLabels = new Set([
                        "View timesheet", "Add comment", "Rename subject",
                        "Ⅱ Pause", "▶ Resume", "■ End experiment"
                    ]);

                    parentDoc.querySelectorAll('button').forEach((button) => {
                        if (dialog && dialog.contains(button)) return;
                        const text = (button.textContent || "").trim();
                        if (!menuLabels.has(text)) return;

                        let node = button.parentElement;
                        let candidate = null;
                        for (let depth = 0; node && depth < 9; depth++, node = node.parentElement) {
                            if (dialog && dialog.contains(node)) break;
                            const testid = node.getAttribute && node.getAttribute('data-testid');
                            const baseweb = node.getAttribute && node.getAttribute('data-baseweb');
                            const pos = window.getComputedStyle(node).position;
                            if (
                                testid === 'stPopoverBody' || testid === 'stPopover' ||
                                baseweb === 'popover' || pos === 'fixed' || pos === 'absolute'
                            ) {
                                candidate = node;
                            }
                        }
                        hideNode(candidate || button.closest('[data-baseweb="popover"]'));
                    });
                } else {
                    parentDoc.querySelectorAll('[data-lab-hidden-for-dialog="1"]').forEach((node) => {
                        node.style.display = node.dataset.labPrevDisplay || "";
                        node.style.visibility = node.dataset.labPrevVisibility || "";
                        node.style.pointerEvents = node.dataset.labPrevPointerEvents || "";
                        delete node.dataset.labHiddenForDialog;
                        delete node.dataset.labPrevDisplay;
                        delete node.dataset.labPrevVisibility;
                        delete node.dataset.labPrevPointerEvents;
                    });
                }
            }

            // Streamlit/BaseWeb tooltip markup has changed across releases.
            // CSS alone can therefore miss the outer portal and allow a brief
            // immediate flash. Hide every newly mounted tooltip portal at the
            // DOM level and release it only after a full 1000 ms hover dwell.
            const TOOLTIP_DELAY_MS = 1000;

            function tooltipRootFor(node) {
                if (!node || node.nodeType !== 1) return null;
                if (node.matches && (node.matches('[role="tooltip"]') || node.matches('[data-baseweb="tooltip"]'))) {
                    return node.closest('[data-baseweb="popover"]') || node;
                }
                const tip = node.querySelector && node.querySelector('[role="tooltip"], [data-baseweb="tooltip"]');
                return tip ? (tip.closest('[data-baseweb="popover"]') || tip) : null;
            }

            function delayTooltip(root) {
                if (!root || root.dataset.labTooltipDelayBound === "1") return;
                root.dataset.labTooltipDelayBound = "1";
                root.style.setProperty('opacity', '0', 'important');
                root.style.setProperty('visibility', 'hidden', 'important');
                root.style.setProperty('pointer-events', 'none', 'important');

                window.setTimeout(() => {
                    if (!root.isConnected) return;
                    root.style.removeProperty('opacity');
                    root.style.removeProperty('visibility');
                    root.style.removeProperty('pointer-events');
                    root.dataset.labTooltipDelayReleased = "1";
                }, TOOLTIP_DELAY_MS);
            }

            function scanExistingTooltips() {
                parentDoc.querySelectorAll('[role="tooltip"], [data-baseweb="tooltip"]').forEach((tip) => {
                    delayTooltip(tip.closest('[data-baseweb="popover"]') || tip);
                });
            }

            const tooltipObserver = new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes) {
                        const root = tooltipRootFor(node);
                        if (root) delayTooltip(root);
                    }
                }
            });
            tooltipObserver.observe(parentDoc.body, { childList: true, subtree: true });
            scanExistingTooltips();

            function attachFullscreenHandler() {
                const wrapper = parentDoc.querySelector('.st-key-fullscreen_view');
                if (!wrapper || wrapper.dataset.fullscreenBound === "1") return;
                const button = wrapper.querySelector('button');
                if (!button) return;
                wrapper.dataset.fullscreenBound = "1";
                button.addEventListener('click', () => {
                    const root = parentDoc.documentElement;
                    if (!parentDoc.fullscreenElement && root.requestFullscreen) {
                        root.requestFullscreen().catch(() => {});
                    } else if (parentDoc.fullscreenElement && parentDoc.exitFullscreen) {
                        parentDoc.exitFullscreen().catch(() => {});
                    }
                }, true);
            }

            function processAutoDownload() {
                const markers = parentDoc.querySelectorAll("[data-lab-auto-download-token]");
                if (!markers.length) return;
                const marker = markers[markers.length - 1];
                const token = marker.getAttribute("data-lab-auto-download-token");
                const filename = marker.getAttribute("data-lab-auto-download-filename") || "shock_timer_timesheets.txt";
                const encoded = marker.getAttribute("data-lab-auto-download-content");
                if (!token || !encoded) return;
                if (parentDoc.documentElement.dataset.labLastAutoDownloadToken === token) return;

                try {
                    const binary = atob(encoded);
                    const bytes = new Uint8Array(binary.length);
                    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                    const blob = new Blob([bytes], { type: "text/plain;charset=utf-8" });
                    const url = URL.createObjectURL(blob);
                    const link = parentDoc.createElement("a");
                    link.href = url;
                    link.download = filename;
                    link.style.display = "none";
                    parentDoc.body.appendChild(link);
                    parentDoc.documentElement.dataset.labLastAutoDownloadToken = token;
                    link.click();
                    link.remove();
                    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
                } catch (err) {
                    console.warn("Shock Timer automatic timesheet download failed", err);
                }
            }

            if (lastEncoded) applyEncoded(lastEncoded);

            function poll() {
                const snapshots = parentDoc.querySelectorAll("[data-lab-attention-snapshot]");
                if (snapshots.length) {
                    const snapshot = snapshots[snapshots.length - 1];
                    const encoded = snapshot.getAttribute("data-lab-attention-snapshot");
                    if (encoded && encoded !== lastEncoded) applyEncoded(encoded);
                }

                reapplyHighlights();
                attachFullscreenHandler();
                processAutoDownload();
            }

            poll();
            window.setInterval(poll, 150);
        })();
        </script>
        ''',
        width=1,
        height=1,
        tab_index=-1,
    )

render_pending_auto_download_marker()
install_browser_helpers()


# ============================================================
# HEADER / SETTINGS
# ============================================================

header_cols = st.columns([1.18, 4.85, 1.10, 1.55, 1.28, 0.95], vertical_alignment="center")

with header_cols[0]:
    if st.button("←  Experiments", key="return_to_experiment_home", use_container_width=True):
        return_to_experiment_home()

with header_cols[1]:
    experiment_name = html.escape(str(st.session_state.get("_experiment_name", "Experiment")))
    st.markdown(
        f'<div class="lab-header-title">Shock Timer <span style="color:#8f9baa;font-weight:620;font-size:1.02rem;">· {experiment_name}</span></div>',
        unsafe_allow_html=True,
    )

with header_cols[2]:
    st.button("⛶  Fullscreen", key="fullscreen_view", use_container_width=True)

with header_cols[3]:
    st.download_button(
        "⇩  Export timesheets",
        data=build_all_timesheets_text(),
        file_name=f"shock_timer_timesheets_{wall_datetime().strftime('%Y-%m-%d')}.txt",
        mime="text/plain",
        key="export_timesheets",
        use_container_width=True,
    )

with header_cols[4]:
    if st.button(
        "■  End all",
        key="end_all_subjects_header",
        use_container_width=True,
        disabled=all_subjects_ended(),
        help="End every remaining subject and mark this experiment complete.",
    ):
        end_all_subjects_dialog()

with header_cols[5]:
    if st.button("⚙  Settings", key="open_settings_dialog", use_container_width=True):
        settings_dialog()

st.markdown('<div class="lab-divider"></div>', unsafe_allow_html=True)

if st.session_state.get("_storage_error"):
    unsaved = st.session_state.get("_unsaved_subjects", [])
    subject_text = ", ".join(subject_name(i) for i in unsaved) if unsaved else "database connection"
    warning_cols = st.columns([5.6, 1.15], vertical_alignment="center")
    with warning_cols[0]:
        st.error(
            f"SAVE WARNING: Neon could not save the latest state for {subject_text}. "
            "The newest state is still present in this browser session. "
            "Do not close or refresh this page until the save succeeds."
        )
    with warning_cols[1]:
        if st.button("Retry save", key="retry_neon_save", use_container_width=True, type="primary"):
            retry_unsaved_subjects()
            st.rerun()


# ============================================================
# ROW RENDERING HELPERS
# ============================================================


def mouse_is_complete(i, now):
    """True once resuscitation duration has elapsed, or the subject was ended."""
    if is_ended(i):
        return True
    resus_start = st.session_state[f"resus_start_{i}"]
    if resus_start is None:
        return False
    remaining = remaining_from_start(resus_start, FIXED_RESUSCITATION_DURATION, now)
    return remaining is not None and remaining <= 0


def html_cell(primary, secondary=None, tone="normal"):
    primary_class = f"lab-primary-text {tone}" if tone != "normal" else "lab-primary-text"
    secondary_html = ""
    if secondary:
        secondary_html = f'<div class="lab-secondary-text">{html.escape(secondary)}</div>'
    return (
        '<div class="lab-cell">'
        f'<div class="{primary_class}">{html.escape(primary)}</div>'
        f'{secondary_html}'
        '</div>'
    )


def mouse_status_tone(i, now):
    if is_paused(i):
        return "gray"
    if is_ended(i) or st.session_state[f"experiment_start_{i}"] is None:
        return "gray"

    levels = [urgency_for_remaining(rem) for _, rem in get_upcoming_events(i, now)]
    if "red" in levels:
        return "red"
    if "orange" in levels:
        return "orange"
    return "green"


def get_next_event_display(i, now):
    if is_ended(i):
        return "Ended", "gray"

    if st.session_state[f"experiment_start_{i}"] is None:
        return "Not started", "gray"

    upcoming = get_upcoming_events(i, now)
    if not upcoming:
        return "Ready", "green"

    event_name, remaining = min(upcoming, key=lambda item: item[1])
    tone = urgency_for_remaining(remaining)

    friendly = {
        "Anesthesia redose": "Anesthesia",
        "Shock": "Shock",
        "Resuscitation": "Resus",
        "Resuscitation complete": "Resus",
    }[event_name]

    if remaining <= 0:
        overdue = format_timer(-remaining)
        if event_name == "Anesthesia redose":
            return f"Redose due +{overdue}", tone
        if event_name == "Resuscitation complete":
            return f"Resus complete +{overdue}", tone
        return f"{friendly} due +{overdue}", tone

    return f"{friendly} in {format_timer(remaining)}", tone


def phase_display(i, now):
    if is_ended(i):
        shock_clock = st.session_state[f"shock_wallclock_{i}"]
        detail = f"Shock started {shock_clock}" if shock_clock else "Experiment ended"
        return "Ended", detail, "gray"

    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    board_start = st.session_state[f"board_start_{i}"]
    shock_start = st.session_state[f"shock_start_{i}"]
    resus_start = st.session_state[f"resus_start_{i}"]

    if anesthesia_start is None:
        return "Not started", "— / —", "gray"

    if board_start is None:
        elapsed = elapsed_from(anesthesia_start, now)
        return "Anesthesia", f"{format_timer(elapsed)} / —", "green"

    if shock_start is None:
        elapsed = elapsed_from(board_start, now)
        remaining = remaining_from_start(board_start, FIXED_BOARD_DURATION, now)
        tone = urgency_for_remaining(remaining)
        return (
            "Board acclimation",
            f"{format_timer(elapsed)} / {format_timer(duration_to_seconds(FIXED_BOARD_DURATION))}",
            tone if tone != "normal" else "green",
        )

    if resus_start is None:
        elapsed = elapsed_from(shock_start, now)
        remaining = remaining_from_start(shock_start, FIXED_SHOCK_DURATION, now)
        tone = urgency_for_remaining(remaining)
        return (
            "Shock",
            f"{format_timer(elapsed)} / {format_timer(duration_to_seconds(FIXED_SHOCK_DURATION))}",
            tone if tone != "normal" else "green",
        )

    elapsed = elapsed_from(resus_start, now)
    remaining = remaining_from_start(resus_start, FIXED_RESUSCITATION_DURATION, now)
    tone = urgency_for_remaining(remaining)
    return (
        "Resuscitation",
        f"{format_timer(elapsed)} / {format_timer(duration_to_seconds(FIXED_RESUSCITATION_DURATION))}",
        tone if tone != "normal" else "green",
    )


def anesthesia_display(i, now):
    start = st.session_state[f"anesthesia_start_{i}"]
    interval = st.session_state[f"anesthesia_duration_{i}"]
    delay = st.session_state[f"anesthesia_delay_duration_{i}"]
    secondary = f"Interval {interval}{UNIT_SHORT}  •  Delay {delay}{UNIT_SHORT}"

    if start is None:
        return "Not started", secondary, "gray"

    remaining = anesthesia_remaining(i, now)
    tone = urgency_for_remaining(remaining)
    if remaining <= 0:
        return "Redose due", secondary, tone
    return f"Redose in {format_timer(remaining)}", secondary, tone if tone != "normal" else "normal"



def render_anesthesia_controls(i):
    """Show early-redose and delay controls only after the mouse has started."""
    delay = st.session_state[f"anesthesia_delay_duration_{i}"]
    # Before the primary Start action, both anesthesia secondary controls must be
    # visibly and functionally disabled. The experiment clock and initial
    # anesthesia dose are created together by that Start action.
    disabled = (
        st.session_state[f"experiment_start_{i}"] is None
        or st.session_state[f"anesthesia_start_{i}"] is None
        or is_paused(i)
        or is_ended(i)
    )

    control_cols = st.columns(2, gap="small")
    with control_cols[0]:
        with st.container(key=f"anesthesia_redose_action_{i}"):
            st.button(
                "💉 Redose now",
                key=f"anesthesia_redose_button_{i}",
                use_container_width=True,
                disabled=disabled,
                help="Record a redose now and restart the normal redose interval from this moment.",
                on_click=start_or_redose_anesthesia,
                args=(i,),
            )

    with control_cols[1]:
        with st.container(key=f"anesthesia_delay_action_{i}"):
            st.button(
                f"Delay +{delay}{UNIT_SHORT}",
                key=f"anesthesia_delay_button_{i}",
                use_container_width=True,
                disabled=disabled,
                help="Set the next redose reminder to this delay interval from the moment this button is pressed.",
                on_click=delay_anesthesia_reminder,
                args=(i,),
            )


def workflow_statuses(i, now):
    """Return a visual state for each of the four procedural milestones."""
    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    board_start = st.session_state[f"board_start_{i}"]
    shock_start = st.session_state[f"shock_start_{i}"]
    resus_start = st.session_state[f"resus_start_{i}"]

    states = ["pending", "pending", "pending", "pending"]

    if anesthesia_start is None:
        return states

    states[0] = "active" if board_start is None else "complete"

    if board_start is not None:
        if shock_start is not None:
            states[1] = "complete"
        else:
            rem = remaining_from_start(board_start, FIXED_BOARD_DURATION, now)
            urgency = urgency_for_remaining(rem)
            states[1] = "overdue" if urgency == "red" else "action" if urgency == "orange" else "active"

    if shock_start is not None:
        if resus_start is not None:
            states[2] = "complete"
        else:
            rem = remaining_from_start(shock_start, FIXED_SHOCK_DURATION, now)
            urgency = urgency_for_remaining(rem)
            states[2] = "overdue" if urgency == "red" else "action" if urgency == "orange" else "active"

    if resus_start is not None:
        if is_ended(i):
            states[3] = "complete"
        else:
            rem = remaining_from_start(resus_start, FIXED_RESUSCITATION_DURATION, now)
            urgency = urgency_for_remaining(rem)
            states[3] = "overdue" if urgency == "red" else "action" if urgency == "orange" else "active"

    return states


def workflow_html(i, now):
    states = workflow_statuses(i, now)
    labels = [
        "Anesthesia",
        f"Board {fixed_duration_label(FIXED_BOARD_DURATION)}",
        f"Shock {fixed_duration_label(FIXED_SHOCK_DURATION)}",
        f"Resus {fixed_duration_label(FIXED_RESUSCITATION_DURATION)}",
    ]
    parts = ['<div class="lab-cell"><div class="lab-stepper">']
    for idx, (state, label) in enumerate(zip(states, labels), start=1):
        parts.append(
            f'<div class="lab-step {state}">'
            f'<div class="lab-step-circle">{idx}</div>'
            f'<div class="lab-step-label">{html.escape(label)}</div>'
            '</div>'
        )
    parts.append("</div></div>")
    return "".join(parts)


def actionable_event_for_mouse(i, now):
    """Choose the highest-priority resolving action currently available."""
    if is_ended(i):
        return None
    if is_paused(i):
        return "resume"

    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    board_start = st.session_state[f"board_start_{i}"]
    shock_start = st.session_state[f"shock_start_{i}"]
    resus_start = st.session_state[f"resus_start_{i}"]

    if anesthesia_start is None:
        return "start_anesthesia"

    due_candidates = []

    if board_start is not None and shock_start is None:
        rem = remaining_from_start(board_start, FIXED_BOARD_DURATION, now)
        if rem <= 0:
            due_candidates.append((rem, "start_shock"))

    if shock_start is not None and resus_start is None:
        rem = remaining_from_start(shock_start, FIXED_SHOCK_DURATION, now)
        if rem <= 0:
            due_candidates.append((rem, "start_resus"))

    if resus_start is not None:
        rem = remaining_from_start(resus_start, FIXED_RESUSCITATION_DURATION, now)
        if rem <= 0:
            due_candidates.append((rem, "end"))

    if due_candidates:
        return min(due_candidates, key=lambda item: item[0])[1]

    if board_start is None:
        return "start_board"

    return "pause"


def render_primary_action(i, now):
    action = actionable_event_for_mouse(i, now)

    if action is None:
        st.button("Ended", key=f"ended_button_{i}", disabled=True, use_container_width=True)
        return

    if action == "resume":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "▶  Resume",
                key=f"resume_button_{i}",
                use_container_width=True,
                on_click=toggle_pause,
                args=(i,),
            )
        return

    if action == "start_anesthesia":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "▷  Start",
                key=f"start_anesthesia_button_{i}",
                use_container_width=True,
                on_click=start_or_redose_anesthesia,
                args=(i,),
            )
        return

    if action == "start_board":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "▷  Start board",
                key=f"start_board_button_{i}",
                use_container_width=True,
                on_click=start_board,
                args=(i,),
            )
        return

    if action == "start_shock":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "⚡  Start shock",
                key=f"start_shock_button_{i}",
                use_container_width=True,
                on_click=start_shock,
                args=(i,),
            )
        return

    if action == "start_resus":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "♥  Start resus",
                key=f"start_resus_button_{i}",
                use_container_width=True,
                on_click=start_resuscitation,
                args=(i,),
            )
        return

    if action == "end":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "■  End",
                key=f"end_direct_button_{i}",
                use_container_width=True,
                on_click=request_dialog,
                args=(i, "end"),
            )
        return

    with st.container(key=f"primary_pause_{i}"):
        st.button(
            "Ⅱ  Pause",
            key=f"pause_button_{i}",
            use_container_width=True,
            on_click=toggle_pause,
            args=(i,),
        )


def _process_mouse_menu_selection(i, selection):
    """Handle one selection from the native per-mouse action menu."""
    if not selection:
        return

    if selection in ("Ⅱ Pause", "▶ Resume"):
        toggle_pause(i)
        # Menu selection occurs inside the one-second dashboard fragment. A
        # direct rerun here intentionally escalates to a full-app rerun.
        st.rerun()

    dialog_map = {
        "View timesheet": "timesheet",
        "Add comment": "comment",
        "Rename subject": "rename",
        "■ End experiment": "end",
    }
    kind = dialog_map.get(selection)
    if kind:
        request_dialog(i, kind)
        # st.menu_button closes itself as soon as an option is selected. This
        # full-app rerun then opens the requested st.dialog at top level, so no
        # dropdown/popover remains behind or on top of the modal.
        st.rerun()


def render_overflow_control(i, now):
    experiment_start = st.session_state[f"experiment_start_{i}"]
    ended = is_ended(i)
    paused = is_paused(i)

    options = [
        "View timesheet",
        "Add comment",
        "Rename subject",
    ]
    if experiment_start is not None and not ended:
        options.append("▶ Resume" if paused else "Ⅱ Pause")
        options.append("■ End experiment")

    with st.container(key=f"overflow_action_{i}"):
        if hasattr(st, "menu_button"):
            # Use the purpose-built action-menu widget rather than st.popover.
            # Unlike a popover containing buttons, menu_button closes natively
            # when an option is selected and returns that option on the rerun.
            selection = st.menu_button(
                "⋮",
                options=options,
                key=f"mouse_action_menu_{i}",
                width="stretch",
            )
            _process_mouse_menu_selection(i, selection)
        else:
            # Compatibility fallback for older Streamlit versions. The app's
            # recommended/current Streamlit release provides st.menu_button.
            with st.popover("⋮", use_container_width=True):
                for option in options:
                    if st.button(
                        option,
                        key=f"legacy_mouse_menu_{i}_{option}",
                        use_container_width=True,
                    ):
                        _process_mouse_menu_selection(i, option)

            shock_clock = st.session_state[f"shock_wallclock_{i}"]
            if shock_clock:
                st.caption(f"Shock started: {shock_clock}")


# ============================================================
# COLUMN HEADERS
# ============================================================

column_widths = [1.12, 1.35, 1.05, 2.48, 1.28, 1.85, 1.48]
headers = [
    "Mouse",
    "Next event",
    "Total elapsed",
    "Workflow",
    "Current phase",
    "Anesthesia",
    "Actions",
]

header_row = st.columns(column_widths, vertical_alignment="center")
for col, label in zip(header_row, headers):
    with col:
        st.markdown(
            f'<div class="lab-column-header">{html.escape(label)}</div>',
            unsafe_allow_html=True,
        )


# ============================================================
# LIVE DASHBOARD
# ============================================================


def render_mouse_row(i, wall_now, finished=False):
    now = effective_now(i, wall_now)
    experiment_start = st.session_state[f"experiment_start_{i}"]
    experiment_elapsed = elapsed_from(experiment_start, now)

    with st.container(border=True, key=f"mouse_row_{i}"):
        if finished:
            st.markdown('<span data-lab-row-finished="true" style="display:none"></span>', unsafe_allow_html=True)

        cols = st.columns(column_widths, vertical_alignment="center")

        # Mouse / renamed subject
        with cols[0]:
            dot_tone = mouse_status_tone(i, now)
            display_name = html.escape(subject_name(i))
            if is_paused(i):
                pause_started = st.session_state[f"pause_started_{i}"]
                pause_elapsed = max(0.0, wall_now - pause_started) if pause_started is not None else 0.0
                st.markdown(
                    '<span data-lab-row-paused="true" style="display:none"></span>'
                    '<div class="lab-mouse-cell">'
                    f'<div class="lab-paused-label">Paused <span class="lab-paused-time">{html.escape(format_timer(pause_elapsed))}</span></div>'
                    '<div class="lab-mouse-wrap">'
                    f'<span class="lab-dot {dot_tone}"></span>'
                    f'<span class="lab-mouse-name">{display_name}</span>'
                    '</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="lab-mouse-wrap">'
                    f'<span class="lab-dot {dot_tone}"></span>'
                    f'<span class="lab-mouse-name">{display_name}</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )

        with cols[1]:
            next_text, tone = get_next_event_display(i, now)
            st.markdown(html_cell(next_text, tone=tone), unsafe_allow_html=True)

        with cols[2]:
            st.markdown(
                '<div class="lab-cell"><div class="lab-total">'
                '<span class="lab-clock">◷</span>'
                f'<span>{format_total_elapsed(experiment_elapsed)}</span>'
                '</div></div>',
                unsafe_allow_html=True,
            )

        with cols[3]:
            st.markdown(workflow_html(i, now), unsafe_allow_html=True)

        with cols[4]:
            phase, phase_time, phase_tone = phase_display(i, now)
            st.markdown(html_cell(phase, phase_time, phase_tone), unsafe_allow_html=True)

        with cols[5]:
            anes_primary, anes_secondary, anes_tone = anesthesia_display(i, now)
            st.markdown(html_cell(anes_primary, anes_secondary, anes_tone), unsafe_allow_html=True)
            render_anesthesia_controls(i)

        with cols[6]:
            with st.container(key=f"actions_cell_{i}"):
                action_cols = st.columns([1.0, 0.28], gap="small")
                with action_cols[0]:
                    render_primary_action(i, now)
                with action_cols[1]:
                    render_overflow_control(i, now)


@st.fragment(run_every=REFRESH_INTERVAL)
def show_timers():
    # Widgets in this dashboard live inside a fragment, so their interactions
    # normally rerun only this fragment. A dialog, however, must be opened by
    # the full script. request_dialog() stores the requested modal; this bridge then performs
    # the documented full-app rerun. The native st.menu_button has already closed
    # after selection, and render_pending_dialog() opens the modal at top level.
    if st.session_state.get("_pending_dialog"):
        st.rerun()

    if st.session_state.pop("_needs_full_rerun", False):
        st.rerun()

    # Never contact Neon from the 1-second display fragment. The fragment must
    # remain a fast, entirely local render loop so the controls do not stay
    # greyed out while Streamlit waits on network round trips. Timer accuracy
    # does not depend on polling: all starts/deadlines are absolute epoch times.
    wall_now = time.time()
    attention_items = collect_attention_items(wall_now)
    render_attention_snapshot(attention_items)

    active_subjects = []
    completed_subjects = []
    for i in range(1, mouse_count() + 1):
        now = effective_now(i, wall_now)
        if mouse_is_complete(i, now):
            completed_subjects.append(i)
        else:
            active_subjects.append(i)

    for i in active_subjects:
        render_mouse_row(i, wall_now, finished=False)

    # The add-subject control belongs directly after the final ACTIVE subject.
    # Completed/ended subjects are intentionally below it in their own section.
    add_cols = st.columns([1.2, 5.8])
    with add_cols[0]:
        st.button(
            "+  Add mouse subject",
            key="add_mouse_subject",
            use_container_width=True,
            on_click=add_mouse_subject,
        )

    if completed_subjects:
        st.markdown('<div class="lab-completed-section-title">Completed / Ended</div>', unsafe_allow_html=True)
        for i in completed_subjects:
            render_mouse_row(i, wall_now, finished=True)


show_timers()


# ============================================================
# FOOTER LEGEND
# ============================================================

st.markdown(
    f"""
    <div class="lab-footer">
        <div class="lab-legend-left">
            <span class="lab-legend-item"><span class="lab-legend-dot" style="background:var(--lab-green)"></span>On track</span>
            <span class="lab-legend-item"><span class="lab-legend-dot" style="background:var(--lab-orange)"></span>Needs action</span>
            <span class="lab-legend-item"><span class="lab-legend-dot" style="background:var(--lab-red)"></span>Overdue</span>
            <span class="lab-legend-item"><span class="lab-legend-dot" style="background:var(--lab-gray)"></span>Not started</span>
        </div>
        <div class="lab-legend-center">
            <span>Board {fixed_duration_label(FIXED_BOARD_DURATION)}</span>
            <span>Shock {fixed_duration_label(FIXED_SHOCK_DURATION)}</span>
            <span>Resus {fixed_duration_label(FIXED_RESUSCITATION_DURATION)}</span>
        </div>
        <div class="lab-legend-right">Phase timers mm:ss • total elapsed hh:mm:ss ⓘ</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Reserve space below the final content so the fixed bottom attention banner never covers the last row/footer.
st.markdown('<div style="height:4.35rem;"></div>', unsafe_allow_html=True)
