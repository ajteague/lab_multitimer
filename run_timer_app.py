import base64
import html
import io
import json
import math
import os
import sqlite3
import struct
import threading
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

# ============================================================
# APP SETTINGS — V40 keeps the V39 timing/behavior defaults.
# ============================================================

TIME_UNIT = "minutes"
REFRESH_INTERVAL = 1.0

DEFAULT_INITIAL_ANESTHESIA = 45
DEFAULT_SUBSEQUENT_ANESTHESIA = 30
DEFAULT_ANESTHESIA_DELAY = 5
DEFAULT_NOTIFICATION_SOUND_ENABLED = True
DEFAULT_NOTIFICATION_SOUND = "Chime"
NOTIFICATION_SOUND_OPTIONS = ["Chime", "Beep", "Double beep"]

FIXED_BOARD_DURATION = 10
FIXED_SHOCK_DURATION = 60
FIXED_RESUSCITATION_DURATION = 20

INITIAL_MOUSE_COUNT = 8
WARNING_UNITS = 1
APP_TIMEZONE = "America/New_York"
STATE_VERSION = "lab_multitimer_v40_refined_card_ui"

UNIT_SECONDS = 1.0 if TIME_UNIT == "seconds" else 60.0
UNIT_SHORT = "s" if TIME_UNIT == "seconds" else "m"
UNIT_LABEL = "sec" if TIME_UNIT == "seconds" else "min"

st.set_page_config(
    page_title="Shock Timer",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# V40 VISUAL SYSTEM
# ============================================================

st.markdown(
    r"""
    <style>
    :root {
        --bg0:#07101a; --bg1:#0a1420; --panel:#111d2a; --panel2:#0d1722;
        --border:rgba(137,160,184,.20); --border2:rgba(137,160,184,.30);
        --text:#f4f7fa; --soft:#c5ced8; --muted:#8291a1; --muted2:#647384;
        --green:#5ed276; --blue:#168cff; --orange:#f5a126; --red:#ef6578; --purple:#b87af4;
        --radius:12px; --radius-sm:9px;
    }
    html,body,[data-testid="stAppViewContainer"],.stApp {
        background:radial-gradient(circle at 50% -18%,rgba(37,66,95,.20),transparent 40%),
                   linear-gradient(180deg,var(--bg1) 0%,var(--bg0) 100%)!important;
        color:var(--text)!important;color-scheme:dark;
    }
    [data-testid="stAppViewContainer"]>.main{background:transparent!important}
    [data-testid="stHeader"],[data-testid="stToolbar"],footer{display:none!important}
    .stMainBlockContainer{max-width:100%!important;padding:1.05rem 1.35rem 6rem!important}
    [data-testid="stVerticalBlock"]{gap:.54rem}[data-testid="stHorizontalBlock"]{gap:.68rem}
    h1,h2,h3,h4{color:var(--text)!important;letter-spacing:-.025em}
    [data-testid="stCaptionContainer"]{color:var(--muted)!important}

    .lab-header-title{color:#f7f9fb!important;font-size:1.82rem!important;font-weight:780!important;
        letter-spacing:-.04em!important;line-height:1.04!important}
    .lab-header-subtitle{color:#8290a0!important;font-size:.83rem!important;margin-top:.24rem!important}
    .lab-divider{height:1px!important;margin:.78rem 0 .72rem!important;
        background:linear-gradient(90deg,transparent,rgba(137,160,184,.17) 8%,rgba(137,160,184,.17) 92%,transparent)!important}
    .lab-table-header,.lab-config-header{color:#778696!important;font-size:.63rem!important;font-weight:760!important;
        text-transform:uppercase!important;letter-spacing:.075em!important}

    .stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{
        min-height:2.72rem!important;border-radius:var(--radius-sm)!important;border:1px solid var(--border)!important;
        background:linear-gradient(180deg,rgba(21,34,49,.97),rgba(15,25,37,.97))!important;
        color:#e9eef4!important;font-size:.84rem!important;font-weight:650!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.025)!important;transition:border-color .14s ease,background .14s ease!important}
    .stButton>button:hover,.stDownloadButton>button:hover,[data-testid="stFormSubmitButton"]>button:hover{
        border-color:rgba(152,178,204,.40)!important;background:linear-gradient(180deg,rgba(26,42,60,.98),rgba(17,29,43,.98))!important}
    .stButton>button:disabled,.stDownloadButton>button:disabled{color:rgba(190,201,212,.36)!important;
        border-color:rgba(137,160,184,.10)!important;background:rgba(137,160,184,.025)!important;box-shadow:none!important;opacity:.72!important}
    [data-testid="stBaseButton-primary"]{background:linear-gradient(180deg,#188df4,#0c72d0)!important;
        border-color:#2297ff!important;color:#fff!important;box-shadow:0 7px 18px rgba(10,132,255,.16)!important}

    div[class*="st-key-back_to_experiments"] button,div[class*="st-key-fullscreen_view"] button,
    div[class*="st-key-global_undo_"] button,div[class*="st-key-open_settings"] button,
    div[class*="st-key-export_timesheets"] button,div[class*="st-key-end_all_subjects"] button{
        min-height:3rem!important;font-size:.87rem!important;white-space:nowrap!important}
    div[class*="st-key-end_all_subjects"] button{color:#ffc17e!important;border-color:rgba(245,161,38,.24)!important;
        background:linear-gradient(180deg,rgba(58,37,22,.33),rgba(28,25,24,.26))!important}

    [data-testid="stTextInput"] input,[data-testid="stNumberInput"] input,[data-testid="stTextArea"] textarea,
    [data-baseweb="select"]>div,[data-baseweb="input"]{color:#edf2f6!important;background:#0c1722!important;
        border-color:rgba(137,160,184,.24)!important;border-radius:var(--radius-sm)!important;box-shadow:none!important}
    [data-testid="stTextInput"] input:focus,[data-testid="stNumberInput"] input:focus,[data-testid="stTextArea"] textarea:focus,
    [data-baseweb="select"]>div:focus-within,[data-baseweb="input"]:focus-within{border-color:rgba(137,160,184,.46)!important;
        box-shadow:0 0 0 1px rgba(137,160,184,.10)!important;outline:none!important}
    [data-testid="stWidgetLabel"] p{color:#b7c1cc!important;font-size:.80rem!important;font-weight:620!important}

    [data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--border)!important;border-radius:var(--radius)!important;
        background:linear-gradient(180deg,rgba(18,31,45,.88),rgba(13,23,34,.88))!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.018)!important}
    [data-testid="stForm"]{border-color:rgba(137,160,184,.16)!important;border-radius:var(--radius)!important;background:rgba(11,21,32,.35)!important}
    [data-testid="stDialog"] [role="dialog"],[role="dialog"][aria-modal="true"]{background:linear-gradient(180deg,#111e2b,#0c1722)!important;
        border:1px solid rgba(137,160,184,.24)!important;border-radius:16px!important;box-shadow:0 24px 80px rgba(0,0,0,.48)!important;color:var(--text)!important}
    [data-testid="stDialog"]::backdrop{background:rgba(3,8,14,.60)!important;backdrop-filter:blur(3px)}
    [data-testid="stPopoverBody"],[data-baseweb="popover"]>div,[role="menu"],[data-baseweb="menu"]{
        background:#0d1824!important;border-color:rgba(137,160,184,.24)!important;color:#e8edf2!important;border-radius:11px!important;
        box-shadow:0 18px 48px rgba(0,0,0,.42)!important}
    [role="menuitem"],[data-baseweb="menu"] li{color:#dce4ec!important;border-radius:7px!important}
    [role="menuitem"]:hover,[data-baseweb="menu"] li:hover{background:rgba(137,160,184,.10)!important}
    [data-testid="stExpander"]{border-color:rgba(137,160,184,.18)!important;border-radius:var(--radius-sm)!important;background:rgba(10,19,29,.45)!important}
    [data-testid="stAlert"]{border-radius:var(--radius-sm)!important;border-color:rgba(137,160,184,.18)!important;background:rgba(14,25,37,.90)!important}

    div[class*="st-key-mouse_row_"]{position:relative;overflow:hidden;
        background:radial-gradient(circle at 48% -100%,rgba(78,112,147,.12),transparent 52%),linear-gradient(180deg,rgba(19,32,46,.97),rgba(13,23,34,.97))!important;
        border:1px solid rgba(137,160,184,.18)!important;border-radius:12px!important;padding:.82rem 1.02rem!important;margin-bottom:.18rem!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.022),0 5px 18px rgba(0,0,0,.08)!important}
    div[class*="st-key-mouse_row_"]:has([data-v40-finished="true"]){opacity:.68;background:linear-gradient(180deg,rgba(14,24,35,.90),rgba(10,18,27,.90))!important}
    .v40-row-state{display:none!important}.lab-cell{min-height:5.30rem!important;display:flex!important;flex-direction:column!important;justify-content:center!important;padding:.02rem .04rem!important}
    .lab-mini-label{color:#738293;font-size:.61rem;line-height:1;font-weight:760;letter-spacing:.075em;text-transform:uppercase;margin-bottom:.45rem;white-space:nowrap}
    .lab-mouse-wrap{display:flex!important;align-items:center!important;gap:.58rem!important;min-height:5.30rem!important}
    .lab-mouse-identity{display:flex;align-items:center;min-width:0;gap:.62rem}.lab-mouse-icon{width:2.05rem;height:2.05rem;flex:0 0 auto;display:grid;place-items:center;color:#7190af;opacity:.92}
    .lab-mouse-icon svg{display:block;width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
    .lab-dot{width:.64rem!important;height:.64rem!important;border-radius:50%;flex:0 0 auto;background:var(--muted2)}
    .lab-dot.green{background:var(--green)}.lab-dot.orange{background:var(--orange)}.lab-dot.red{background:var(--red)}.lab-dot.gray{background:#7f8b98}
    .lab-mouse-name{color:#f4f6f8!important;font-size:1.02rem!important;font-weight:750!important;line-height:1.10!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .lab-paused-label{color:#9da9b5!important;font-size:.60rem!important;font-weight:760!important;letter-spacing:.07em!important;text-transform:uppercase!important;margin-bottom:.20rem!important}
    .lab-primary-text{color:#eef2f5!important;font-size:.88rem!important;font-weight:680!important;line-height:1.16!important}
    .lab-primary-text.green{color:#9be5a7!important}.lab-primary-text.orange{color:#ffc169!important}.lab-primary-text.red{color:#ff9cab!important}.lab-primary-text.gray{color:#8d99a6!important}
    .lab-secondary-text{color:#7f8c9a!important;font-size:.70rem!important;line-height:1.18!important;margin-top:.25rem!important}
    .lab-next-caption{color:#dbe2e9;font-size:.82rem;font-weight:650;line-height:1.08;white-space:nowrap}
    .lab-next-time{margin-top:.28rem;color:var(--orange);font-size:1.08rem;line-height:1;font-weight:760;font-variant-numeric:tabular-nums;white-space:nowrap}
    .lab-next-time.red{color:#ff9cab}.lab-next-time.green{color:#9be5a7}.lab-next-time.gray{color:#8d99a6}
    .lab-total{color:#f1f4f7!important;font-size:.91rem!important;font-weight:710!important;font-variant-numeric:tabular-nums;white-space:nowrap}

    .lab-stepper{display:flex!important;align-items:flex-start!important;gap:.10rem!important;width:100%!important;padding:.10rem .08rem 0!important}
    .lab-step{flex:1 1 0!important;min-width:0!important;position:relative!important;text-align:center!important}
    .lab-step:not(:last-child)::after{content:""!important;position:absolute!important;z-index:0!important;top:.69rem!important;left:calc(50% + .78rem)!important;right:calc(-50% + .78rem)!important;height:2px!important;background:rgba(117,137,157,.34)!important;border-radius:999px}
    .lab-step.complete:not(:last-child)::after{background:rgba(94,210,118,.72)!important}
    .lab-step.active:not(:last-child)::after{background:linear-gradient(90deg,rgba(22,140,255,.76) 0 34%,rgba(117,137,157,.34) 34% 100%)!important}
    .lab-step-circle{position:relative!important;z-index:1!important;margin:0 auto!important;width:1.38rem!important;height:1.38rem!important;border-radius:50%!important;display:grid!important;place-items:center!important;font-size:.66rem!important;font-weight:800!important;color:#8996a4!important;border:1.5px solid rgba(137,160,184,.40)!important;background:#101b28!important}
    .lab-step.complete .lab-step-circle{background:rgba(94,210,118,.12)!important;border-color:rgba(94,210,118,.82)!important;color:#78e28d!important}
    .lab-step.active .lab-step-circle{background:rgba(22,140,255,.12)!important;border-color:rgba(22,140,255,.88)!important;color:#5eafff!important}
    .lab-step.action .lab-step-circle{background:rgba(245,161,38,.11)!important;border-color:rgba(245,161,38,.88)!important;color:#ffc169!important}
    .lab-step.overdue .lab-step-circle{background:rgba(239,101,120,.12)!important;border-color:rgba(239,101,120,.88)!important;color:#ff9cab!important}
    .lab-step-label{color:#9ba7b4!important;font-size:.70rem!important;line-height:1.08!important;margin-top:.30rem!important;font-weight:650!important;white-space:nowrap!important}
    .lab-step-time{min-height:.75rem!important;margin-top:.16rem!important;color:#808d9b!important;font-size:.69rem!important;line-height:1.08!important;font-weight:710!important;font-variant-numeric:tabular-nums!important;white-space:nowrap!important}
    .lab-step-time.green{color:#73dc87!important}.lab-step-time.orange{color:#ffc169!important}.lab-step-time.red{color:#ff9cab!important}.lab-step-time.gray{color:#818e9b!important}

    div[class*="st-key-anesthesia_redose_action_"] button,div[class*="st-key-anesthesia_delay_action_"] button{min-height:2.18rem!important;height:2.18rem!important;margin-top:.24rem!important;padding:0 .50rem!important;border-radius:8px!important;font-size:.73rem!important;font-weight:680!important;white-space:nowrap!important}
    div[class*="st-key-anesthesia_redose_action_"] button{color:#ffd49a!important;border-color:rgba(245,161,38,.57)!important;background:rgba(245,161,38,.035)!important}
    div[class*="st-key-anesthesia_delay_action_"] button{color:#d7b8ff!important;border-color:rgba(184,122,244,.55)!important;background:rgba(184,122,244,.035)!important}
    div[class*="st-key-anesthesia_redose_action_"] button:disabled,div[class*="st-key-anesthesia_delay_action_"] button:disabled{color:rgba(177,190,203,.34)!important;border-color:rgba(137,160,184,.10)!important;background:rgba(137,160,184,.018)!important}
    div[class*="st-key-primary_action_"] button{min-height:3.08rem!important;border-color:rgba(245,161,38,.72)!important;color:#fff4e4!important;background:linear-gradient(180deg,rgba(186,115,22,.84),rgba(125,72,10,.84))!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 22px rgba(245,161,38,.10)!important;font-size:.88rem!important;font-weight:720!important}
    div[class*="st-key-primary_start_anesthesia_"] button{background:rgba(245,161,38,.025)!important;border-color:rgba(245,161,38,.75)!important;color:#ffe0ad!important;box-shadow:none!important}
    div[class*="st-key-primary_pause_"] button{min-height:3.08rem!important;border-color:rgba(137,160,184,.28)!important;color:#e7ebef!important;background:rgba(10,18,27,.20)!important;box-shadow:none!important;font-size:.88rem!important;font-weight:680!important}
    div[class*="st-key-mouse_action_menu_"] button{min-height:3.08rem!important;width:100%!important;min-width:2.75rem!important;padding:0 .18rem!important;font-size:1.06rem!important;border-color:rgba(137,160,184,.25)!important;background:rgba(10,18,27,.20)!important}
    div[class*="st-key-add_mouse_card"] button{width:100%!important;min-height:4.30rem!important;border:1px dashed rgba(137,160,184,.29)!important;border-radius:11px!important;background:linear-gradient(180deg,rgba(17,29,42,.44),rgba(11,21,31,.44))!important;color:#e2e8ee!important;font-size:.88rem!important;font-weight:680!important}
    .lab-completed-section-title{color:#7e8c9b!important;font-size:.65rem!important;font-weight:760!important;text-transform:uppercase!important;letter-spacing:.08em!important;border-top:1px solid rgba(137,160,184,.13)!important;margin-top:.70rem!important;padding:.80rem .12rem .15rem!important}

    .st-key-configuration_table [data-testid="stVerticalBlock"]{gap:.16rem!important}.st-key-configuration_table input,.st-key-configuration_table button{min-height:2.35rem!important;height:2.35rem!important}
    div[class*="st-key-delete_exp_confirm_"] button,div[class*="st-key-end_exp_confirm_"] button,div[class*="st-key-end_confirm_"] button,div[class*="st-key-reset_confirm_"] button,div[class*="st-key-end_all_confirm"] button{
        background:linear-gradient(180deg,rgba(185,55,75,.96),rgba(139,38,55,.96))!important;border-color:rgba(239,101,120,.72)!important;color:#fff!important}
    #lab-attention-v40{left:1.35rem!important;right:1.35rem!important;bottom:1rem!important;padding:.72rem .92rem!important;border-radius:11px!important;background:rgba(11,20,30,.97)!important;border:1px solid rgba(245,161,38,.30)!important;box-shadow:0 16px 48px rgba(0,0,0,.36)!important;color:#e8edf2!important;font:650 13px/1.25 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important}
    #lab-attention-v40 .orange{color:#ffc169!important}#lab-attention-v40 .red{color:#ff9cab!important}#lab-attention-v40 .x{color:#99a6b3!important;cursor:pointer;float:right}
    @media(max-width:1180px){.stMainBlockContainer{min-width:1140px}}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# TIME / STATE HELPERS
# ============================================================

def duration_to_seconds(value): return float(value) * UNIT_SECONDS
def warning_seconds(): return duration_to_seconds(WARNING_UNITS)
def rounded_seconds(seconds): return max(0, int(round(float(seconds))))

def format_timer(seconds):
    total = rounded_seconds(seconds); hours, rem = divmod(total, 3600); minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

def format_total_elapsed(seconds):
    total = rounded_seconds(seconds); hours, rem = divmod(total, 3600); minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def format_phase_timer(seconds):
    total = rounded_seconds(seconds); minutes, secs = divmod(total, 60); return f"{minutes:02d}:{secs:02d}"

def fixed_duration_label(value): return f"{value}{UNIT_SHORT}"
def wall_datetime(epoch=None): return datetime.fromtimestamp(float(epoch if epoch is not None else time.time()), ZoneInfo(APP_TIMEZONE))
def elapsed_from(start, now): return 0.0 if start is None else max(0.0, float(now) - float(start))
def remaining_from_start(start, duration_units, now): return None if start is None else float(start) + duration_to_seconds(duration_units) - float(now)

def mouse_defaults(i):
    return {
        f"experiment_start_{i}":None, f"anesthesia_start_{i}":None, f"anesthesia_due_override_{i}":None,
        f"board_start_{i}":None, f"shock_start_{i}":None, f"shock_wallclock_{i}":None, f"resus_start_{i}":None,
        f"paused_{i}":False, f"pause_started_{i}":None, f"ended_{i}":False, f"end_time_{i}":None,
        f"anesthesia_initial_duration_{i}":DEFAULT_INITIAL_ANESTHESIA,
        f"anesthesia_duration_{i}":DEFAULT_SUBSEQUENT_ANESTHESIA,
        f"anesthesia_delay_duration_{i}":DEFAULT_ANESTHESIA_DELAY,
        f"anesthesia_dose_count_{i}":0,
        f"notification_sound_enabled_{i}":DEFAULT_NOTIFICATION_SOUND_ENABLED,
        f"notification_sound_{i}":DEFAULT_NOTIFICATION_SOUND,
        f"event_log_{i}":[], f"subject_name_{i}":f"Mouse {i}", f"mouse_weight_g_{i}":None,
        f"display_order_{i}":i, f"undo_history_{i}":[],
    }

def _copy_value(value):
    if isinstance(value, list): return [dict(x) if isinstance(x, dict) else x for x in value]
    if isinstance(value, dict): return dict(value)
    return value

def initialize_mouse_state(i):
    for key, value in mouse_defaults(i).items(): st.session_state.setdefault(key, _copy_value(value))

def initialize_state():
    st.session_state.setdefault("_state_version", STATE_VERSION)
    st.session_state.setdefault("_mouse_count", INITIAL_MOUSE_COUNT)
    st.session_state.setdefault("_sticky_alerts", {})
    st.session_state.setdefault("_pending_dialog", None)
    st.session_state.setdefault("_needs_full_rerun", False)
    st.session_state.setdefault("_unsaved_subjects", [])
    st.session_state.setdefault("_global_undo_history", [])
    for i in range(1, int(st.session_state["_mouse_count"]) + 1): initialize_mouse_state(i)

def mouse_count(): return int(st.session_state.get("_mouse_count", INITIAL_MOUSE_COUNT))
def subject_name(i): return str(st.session_state.get(f"subject_name_{i}", f"Mouse {i}")).strip() or f"Mouse {i}"
def mouse_weight(i):
    try:
        v=st.session_state.get(f"mouse_weight_g_{i}"); return None if v is None else float(v)
    except (TypeError,ValueError): return None

def weight_label(i):
    v=mouse_weight(i); return "Weight —" if v is None or v <= 0 else f"{v:.1f} g"

def ordered_subject_indices():
    return sorted(range(1,mouse_count()+1), key=lambda i:(float(st.session_state.get(f"display_order_{i}",i)),i))

def is_paused(i): return bool(st.session_state.get(f"paused_{i}",False))
def is_ended(i): return bool(st.session_state.get(f"ended_{i}",False))
def effective_now(i,wall_now):
    if is_ended(i): return st.session_state.get(f"end_time_{i}") or wall_now
    if is_paused(i): return st.session_state.get(f"pause_started_{i}") or wall_now
    return wall_now

# ============================================================
# DATABASE / PERSISTENCE — schema and payload names remain V39-compatible.
# ============================================================

def _configured_database_url():
    env=os.environ.get("SHOCK_TIMER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if env: return str(env).strip()
    try:
        v=st.secrets.get("SHOCK_TIMER_DATABASE_URL") or st.secrets.get("DATABASE_URL"); return str(v).strip() if v else None
    except Exception: return None

DATABASE_URL=_configured_database_url()
DATABASE_KIND="postgres" if DATABASE_URL and DATABASE_URL.startswith(("postgres://","postgresql://")) else "sqlite"
LOCAL_DATABASE_PATH=os.environ.get("SHOCK_TIMER_DB_PATH", str(Path(__file__).resolve().with_name("shock_timer_sessions.db")))

def _adapt_sql(sql): return sql.replace("?","%s") if DATABASE_KIND=="postgres" else sql

def _new_connection():
    if DATABASE_KIND=="postgres":
        try: import psycopg
        except ImportError as exc: raise RuntimeError("PostgreSQL persistence requires psycopg. Add psycopg[binary]>=3.2,<4 to requirements.txt.") from exc
        return psycopg.connect(DATABASE_URL,connect_timeout=10)
    path=Path(LOCAL_DATABASE_PATH); path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(path),timeout=10,check_same_thread=False); conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=FULL"); conn.execute("PRAGMA busy_timeout=10000"); return conn

@st.cache_resource(show_spinner=False)
def _db_resource(): return {"conn":_new_connection(),"lock":threading.RLock()}

def _run_db(operation):
    resource=_db_resource()
    with resource["lock"]:
        for attempt in range(2):
            conn=resource["conn"]
            try:
                result=operation(conn); conn.commit(); return result
            except Exception:
                try: conn.rollback()
                except Exception: pass
                if attempt==0:
                    try: conn.close()
                    except Exception: pass
                    resource["conn"]=_new_connection(); continue
                raise

def _db_execute(sql,params=()):
    def op(conn):
        cur=conn.cursor(); cur.execute(_adapt_sql(sql),params); return cur.rowcount
    return _run_db(op)

def _db_execute_many(statements):
    def op(conn):
        cur=conn.cursor()
        for sql,params in statements: cur.execute(_adapt_sql(sql),params)
        return True
    return _run_db(op)

def _db_query(sql,params=()):
    def op(conn):
        cur=conn.cursor(); cur.execute(_adapt_sql(sql),params); names=[x[0] for x in cur.description]; return [dict(zip(names,row)) for row in cur.fetchall()]
    return _run_db(op)

@st.cache_resource(show_spinner=False)
def initialize_database():
    _db_execute_many([
        ("""CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY,name TEXT NOT NULL,mouse_count INTEGER NOT NULL,created_at DOUBLE PRECISION NOT NULL,updated_at DOUBLE PRECISION NOT NULL,completed_at DOUBLE PRECISION)""",()),
        ("""CREATE TABLE IF NOT EXISTS subjects (experiment_id TEXT NOT NULL,mouse_index INTEGER NOT NULL,state_json TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL,PRIMARY KEY (experiment_id,mouse_index))""",()),
        ("CREATE INDEX IF NOT EXISTS idx_experiments_updated_at ON experiments(updated_at)",()),
    ])
    try: _db_query("SELECT completed_at FROM experiments LIMIT 1")
    except Exception:
        try: _db_execute("ALTER TABLE experiments ADD COLUMN completed_at DOUBLE PRECISION")
        except Exception: pass
    return True

initialize_database()

def _default_subject_payload(i): return {k:_copy_value(v) for k,v in mouse_defaults(i).items()}
def _subject_payload(i): return {k:_copy_value(st.session_state.get(k,v)) for k,v in mouse_defaults(i).items()}
def _load_subject_payload(i,payload):
    merged=_default_subject_payload(i)
    if isinstance(payload,dict):
        for k,v in payload.items():
            if k in merged: merged[k]=v
    for k,v in merged.items(): st.session_state[k]=_copy_value(v)

def create_experiment_record(name,configured_mice):
    name=(name or "").strip()
    if not name: raise ValueError("Experiment name cannot be blank.")
    if not configured_mice: raise ValueError("At least one mouse is required.")
    exp_id=uuid.uuid4().hex; now=time.time(); statements=[("INSERT INTO experiments(id,name,mouse_count,created_at,updated_at,completed_at) VALUES(?,?,?,?,?,NULL)",(exp_id,name,len(configured_mice),now,now))]
    for i,mouse in enumerate(configured_mice,start=1):
        p=_default_subject_payload(i); p[f"subject_name_{i}"]=str(mouse["name"]).strip() or f"Mouse {i}"; p[f"mouse_weight_g_{i}"]=round(float(mouse["weight_g"]),1); p[f"display_order_{i}"]=i
        statements.append(("INSERT INTO subjects(experiment_id,mouse_index,state_json,updated_at) VALUES(?,?,?,?)",(exp_id,i,json.dumps(p,separators=(",",":")),now)))
    _db_execute_many(statements); return exp_id

def list_experiment_records(): return _db_query("SELECT id,name,mouse_count,created_at,updated_at,completed_at FROM experiments ORDER BY CASE WHEN completed_at IS NULL THEN 0 ELSE 1 END,updated_at DESC,created_at DESC")
def get_experiment_record(exp_id):
    rows=_db_query("SELECT id,name,mouse_count,created_at,updated_at,completed_at FROM experiments WHERE id=?",(exp_id,)); return rows[0] if rows else None
def get_subject_records(exp_id): return _db_query("SELECT mouse_index,state_json,updated_at FROM subjects WHERE experiment_id=? ORDER BY mouse_index",(exp_id,))

def load_experiment_into_session(exp_id):
    exp=get_experiment_record(exp_id)
    if not exp: return False
    rows=get_subject_records(exp_id); st.session_state.clear(); st.session_state["_state_version"]=STATE_VERSION; st.session_state["_active_experiment_id"]=str(exp_id); st.session_state["_active_experiment_name"]=str(exp["name"]); st.session_state["_mouse_count"]=int(exp["mouse_count"]); st.session_state["_sticky_alerts"]={}; st.session_state["_pending_dialog"]=None; st.session_state["_needs_full_rerun"]=False; st.session_state["_unsaved_subjects"]=[]; st.session_state["_global_undo_history"]=[]; st.session_state["_db_experiment_updated"]=float(exp["updated_at"])
    by_index={int(r["mouse_index"]):r for r in rows}
    for i in range(1,int(exp["mouse_count"])+1):
        row=by_index.get(i); payload={}
        if row:
            try: payload=json.loads(row["state_json"])
            except Exception: payload={}
            st.session_state[f"_db_subject_updated_{i}"]=float(row["updated_at"])
        _load_subject_payload(i,payload)
    initialize_state(); return True

def _mark_storage_failure(indices,exc):
    pending=set(st.session_state.get("_unsaved_subjects",[])); pending.update(int(i) for i in indices); st.session_state["_unsaved_subjects"]=sorted(pending); st.session_state["_storage_error"]=str(exc)

def _bulk_update_subject_payloads(exp_id,payloads,now,completed_at=None):
    items=sorted((int(i),p) for i,p in payloads.items())
    if not items: return True
    statements=[("UPDATE subjects SET state_json=?,updated_at=? WHERE experiment_id=? AND mouse_index=?",(json.dumps(p,separators=(",",":")),now,exp_id,i)) for i,p in items]
    if completed_at is None: statements.append(("UPDATE experiments SET updated_at=? WHERE id=?",(now,exp_id)))
    else: statements.append(("UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",(completed_at,now,exp_id)))
    _db_execute_many(statements); return True

def persist_subjects(indices):
    exp_id=st.session_state.get("_active_experiment_id")
    if not exp_id: return False
    indices=sorted({int(i) for i in indices}); now=time.time(); payloads={i:_subject_payload(i) for i in indices}
    try: _bulk_update_subject_payloads(exp_id,payloads,now)
    except Exception as exc: _mark_storage_failure(indices,exc); return False
    for i in indices: st.session_state[f"_db_subject_updated_{i}"]=now
    st.session_state["_db_experiment_updated"]=now; pending=set(st.session_state.get("_unsaved_subjects",[])); pending.difference_update(indices); st.session_state["_unsaved_subjects"]=sorted(pending)
    if not pending: st.session_state.pop("_storage_error",None)
    return True

def persist_subject(i): return persist_subjects([i])
def retry_unsaved_subjects():
    pending=list(st.session_state.get("_unsaved_subjects",[]))
    if pending: persist_subjects(pending)

def rename_experiment_record(exp_id,new_name):
    new_name=(new_name or "").strip()
    if not new_name: return False
    _db_execute("UPDATE experiments SET name=?,updated_at=? WHERE id=?",(new_name,time.time(),exp_id)); return True

def delete_experiment_record(exp_id): _db_execute_many([("DELETE FROM subjects WHERE experiment_id=?",(exp_id,)),("DELETE FROM experiments WHERE id=?",(exp_id,))])

def _append_payload_event(payload,i,event_name,details,epoch):
    key=f"event_log_{i}"; log=list(payload.get(key,[])); log.append({"_id":uuid.uuid4().hex,"Event":event_name,"Absolute time":wall_datetime(epoch).strftime("%Y-%m-%d %H:%M:%S"),"Details":details,"_epoch":float(epoch)}); payload[key]=log

def end_experiment_record(exp_id):
    rows=get_subject_records(exp_id); now=time.time(); payloads={}
    for row in rows:
        i=int(row["mouse_index"])
        try: p=json.loads(row["state_json"])
        except Exception: p=_default_subject_payload(i)
        if not bool(p.get(f"ended_{i}",False)):
            p[f"ended_{i}"]=True; p[f"end_time_{i}"]=p.get(f"pause_started_{i}") or now; p[f"paused_{i}"]=False; p[f"pause_started_{i}"]=None; _append_payload_event(p,i,"Experiment ended","Ended from experiment management",now)
        payloads[i]=p
    _bulk_update_subject_payloads(exp_id,payloads,now,completed_at=now)

def maybe_mark_experiment_complete():
    if not all(is_ended(i) for i in range(1,mouse_count()+1)): return
    exp_id=st.session_state.get("_active_experiment_id")
    if exp_id:
        now=time.time(); _db_execute("UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",(now,now,exp_id))

# ============================================================
# EVENT LOG / TIMESHEETS
# ============================================================

def log_event(i,event_name,details="",when_epoch=None):
    epoch=float(when_epoch if when_epoch is not None else time.time()); key=f"event_log_{i}"; log=list(st.session_state.get(key,[])); entry={"_id":uuid.uuid4().hex,"Event":str(event_name),"Absolute time":wall_datetime(epoch).strftime("%Y-%m-%d %H:%M:%S"),"Details":str(details or ""),"_epoch":epoch}; log.append(entry); st.session_state[key]=log; return entry

def event_epoch(entry):
    try:
        if entry.get("_epoch") is not None: return float(entry["_epoch"])
    except (TypeError,ValueError): pass
    absolute=str(entry.get("Absolute time","")).strip()
    if not absolute: return None
    try: return datetime.strptime(absolute,"%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(APP_TIMEZONE)).timestamp()
    except ValueError: return None

def _format_relative(seconds):
    sign="-" if seconds<0 else "+"; seconds=abs(seconds); return sign+format_total_elapsed(seconds)

def relative_time_map(i,log):
    base=st.session_state.get(f"experiment_start_{i}")
    epochs=[event_epoch(e) for e in log if event_epoch(e) is not None]
    if base is None and epochs: base=min(epochs)
    result={}
    for order,e in enumerate(log):
        ep=event_epoch(e); value="—" if ep is None or base is None else _format_relative(ep-float(base)); key=e.get("_id") or f"__order_{order}"; result[key]=value
    return result

def is_backtime_editable_event(entry): return entry.get("Event") in {"Anesthesia started","Anesthesia redosed","Board acclimation started","Shock started","Resuscitation started"}

def backtime_start_event(i,event_id,minutes):
    try: minutes=float(minutes)
    except (TypeError,ValueError): return False,"Enter a valid number of minutes."
    if minutes<=0: return False,"Back-time must be greater than 0 minutes."
    key=f"event_log_{i}"; log=list(st.session_state.get(key,[])); idx=next((n for n,e in enumerate(log) if e.get("_id")==event_id),None)
    if idx is None: return False,"That event could not be found."
    entry=dict(log[idx])
    if not is_backtime_editable_event(entry): return False,"That event is not a timer start and cannot be back-timed here."
    old=event_epoch(entry)
    if old is None: return False,"The saved event time could not be parsed."
    new=old-minutes*60.0; name=entry.get("Event"); _record_global_undo(f"Back-time {name} — {subject_name(i)}",[i]); entry["_epoch"]=new; entry["Absolute time"]=wall_datetime(new).strftime("%Y-%m-%d %H:%M:%S"); log[idx]=entry; st.session_state[key]=log
    if name=="Board acclimation started": st.session_state[f"board_start_{i}"]=new
    elif name=="Shock started": st.session_state[f"shock_start_{i}"]=new; st.session_state[f"shock_wallclock_{i}"]=wall_datetime(new).strftime("%H:%M:%S")
    elif name=="Resuscitation started": st.session_state[f"resus_start_{i}"]=new
    elif name in ("Anesthesia started","Anesthesia redosed"):
        ae=[x for x in log if x.get("Event") in ("Anesthesia started","Anesthesia redosed")]
        if ae and ae[-1].get("_id")==event_id: st.session_state[f"anesthesia_start_{i}"]=new
        if name=="Anesthesia started":
            cur=st.session_state.get(f"experiment_start_{i}")
            if cur is None or new<float(cur): st.session_state[f"experiment_start_{i}"]=new
    log_event(i,"Time correction",f"{name} moved {minutes:g} min earlier"); persist_subject(i); clear_mouse_alerts(i); st.session_state["_needs_full_rerun"]=True; return True,None

def build_all_timesheets_text():
    lines=["Shock Timer - Aggregated Timesheets",f"Experiment: {st.session_state.get('_active_experiment_name','')}",f"Timezone: {APP_TIMEZONE}",f"Exported: {wall_datetime().strftime('%Y-%m-%d %H:%M:%S')}",""]
    for i in ordered_subject_indices():
        lines += ["="*96,f"{subject_name(i)} (Mouse {i}; {weight_label(i)})","="*96]; log=list(st.session_state.get(f"event_log_{i}",[])); rel=relative_time_map(i,log)
        if not log: lines.append("No events recorded.")
        else: lines += ["Relative time | Absolute time        | Event | Details","-"*96]
        for order,e in enumerate(log):
            r=rel.get(e.get("_id"),rel.get(f"__order_{order}","—")); line=f"{r:>13} | {e.get('Absolute time','')} | {e.get('Event','')}"; details=str(e.get("Details","")).strip(); lines.append(line+(f" | {details}" if details else ""))
        lines.append("")
    return "\n".join(lines).rstrip()+"\n"

# ============================================================
# ALERT / TIMER CORE / UNDO
# ============================================================

def alert_key(i,event): return f"{i}:{event}"
def clear_alert(i,event): st.session_state.get("_sticky_alerts",{}).pop(alert_key(i,event),None)
def clear_mouse_alerts(i):
    alerts=st.session_state.get("_sticky_alerts",{}); prefix=f"{i}:"
    for key in list(alerts):
        if key.startswith(prefix): alerts.pop(key,None)
def mouse_is_running(i): return not is_paused(i) and not is_ended(i)
def ensure_experiment_started(i,timestamp):
    if st.session_state.get(f"experiment_start_{i}") is None: st.session_state[f"experiment_start_{i}"]=float(timestamp)
def anesthesia_dose_count(i): return int(st.session_state.get(f"anesthesia_dose_count_{i}",0) or 0)
def current_anesthesia_interval(i): return st.session_state.get(f"anesthesia_initial_duration_{i}",DEFAULT_INITIAL_ANESTHESIA) if anesthesia_dose_count(i)<=1 else st.session_state.get(f"anesthesia_duration_{i}",DEFAULT_SUBSEQUENT_ANESTHESIA)
def anesthesia_due_time(i):
    override=st.session_state.get(f"anesthesia_due_override_{i}")
    if override is not None: return float(override)
    start=st.session_state.get(f"anesthesia_start_{i}"); return None if start is None else float(start)+duration_to_seconds(current_anesthesia_interval(i))
def anesthesia_remaining(i,now):
    due=anesthesia_due_time(i); return None if due is None else due-float(now)
def board_is_complete(i,now):
    s=st.session_state.get(f"board_start_{i}"); return s is not None and remaining_from_start(s,FIXED_BOARD_DURATION,now)<=0
def shock_is_complete(i,now):
    s=st.session_state.get(f"shock_start_{i}"); return s is not None and remaining_from_start(s,FIXED_SHOCK_DURATION,now)<=0
def resus_is_complete(i,now):
    s=st.session_state.get(f"resus_start_{i}"); return s is not None and remaining_from_start(s,FIXED_RESUSCITATION_DURATION,now)<=0

def _record_global_undo(label,indices):
    unique=sorted({int(i) for i in indices if 1<=int(i)<=mouse_count()})
    if not unique: return
    history=list(st.session_state.get("_global_undo_history",[])); history.append({"token":uuid.uuid4().hex,"label":str(label),"created_at":time.time(),"subjects":{str(i):_subject_payload(i) for i in unique}}); st.session_state["_global_undo_history"]=history[-50:]; st.session_state["_needs_full_rerun"]=True

def global_undo_available(): return bool(st.session_state.get("_global_undo_history",[]))
def global_undo_label():
    h=st.session_state.get("_global_undo_history",[]); return str(h[-1].get("label","last action")) if h else None
def global_undo_token():
    h=st.session_state.get("_global_undo_history",[])
    if not h: return "empty"
    x=h[-1]; return str(x.get("token") or x.get("created_at") or "legacy")

def _merge_audit_log_after_restore(current,restored):
    current=[dict(x) for x in (current or [])]; restored=[dict(x) for x in (restored or [])]; rb={str(x.get("_id")):x for x in restored if x.get("_id")}; merged=[]; seen=set()
    for x in current:
        eid=x.get("_id")
        if eid and str(eid) in rb: merged.append(dict(rb[str(eid)])); seen.add(str(eid))
        else: merged.append(dict(x)); seen.add(str(eid)) if eid else None
    for x in restored:
        eid=x.get("_id")
        if eid and str(eid) not in seen: merged.append(dict(x)); seen.add(str(eid))
    return merged

def _sync_experiment_completion_from_session():
    exp_id=st.session_state.get("_active_experiment_id")
    if not exp_id: return
    now=time.time()
    if all(is_ended(i) for i in range(1,mouse_count()+1)): _db_execute("UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",(now,now,exp_id))
    else: _db_execute("UPDATE experiments SET completed_at=NULL,updated_at=? WHERE id=?",(now,exp_id))

def global_undo_last_action():
    history=list(st.session_state.get("_global_undo_history",[]))
    if not history: return False
    item=history.pop(); st.session_state["_global_undo_history"]=history; restored=[]; label=str(item.get("label","last action"))
    for k,payload in item.get("subjects",{}).items():
        try: i=int(k)
        except Exception: continue
        if not 1<=i<=mouse_count(): continue
        current=list(st.session_state.get(f"event_log_{i}",[])); old=list(payload.get(f"event_log_{i}",[])) if isinstance(payload,dict) else []; _load_subject_payload(i,payload); st.session_state[f"event_log_{i}"]=_merge_audit_log_after_restore(current,old); log_event(i,"Undo",f"Global undo: {label}"); clear_mouse_alerts(i); restored.append(i)
    if not restored: return False
    persist_subjects(restored); _sync_experiment_completion_from_session(); st.session_state["_needs_full_rerun"]=True; st.toast(f"Undid: {label}"); return True

def _push_undo(i,action,event_entry,snapshot=None):
    key=f"undo_history_{i}"; h=list(st.session_state.get(key,[])); item={"action":action,"event_id":event_entry.get("_id"),"created_at":time.time()};
    if snapshot is not None: item["snapshot"]=snapshot
    h.append(item); st.session_state[key]=h[-20:]
def _undo_label(action): return {"anesthesia_redose":"Anesthesia redose","start_board":"Start board","start_shock":"Start shock","start_resus":"Start resus"}.get(action,"last stage action")
def latest_undo_action(i):
    h=st.session_state.get(f"undo_history_{i}",[]); return h[-1].get("action") if h else None

def undo_last_stage_action(i):
    if is_ended(i): return False
    key=f"undo_history_{i}"; h=list(st.session_state.get(key,[]))
    if not h: return False
    item=h[-1]; action=item.get("action")
    if action=="start_shock" and st.session_state.get(f"resus_start_{i}") is not None: return False
    if action=="start_board" and st.session_state.get(f"shock_start_{i}") is not None: return False
    if action not in {"anesthesia_redose","start_resus","start_shock","start_board"}: return False
    _record_global_undo(f"Undo {_undo_label(action)} — {subject_name(i)}",[i]); h.pop()
    if action=="anesthesia_redose":
        s=item.get("snapshot") or {}; st.session_state[f"anesthesia_start_{i}"]=s.get("anesthesia_start"); st.session_state[f"anesthesia_due_override_{i}"]=s.get("anesthesia_due_override"); st.session_state[f"anesthesia_dose_count_{i}"]=int(s.get("anesthesia_dose_count",1))
    elif action=="start_resus": st.session_state[f"resus_start_{i}"]=None
    elif action=="start_shock": st.session_state[f"shock_start_{i}"]=None; st.session_state[f"shock_wallclock_{i}"]=None
    elif action=="start_board": st.session_state[f"board_start_{i}"]=None
    st.session_state[key]=h; clear_mouse_alerts(i); log_event(i,"Undo",f"Reverted {_undo_label(action)}"); persist_subject(i); st.session_state["_needs_full_rerun"]=True; return True

def start_or_redose_anesthesia(i):
    if not mouse_is_running(i): return
    now=time.time(); previous=st.session_state.get(f"anesthesia_start_{i}"); first=previous is None; _record_global_undo(f"{'Start anesthesia' if first else 'Anesthesia redose'} — {subject_name(i)}",[i]); snap=None
    if not first: snap={"anesthesia_start":previous,"anesthesia_due_override":st.session_state.get(f"anesthesia_due_override_{i}"),"anesthesia_dose_count":anesthesia_dose_count(i)}
    ensure_experiment_started(i,now); st.session_state[f"anesthesia_start_{i}"]=now; st.session_state[f"anesthesia_due_override_{i}"]=None; st.session_state[f"anesthesia_dose_count_{i}"]=1 if first else anesthesia_dose_count(i)+1; event=log_event(i,"Anesthesia started" if first else "Anesthesia redosed",when_epoch=now)
    if not first: _push_undo(i,"anesthesia_redose",event,snapshot=snap)
    clear_alert(i,"Anesthesia redose"); persist_subject(i)

def delay_anesthesia_reminder(i):
    if not mouse_is_running(i) or st.session_state.get(f"anesthesia_start_{i}") is None: return
    now=time.time(); delay=st.session_state[f"anesthesia_delay_duration_{i}"]; _record_global_undo(f"Delay anesthesia reminder — {subject_name(i)}",[i]); st.session_state[f"anesthesia_due_override_{i}"]=now+duration_to_seconds(delay); log_event(i,"Anesthesia reminder delayed",f"+{delay}{UNIT_SHORT} from button press",now); clear_alert(i,"Anesthesia redose"); persist_subject(i)

def start_board(i):
    if not mouse_is_running(i) or st.session_state.get(f"anesthesia_start_{i}") is None or st.session_state.get(f"board_start_{i}") is not None: return
    now=time.time(); _record_global_undo(f"Start board — {subject_name(i)}",[i]); ensure_experiment_started(i,now); st.session_state[f"board_start_{i}"]=now; event=log_event(i,"Board acclimation started",when_epoch=now); _push_undo(i,"start_board",event); persist_subject(i)

def start_shock(i,force=False):
    if not mouse_is_running(i): return
    now=time.time()
    if st.session_state.get(f"shock_start_{i}") is not None or st.session_state.get(f"board_start_{i}") is None or (not force and not board_is_complete(i,now)): return
    _record_global_undo(f"{'Force start shock' if force else 'Start shock'} — {subject_name(i)}",[i]); ensure_experiment_started(i,now); st.session_state[f"shock_start_{i}"]=now; st.session_state[f"shock_wallclock_{i}"]=wall_datetime(now).strftime("%H:%M:%S"); event=log_event(i,"Shock started","Forced advance before board acclimation completed" if force else "",when_epoch=now); _push_undo(i,"start_shock",event); clear_alert(i,"Shock"); persist_subject(i)

def start_resuscitation(i,force=False):
    if not mouse_is_running(i): return
    now=time.time()
    if st.session_state.get(f"resus_start_{i}") is not None or st.session_state.get(f"shock_start_{i}") is None or (not force and not shock_is_complete(i,now)): return
    _record_global_undo(f"{'Force start resus' if force else 'Start resus'} — {subject_name(i)}",[i]); st.session_state[f"resus_start_{i}"]=now; event=log_event(i,"Resuscitation started","Forced advance before shock completed" if force else "",when_epoch=now); _push_undo(i,"start_resus",event); clear_alert(i,"Resuscitation"); persist_subject(i)

def toggle_pause(i):
    if is_ended(i): return
    now=time.time(); _record_global_undo(f"{'Resume' if is_paused(i) else 'Pause'} — {subject_name(i)}",[i])
    if not is_paused(i):
        st.session_state[f"paused_{i}"]=True; st.session_state[f"pause_started_{i}"]=now; log_event(i,"Paused",when_epoch=now)
    else:
        started=st.session_state.get(f"pause_started_{i}") or now; delta=max(0,now-float(started))
        for field in ("experiment_start","anesthesia_start","board_start","shock_start","resus_start","anesthesia_due_override"):
            key=f"{field}_{i}"; value=st.session_state.get(key)
            if value is not None: st.session_state[key]=float(value)+delta
        st.session_state[f"paused_{i}"]=False; st.session_state[f"pause_started_{i}"]=None; log_event(i,"Resumed",f"Paused {format_timer(delta)}",when_epoch=now)
    clear_mouse_alerts(i); persist_subject(i)

def end_mouse(i,forced=False):
    if is_ended(i): return False
    now=time.time(); _record_global_undo(f"{'Force end subject' if forced else 'End subject'} — {subject_name(i)}",[i]); end_at=st.session_state.get(f"pause_started_{i}") or now; st.session_state[f"ended_{i}"]=True; st.session_state[f"end_time_{i}"]=end_at; st.session_state[f"paused_{i}"]=False; st.session_state[f"pause_started_{i}"]=None; clear_mouse_alerts(i); log_event(i,"Experiment ended","Forced advance before resuscitation completed" if forced else "",when_epoch=now); persist_subject(i); maybe_mark_experiment_complete(); return True

def reset_mouse(i):
    _record_global_undo(f"Reset subject — {subject_name(i)}",[i]); name=subject_name(i); weight=mouse_weight(i); order=st.session_state.get(f"display_order_{i}",i); init=st.session_state.get(f"anesthesia_initial_duration_{i}",DEFAULT_INITIAL_ANESTHESIA); sub=st.session_state.get(f"anesthesia_duration_{i}",DEFAULT_SUBSEQUENT_ANESTHESIA); delay=st.session_state.get(f"anesthesia_delay_duration_{i}",DEFAULT_ANESTHESIA_DELAY); snd=st.session_state.get(f"notification_sound_{i}",DEFAULT_NOTIFICATION_SOUND); enabled=st.session_state.get(f"notification_sound_enabled_{i}",DEFAULT_NOTIFICATION_SOUND_ENABLED)
    for k,v in mouse_defaults(i).items(): st.session_state[k]=_copy_value(v)
    st.session_state[f"subject_name_{i}"]=name; st.session_state[f"mouse_weight_g_{i}"]=weight; st.session_state[f"display_order_{i}"]=order; st.session_state[f"anesthesia_initial_duration_{i}"]=init; st.session_state[f"anesthesia_duration_{i}"]=sub; st.session_state[f"anesthesia_delay_duration_{i}"]=delay; st.session_state[f"notification_sound_{i}"]=snd; st.session_state[f"notification_sound_enabled_{i}"]=enabled; clear_mouse_alerts(i); persist_subject(i); _sync_experiment_completion_from_session()

def end_all_subjects_current_experiment():
    targets=[i for i in ordered_subject_indices() if not is_ended(i)]
    if not targets: return True
    _record_global_undo("End all subjects",targets); now=time.time()
    for i in targets:
        st.session_state[f"ended_{i}"]=True; st.session_state[f"end_time_{i}"]=st.session_state.get(f"pause_started_{i}") or now; st.session_state[f"paused_{i}"]=False; st.session_state[f"pause_started_{i}"]=None; clear_mouse_alerts(i); log_event(i,"Experiment ended","Ended with End all subjects",when_epoch=now)
    ok=persist_subjects(targets)
    if ok:
        exp_id=st.session_state.get("_active_experiment_id")
        if exp_id: _db_execute("UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",(now,now,exp_id))
    return ok

# ============================================================
# PROFILE / ADD / REORDER
# ============================================================

def weight_requires_confirmation(weight):
    try: value=float(weight)
    except (TypeError,ValueError): return False
    return not (20.0 < value < 40.0)

def validate_mouse_name_weight(name,weight,default_name="Mouse"):
    name=(name or "").strip()
    if not name: return None,None,"Mouse name cannot be blank."
    try: weight=float(weight)
    except (TypeError,ValueError): return None,None,"Enter a valid mouse weight."
    if weight<=0: return None,None,"Mouse weight must be greater than 0 g."
    return name or default_name,round(weight,1),None

def queue_weight_warning(context,entries,**extra): st.session_state["_pending_weight_warning"]={"context":context,"entries":entries,**extra}

def save_subject_profile(i,name,weight):
    name=(name or "").strip()
    if not name: return False,"Subject name cannot be blank."
    try: weight=float(weight)
    except (TypeError,ValueError): return False,"Enter a valid weight."
    if weight<=0: return False,"Weight must be greater than 0 g."
    st.session_state[f"subject_name_{i}"]=name; st.session_state[f"mouse_weight_g_{i}"]=round(weight,1); persist_subject(i); return True,None

def create_mouse_subject(name,weight):
    exp_id=st.session_state.get("_active_experiment_id")
    if not exp_id: return False,"No active experiment."
    name=(name or "").strip()
    try: weight=float(weight)
    except (TypeError,ValueError): return False,"Enter a valid mouse weight."
    if not name or weight<=0: return False,"Enter a mouse name and weight greater than 0 g."
    new_i=mouse_count()+1; st.session_state["_mouse_count"]=new_i; initialize_mouse_state(new_i); st.session_state[f"subject_name_{new_i}"]=name; st.session_state[f"mouse_weight_g_{new_i}"]=round(weight,1)
    if new_i>1:
        source=ordered_subject_indices()[0]
        for field,default in (("anesthesia_initial_duration",DEFAULT_INITIAL_ANESTHESIA),("anesthesia_duration",DEFAULT_SUBSEQUENT_ANESTHESIA),("anesthesia_delay_duration",DEFAULT_ANESTHESIA_DELAY),("notification_sound_enabled",DEFAULT_NOTIFICATION_SOUND_ENABLED),("notification_sound",DEFAULT_NOTIFICATION_SOUND)):
            st.session_state[f"{field}_{new_i}"]=st.session_state.get(f"{field}_{source}",default)
    existing=[float(st.session_state.get(f"display_order_{j}",j)) for j in range(1,new_i)]; st.session_state[f"display_order_{new_i}"]=max(existing)+1 if existing else 1; now=time.time()
    try: _db_execute_many([("INSERT INTO subjects(experiment_id,mouse_index,state_json,updated_at) VALUES(?,?,?,?)",(exp_id,new_i,json.dumps(_subject_payload(new_i),separators=(",",":")),now)),("UPDATE experiments SET mouse_count=?,updated_at=? WHERE id=?",(new_i,now,exp_id))])
    except Exception as exc: _mark_storage_failure([new_i],exc); return False,str(exc)
    st.session_state["_needs_full_rerun"]=True; return True,None

def mouse_is_complete(i,now):
    if is_ended(i): return True
    s=st.session_state.get(f"resus_start_{i}"); return s is not None and remaining_from_start(s,FIXED_RESUSCITATION_DURATION,now)<=0

def _reorder_group(i,now): return "completed" if mouse_is_complete(i,effective_now(i,now)) else "active"
def move_subject(i,direction):
    now=time.time(); group=_reorder_group(i,now); peers=[j for j in ordered_subject_indices() if _reorder_group(j,now)==group]
    if i not in peers: return False
    pos=peers.index(i); target=pos+int(direction)
    if target<0 or target>=len(peers): return False
    other=peers[target]; _record_global_undo(f"Reorder subjects — {subject_name(i)}",[i,other]); a=float(st.session_state.get(f"display_order_{i}",i)); b=float(st.session_state.get(f"display_order_{other}",other)); st.session_state[f"display_order_{i}"]=b; st.session_state[f"display_order_{other}"]=a; persist_subjects([i,other]); st.session_state["_needs_full_rerun"]=True; return True

# ============================================================
# NEW EXPERIMENT CONFIGURATION / HOME
# ============================================================

def _clear_configuration():
    for key in list(st.session_state):
        if key.startswith("_cfg_name_") or key.startswith("_cfg_weight_"): st.session_state.pop(key,None)
    for key in ("_configuration_draft","_configuration_experiment_name","_show_configuration_dialog","_configuration_error"): st.session_state.pop(key,None)

def _new_draft_mouse(number): return {"draft_id":uuid.uuid4().hex,"name":f"Mouse {number}","weight_g":0.0}

def begin_experiment_configuration(experiment_name,subject_count):
    name=(experiment_name or "").strip()
    if not name: st.session_state["_home_error"]="Enter an experiment name."; return
    try: count=max(1,min(64,int(subject_count)))
    except Exception: count=INITIAL_MOUSE_COUNT
    _clear_configuration(); st.session_state["_configuration_experiment_name"]=name; st.session_state["_configuration_draft"]=[_new_draft_mouse(i) for i in range(1,count+1)]; st.session_state["_show_configuration_dialog"]=True

def _sync_cfg_from_widgets():
    draft=list(st.session_state.get("_configuration_draft",[])); updated=[]
    for row in draft:
        did=row["draft_id"]; updated.append({"draft_id":did,"name":str(st.session_state.get(f"_cfg_name_{did}",row.get("name",""))),"weight_g":float(st.session_state.get(f"_cfg_weight_{did}",row.get("weight_g",0.0)) or 0.0)})
    st.session_state["_configuration_draft"]=updated; return updated

@st.dialog("Configure experiment",width="large")
def configure_experiment_dialog():
    name=st.session_state.get("_configuration_experiment_name",""); st.markdown(f"### {html.escape(name)}",unsafe_allow_html=True); st.caption("Confirm each mouse name and weight before starting the experiment.")
    draft=list(st.session_state.get("_configuration_draft",[]))
    with st.container(key="configuration_table"):
        hdr=st.columns([.6,3.4,1.5,.55]);
        for col,label in zip(hdr,["#","Mouse name","Weight (g)",""]):
            with col: st.markdown(f'<div class="lab-config-header">{label}</div>',unsafe_allow_html=True)
        remove=None
        for idx,row in enumerate(draft,start=1):
            did=row["draft_id"]; nk=f"_cfg_name_{did}"; wk=f"_cfg_weight_{did}"; st.session_state.setdefault(nk,row.get("name",f"Mouse {idx}")); st.session_state.setdefault(wk,float(row.get("weight_g",0.0))); cols=st.columns([.6,3.4,1.5,.55],vertical_alignment="center")
            with cols[0]: st.markdown(f"**{idx}**")
            with cols[1]: st.text_input("Name",key=nk,label_visibility="collapsed")
            with cols[2]: st.number_input("Weight",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk,label_visibility="collapsed")
            with cols[3]:
                if len(draft)>1 and st.button("×",key=f"cfg_remove_{did}",use_container_width=True): remove=did
        if remove:
            _sync_cfg_from_widgets(); st.session_state["_configuration_draft"]=[r for r in st.session_state["_configuration_draft"] if r["draft_id"]!=remove]; st.rerun()
    if st.button("+ Add mouse",key="cfg_add_mouse",use_container_width=True):
        current=_sync_cfg_from_widgets(); current.append(_new_draft_mouse(len(current)+1)); st.session_state["_configuration_draft"]=current; st.rerun()
    error=st.session_state.pop("_configuration_error",None)
    if error: st.error(error)
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="cfg_cancel",use_container_width=True): _clear_configuration(); st.rerun()
    with right:
        if st.button("Start experiment",key="cfg_start",use_container_width=True,type="primary"):
            current=_sync_cfg_from_widgets(); configured=[]; errors=[]
            for idx,row in enumerate(current,start=1):
                n,w,e=validate_mouse_name_weight(row.get("name"),row.get("weight_g"),f"Mouse {idx}")
                if e: errors.append(e)
                else: configured.append({"name":n,"weight_g":w})
            if errors: st.session_state["_configuration_error"]=" ".join(errors); st.rerun()
            atypical=[x for x in configured if weight_requires_confirmation(x["weight_g"])]
            if atypical: queue_weight_warning("configuration",configured); st.rerun()
            try:
                exp_id=create_experiment_record(name,configured); _clear_configuration(); load_experiment_into_session(exp_id); st.rerun()
            except Exception as exc: st.error(f"Could not create experiment: {exc}")

@st.dialog("Confirm mouse weight")
def weight_warning_dialog():
    payload=st.session_state.get("_pending_weight_warning") or {}; entries=payload.get("entries",[]); st.warning("One or more mouse weights are outside the usual 20–40 g range.")
    for x in entries:
        if weight_requires_confirmation(x.get("weight_g")): st.write(f"• {x.get('name','Mouse')}: {float(x.get('weight_g',0)):.1f} g")
    left,right=st.columns(2)
    with left:
        if st.button("Go back",key="weight_warning_cancel",use_container_width=True): st.session_state.pop("_pending_weight_warning",None); st.rerun()
    with right:
        if st.button("Use these weights",key="weight_warning_accept",use_container_width=True,type="primary"):
            context=payload.get("context")
            if context=="configuration":
                try:
                    exp_id=create_experiment_record(st.session_state.get("_configuration_experiment_name","Experiment"),entries); st.session_state.pop("_pending_weight_warning",None); _clear_configuration(); load_experiment_into_session(exp_id); st.rerun()
                except Exception as exc: st.error(str(exc))
            elif context=="add_mouse":
                e=entries[0] if entries else {}; ok,error=create_mouse_subject(e.get("name"),e.get("weight_g"))
                if ok: st.session_state.pop("_pending_weight_warning",None); st.session_state.pop("_add_mouse_name",None); st.session_state.pop("_add_mouse_weight",None); st.rerun()
                st.warning(error)
            elif context=="edit_subject":
                e=entries[0] if entries else {}; i=int(payload.get("mouse",0)); ok,error=save_subject_profile(i,e.get("name"),e.get("weight_g"))
                if ok: st.session_state.pop("_pending_weight_warning",None); st.session_state.pop(f"edit_name_{i}",None); st.session_state.pop(f"edit_weight_{i}",None); st.rerun()
                st.warning(error)

def _fmt_epoch(epoch):
    try: return wall_datetime(float(epoch)).strftime("%b %d, %Y · %I:%M:%S %p")
    except Exception: return "Unknown"

@st.dialog("Rename experiment")
def rename_experiment_dialog(exp_id,current_name):
    key=f"rename_exp_text_{exp_id}"; st.session_state.setdefault(key,str(current_name)); st.text_input("Experiment name",key=key); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"rename_exp_cancel_{exp_id}",use_container_width=True): st.rerun()
    with right:
        if st.button("Save",key=f"rename_exp_save_{exp_id}",use_container_width=True,type="primary"):
            value=str(st.session_state.get(key,"")).strip()
            if value: rename_experiment_record(exp_id,value); st.rerun()
            st.warning("Experiment name cannot be blank.")

@st.dialog("End experiment")
def end_experiment_home_dialog(exp_id,exp_name):
    st.markdown(f"### End {html.escape(str(exp_name))}?",unsafe_allow_html=True); st.write("This ends every remaining subject and moves the experiment to Completed experiments."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"end_exp_cancel_{exp_id}",use_container_width=True): st.rerun()
    with right:
        if st.button("End experiment",key=f"end_exp_confirm_{exp_id}",use_container_width=True,type="primary"): end_experiment_record(exp_id); st.rerun()

@st.dialog("Delete experiment")
def delete_experiment_dialog(exp_id,exp_name):
    st.markdown(f"### Delete {html.escape(str(exp_name))}?",unsafe_allow_html=True); st.write("This permanently deletes the experiment and its saved subject timesheets."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"delete_exp_cancel_{exp_id}",use_container_width=True): st.rerun()
    with right:
        if st.button("Delete permanently",key=f"delete_exp_confirm_{exp_id}",use_container_width=True,type="primary"): delete_experiment_record(exp_id); st.rerun()

def _render_experiment_card(exp,completed):
    exp_id,name=str(exp["id"]),str(exp["name"]); widths=[4.6,1.1,.95,.88] if completed else [4.2,1.1,.95,.82,.88]
    with st.container(border=True):
        cols=st.columns(widths,vertical_alignment="center")
        with cols[0]: st.markdown(f"**{html.escape(name)}**",unsafe_allow_html=True); st.caption(f"{int(exp['mouse_count'])} mice · Last saved {_fmt_epoch(exp['updated_at'])}")
        with cols[1]:
            if st.button("Open" if completed else "Resume",key=f"open_exp_{exp_id}",use_container_width=True,type="primary" if not completed else "secondary"):
                if load_experiment_into_session(exp_id): st.rerun()
                st.error("Experiment could not be loaded.")
        with cols[2]:
            if st.button("Rename",key=f"rename_exp_{exp_id}",use_container_width=True): rename_experiment_dialog(exp_id,name)
        if completed:
            with cols[3]:
                if st.button("Delete",key=f"delete_exp_{exp_id}",use_container_width=True): delete_experiment_dialog(exp_id,name)
        else:
            with cols[3]:
                if st.button("End",key=f"end_exp_{exp_id}",use_container_width=True): end_experiment_home_dialog(exp_id,name)
            with cols[4]:
                if st.button("Delete",key=f"delete_exp_{exp_id}",use_container_width=True): delete_experiment_dialog(exp_id,name)

def render_experiment_home():
    st.markdown('<div class="lab-header-title" style="font-size:2.05rem;margin-top:.4rem;">Shock Timer</div>',unsafe_allow_html=True); st.caption("Create a new experiment or resume a saved session.")
    if DATABASE_KIND=="postgres": st.success("Persistent cloud storage connected.")
    else: st.warning("Local SQLite storage is active. Configure SHOCK_TIMER_DATABASE_URL for shared/cloud persistence.")
    with st.container(border=True):
        st.markdown("### New experiment")
        with st.form("new_experiment_form",clear_on_submit=False):
            cols=st.columns([4.4,1.15,1.7],vertical_alignment="bottom")
            with cols[0]: experiment_name=st.text_input("Experiment name",placeholder="e.g. Plasma resuscitation 08-22-2026")
            with cols[1]: subject_count=st.number_input("Mouse subjects",min_value=1,max_value=64,value=INITIAL_MOUSE_COUNT,step=1)
            with cols[2]: submitted=st.form_submit_button("Configure experiment",use_container_width=True,type="primary")
        if submitted: begin_experiment_configuration(experiment_name,subject_count)
        error=st.session_state.pop("_home_error",None)
        if error: st.error(error)
    experiments=list_experiment_records(); active=[x for x in experiments if x.get("completed_at") is None]; completed=[x for x in experiments if x.get("completed_at") is not None]
    st.markdown("### Active experiments")
    if active:
        for x in active: _render_experiment_card(x,False)
    else: st.info("No active experiments.")
    st.markdown("### Completed experiments")
    if completed:
        for x in completed: _render_experiment_card(x,True)
    else: st.caption("Completed experiments will appear here once all subjects are ended.")
    if st.session_state.get("_pending_weight_warning"): weight_warning_dialog()
    elif st.session_state.get("_show_configuration_dialog"): configure_experiment_dialog()

def return_to_experiment_home(): retry_unsaved_subjects(); st.session_state.clear(); st.rerun()

# ============================================================
# ACTIVE EXPERIMENT DIALOGS
# ============================================================

@st.dialog("Timesheet",width="large")
def timesheet_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} timesheet",unsafe_allow_html=True); st.caption(f"{weight_label(i)} · {APP_TIMEZONE} · Start events can be back-timed when a button was clicked late."); log=list(st.session_state.get(f"event_log_{i}",[]))
    if not log: st.info("No events have been recorded.")
    else:
        rel=relative_time_map(i,log); hdr=st.columns([1.85,1.05,1.70,2.35,.85],gap="small")
        for c,label in zip(hdr,["Event","Relative time","Absolute time","Details","Adjust"]):
            with c: st.markdown(f'<div class="lab-table-header">{label}</div>',unsafe_allow_html=True)
        for order,e in enumerate(log):
            row=st.columns([1.85,1.05,1.70,2.35,.85],gap="small",vertical_alignment="center"); relative=rel.get(e.get("_id"),rel.get(f"__order_{order}","—"))
            with row[0]: st.markdown(f"**{html.escape(str(e.get('Event','')))}**",unsafe_allow_html=True)
            with row[1]: st.caption(relative)
            with row[2]: st.caption(str(e.get("Absolute time","")))
            with row[3]: st.caption(str(e.get("Details","")).strip() or "—")
            with row[4]:
                if is_backtime_editable_event(e) and st.button("Back-time",key=f"backtime_select_{i}_{e.get('_id')}",use_container_width=True): st.session_state[f"_backtime_target_{i}"]=e.get("_id")
        target=st.session_state.get(f"_backtime_target_{i}")
        if target:
            st.divider(); st.markdown("**Back-time selected event**"); mins=st.number_input("Minutes earlier",min_value=.1,step=.5,value=1.0,key=f"backtime_minutes_{i}"); left,right=st.columns(2)
            with left:
                if st.button("Cancel adjustment",key=f"backtime_cancel_{i}",use_container_width=True): st.session_state.pop(f"_backtime_target_{i}",None); st.rerun()
            with right:
                if st.button("Apply back-time",key=f"backtime_apply_{i}",use_container_width=True,type="primary"):
                    ok,error=backtime_start_event(i,target,mins)
                    if ok: st.session_state.pop(f"_backtime_target_{i}",None); st.rerun()
                    st.warning(error)

@st.dialog("Add comment")
def comment_dialog(i):
    key=f"comment_text_{i}"; st.session_state.setdefault(key,""); st.markdown(f"**{html.escape(subject_name(i))}**",unsafe_allow_html=True); st.text_area("Comment",key=key,height=130); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"comment_cancel_{i}",use_container_width=True): st.session_state.pop(key,None); st.rerun()
    with right:
        if st.button("Accept",key=f"comment_accept_{i}",use_container_width=True,type="primary"):
            text=str(st.session_state.get(key,"")).strip()
            if not text: st.warning("Enter a comment.")
            else: log_event(i,"Comment",text); persist_subject(i); st.session_state.pop(key,None); st.rerun()

@st.dialog("Edit subject")
def edit_subject_dialog(i):
    nk,wk=f"edit_name_{i}",f"edit_weight_{i}"; st.session_state.setdefault(nk,subject_name(i)); st.session_state.setdefault(wk,float(mouse_weight(i) or 0.0)); st.text_input("Subject name",key=nk); st.number_input("Weight (g)",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"edit_cancel_{i}",use_container_width=True): st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
    with right:
        if st.button("Save",key=f"edit_save_{i}",use_container_width=True,type="primary"):
            name,weight,error=validate_mouse_name_weight(st.session_state.get(nk),st.session_state.get(wk),f"Mouse {i}")
            if error: st.warning(error)
            elif weight_requires_confirmation(weight): queue_weight_warning("edit_subject",[{"name":name,"weight_g":weight}],mouse=i); st.rerun()
            else:
                ok,error=save_subject_profile(i,name,weight)
                if ok: st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
                st.warning(error)

def notification_sound_wav(sound_name):
    sample_rate=22050
    notes=[(880.0,0,.18,.32)] if sound_name=="Beep" else ([(760.0,0,.12,.30),(760.0,.20,.12,.30)] if sound_name=="Double beep" else [(660.0,0,.12,.24),(990.0,.11,.22,.25)])
    total_duration=max(s+d for _,s,d,_ in notes)+.04; samples=[0.0]*max(1,int(total_duration*sample_rate)); fade=max(1,int(.012*sample_rate))
    for frequency,start,duration,gain in notes:
        start_sample=int(start*sample_rate); note_samples=max(1,int(duration*sample_rate))
        for offset in range(note_samples):
            target=start_sample+offset
            if target>=len(samples): break
            envelope=1.0
            if offset<fade: envelope*=offset/fade
            tail=note_samples-1-offset
            if tail<fade: envelope*=max(0,tail/fade)
            samples[target]+=gain*envelope*math.sin(2*math.pi*frequency*(offset/sample_rate))
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sample_rate); frames=bytearray()
        for value in samples: frames.extend(struct.pack("<h",int(max(-1,min(1,value))*32767)))
        w.writeframes(bytes(frames))
    return buffer.getvalue()

def queue_notification_sound_sample(): st.session_state["_pending_sound_sample"]={"token":uuid.uuid4().hex,"sound":str(st.session_state.get("settings_notification_sound",DEFAULT_NOTIFICATION_SOUND))}
def render_notification_sound_sample():
    pending=st.session_state.pop("_pending_sound_sample",None)
    if pending: st.audio(notification_sound_wav(str(pending.get("sound",DEFAULT_NOTIFICATION_SOUND))),format="audio/wav",autoplay=True)

@st.dialog("Settings",width="large")
def settings_dialog():
    st.markdown("### Global anesthesia schedule"); st.caption("These values apply to every mouse in this experiment. The first redose interval runs from the initial anesthesia dose; every redose after that uses the subsequent interval.")
    first=ordered_subject_indices()[0] if mouse_count() else 1; ik="settings_global_initial_anesthesia"; sk="settings_global_subsequent_anesthesia"; dk="settings_global_anesthesia_delay"; ek="settings_notification_sound_enabled"; nk="settings_notification_sound"
    st.session_state.setdefault(ik,int(st.session_state.get(f"anesthesia_initial_duration_{first}",DEFAULT_INITIAL_ANESTHESIA))); st.session_state.setdefault(sk,int(st.session_state.get(f"anesthesia_duration_{first}",DEFAULT_SUBSEQUENT_ANESTHESIA))); st.session_state.setdefault(dk,int(st.session_state.get(f"anesthesia_delay_duration_{first}",DEFAULT_ANESTHESIA_DELAY))); st.session_state.setdefault(ek,bool(st.session_state.get(f"notification_sound_enabled_{first}",DEFAULT_NOTIFICATION_SOUND_ENABLED))); st.session_state.setdefault(nk,str(st.session_state.get(f"notification_sound_{first}",DEFAULT_NOTIFICATION_SOUND)))
    cols=st.columns(3)
    with cols[0]: st.number_input(f"First redose ({UNIT_LABEL})",min_value=1,step=1,key=ik,help="Default: 45 minutes after the initial anesthesia dose.")
    with cols[1]: st.number_input(f"Subsequent redoses ({UNIT_LABEL})",min_value=1,step=1,key=sk,help="Default: every 30 minutes after each redose.")
    with cols[2]: st.number_input(f"Delay button ({UNIT_LABEL})",min_value=1,step=1,key=dk)
    with st.expander("🔊 Notification sound",expanded=False):
        st.toggle("Play a sound when an event becomes due",key=ek); st.selectbox("Sound",NOTIFICATION_SOUND_OPTIONS,key=nk,disabled=not bool(st.session_state.get(ek,True)),on_change=queue_notification_sound_sample); render_notification_sound_sample(); st.caption("Changing the sound plays a sample immediately.")
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="settings_cancel",use_container_width=True): st.rerun()
    with right:
        if st.button("Save settings",key="settings_save",use_container_width=True,type="primary"):
            initial=int(st.session_state[ik]); subsequent=int(st.session_state[sk]); delay=int(st.session_state[dk]); enabled=bool(st.session_state[ek]); sound=str(st.session_state[nk])
            _record_global_undo("Update global settings",range(1,mouse_count()+1))
            for i in range(1,mouse_count()+1): st.session_state[f"anesthesia_initial_duration_{i}"]=initial; st.session_state[f"anesthesia_duration_{i}"]=subsequent; st.session_state[f"anesthesia_delay_duration_{i}"]=delay; st.session_state[f"notification_sound_enabled_{i}"]=enabled; st.session_state[f"notification_sound_{i}"]=sound
            persist_subjects(range(1,mouse_count()+1)); st.toast("Global settings updated"); st.rerun()

@st.dialog("Confirm end")
def end_confirmation_dialog(i):
    st.markdown(f"### End {html.escape(subject_name(i))}?",unsafe_allow_html=True); st.write("This freezes the subject timers and preserves the timesheet."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"end_cancel_{i}",use_container_width=True): st.rerun()
    with right:
        if st.button("End subject",key=f"end_confirm_{i}",use_container_width=True,type="primary"): end_mouse(i); st.rerun()

@st.dialog("Reset subject")
def reset_confirmation_dialog(i):
    st.markdown(f"### Reset {html.escape(subject_name(i))}?",unsafe_allow_html=True); st.write("This clears timer events and timesheet entries for this subject."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"reset_cancel_{i}",use_container_width=True): st.rerun()
    with right:
        if st.button("Reset",key=f"reset_confirm_{i}",use_container_width=True,type="primary"): reset_mouse(i); st.rerun()

@st.dialog("End all subjects")
def end_all_subjects_dialog():
    remaining=[i for i in ordered_subject_indices() if not is_ended(i)]; st.markdown("### End all subjects?"); st.write(f"This ends {len(remaining)} remaining subject{'s' if len(remaining)!=1 else ''} and downloads the aggregate timesheet."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="end_all_cancel",use_container_width=True): st.rerun()
    with right:
        if st.button("End all subjects",key="end_all_confirm",use_container_width=True,type="primary"):
            if end_all_subjects_current_experiment(): queue_timesheet_auto_download(); st.rerun()
            else: st.error("Subjects were ended locally, but persistent storage has not confirmed the save yet.")

@st.dialog("Add mouse")
def add_mouse_dialog():
    new_i=mouse_count()+1; nk,wk="_add_mouse_name","_add_mouse_weight"; st.session_state.setdefault(nk,f"Mouse {new_i}"); st.session_state.setdefault(wk,0.0); st.caption("Enter the mouse name and weight before adding it to the running experiment."); st.text_input("Mouse name",key=nk); st.number_input("Weight (g)",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="add_mouse_cancel",use_container_width=True): st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
    with right:
        if st.button("Add mouse",key="add_mouse_confirm",use_container_width=True,type="primary"):
            name,weight,error=validate_mouse_name_weight(st.session_state.get(nk),st.session_state.get(wk),f"Mouse {new_i}")
            if error: st.warning(error)
            elif weight_requires_confirmation(weight): queue_weight_warning("add_mouse",[{"name":name,"weight_g":weight}]); st.rerun()
            else:
                ok,error=create_mouse_subject(name,weight)
                if ok: st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
                st.warning(error)

def request_add_mouse_dialog(): st.session_state["_pending_dialog"]={"mouse":0,"kind":"add_mouse"}
def request_dialog(i,kind): st.session_state["_pending_dialog"]={"mouse":int(i),"kind":kind}
def render_pending_dialog():
    req=st.session_state.pop("_pending_dialog",None)
    if not req: return
    kind=req.get("kind")
    if kind=="add_mouse": add_mouse_dialog(); return
    i=int(req.get("mouse",0))
    if not 1<=i<=mouse_count(): return
    {"timesheet":timesheet_dialog,"comment":comment_dialog,"edit":edit_subject_dialog,"end":end_confirmation_dialog,"reset":reset_confirmation_dialog}.get(kind,lambda _:None)(i)

# ============================================================
# ATTENTION / AUTO DOWNLOAD / BROWSER HELPERS
# ============================================================

def urgency_for_remaining(remaining):
    if remaining is None: return "normal"
    if remaining<=0: return "red"
    return "orange" if warning_seconds()>0 and remaining<=warning_seconds() else "normal"

def get_upcoming_events(i,now):
    if is_ended(i): return []
    events=[]
    if st.session_state.get(f"anesthesia_start_{i}") is not None: events.append(("Anesthesia redose",anesthesia_remaining(i,now)))
    board,shock,resus=st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}")
    if board is not None and shock is None: events.append(("Shock",remaining_from_start(board,FIXED_BOARD_DURATION,now)))
    if shock is not None and resus is None: events.append(("Resuscitation",remaining_from_start(shock,FIXED_SHOCK_DURATION,now)))
    if resus is not None: events.append(("Resuscitation complete",remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now)))
    return events

def action_targets_for_alert(i,event,remaining):
    if is_ended(i) or is_paused(i): return []
    if event=="Anesthesia redose": return [{"key":f"anesthesia_redose_action_{i}","style":"primary"},{"key":f"anesthesia_delay_action_{i}","style":"delay"}]
    if remaining<=0: return [{"key":f"primary_action_{i}","style":"primary"}]
    return []

def collect_attention_items(wall_now):
    sticky=st.session_state.setdefault("_sticky_alerts",{}); active=set()
    for i in ordered_subject_indices():
        if is_ended(i): clear_mouse_alerts(i); continue
        now=effective_now(i,wall_now)
        for event,remaining in get_upcoming_events(i,now):
            key=alert_key(i,event); active.add(key); level=urgency_for_remaining(remaining)
            if level in ("orange","red"): sticky[key]={"mouse":i,"name":subject_name(i),"event":event,"remaining":remaining,"level":level}
    for key in list(sticky):
        if key not in active: sticky.pop(key,None)
    items=[]
    for x in sticky.values():
        y=dict(x); y["targets"]=action_targets_for_alert(y["mouse"],y["event"],y["remaining"]); items.append(y)
    return sorted(items,key=lambda x:(0 if x["level"]=="red" else 1,x["remaining"]))

def render_attention_snapshot(items):
    first=ordered_subject_indices()[0] if mouse_count() else 1; payload={"items":[{"mouse":x["mouse"],"name":x["name"],"event":x["event"],"level":x["level"],"targets":x.get("targets",[])} for x in items],"soundEnabled":bool(st.session_state.get(f"notification_sound_enabled_{first}",DEFAULT_NOTIFICATION_SOUND_ENABLED)),"soundName":str(st.session_state.get(f"notification_sound_{first}",DEFAULT_NOTIFICATION_SOUND))}; encoded=base64.b64encode(json.dumps(payload,separators=(",",":")).encode()).decode(); st.html(f'<div data-lab-attention-snapshot="{encoded}" style="display:none!important"></div>')

def queue_timesheet_auto_download(): st.session_state["_pending_auto_download"]={"token":uuid.uuid4().hex,"filename":f"shock_timer_timesheets_{wall_datetime().strftime('%Y-%m-%d')}.txt","content_b64":base64.b64encode(build_all_timesheets_text().encode()).decode()}
def render_pending_auto_download_marker():
    pending=st.session_state.get("_pending_auto_download")
    if pending: st.html(f'<div data-lab-auto-download-token="{html.escape(pending["token"],quote=True)}" data-lab-auto-download-filename="{html.escape(pending["filename"],quote=True)}" data-lab-auto-download-content="{pending["content_b64"]}" style="display:none!important"></div>')

def install_browser_helpers():
    components.html(r"""
    <script>
    (()=>{
      const doc=window.parent.document,BAR='lab-attention-v40',P='lab-next-primary-v40',D='lab-next-delay-v40';
      let bar=doc.getElementById(BAR);if(!bar){bar=doc.createElement('div');bar.id=BAR;bar.style.cssText='display:none;position:fixed;z-index:999999';doc.body.appendChild(bar)}
      if(!doc.getElementById('lab-v40-browser-style')){const s=doc.createElement('style');s.id='lab-v40-browser-style';s.textContent=`.${P} button{outline:2px solid rgba(245,161,38,.55)!important;outline-offset:1px}.${D} button{outline:2px solid rgba(184,122,244,.5)!important;outline-offset:1px}`;doc.head.appendChild(s)}
      let last='',dismissed='',targets=[],lastDue='';
      function beep(name){try{const C=window.AudioContext||window.webkitAudioContext,c=new C();const note=(f,t,d)=>{const o=c.createOscillator(),g=c.createGain();o.frequency.value=f;g.gain.setValueAtTime(.0001,c.currentTime+t);g.gain.exponentialRampToValueAtTime(.12,c.currentTime+t+.01);g.gain.exponentialRampToValueAtTime(.0001,c.currentTime+t+d);o.connect(g);g.connect(c.destination);o.start(c.currentTime+t);o.stop(c.currentTime+t+d+.02)};if(name==='Double beep'){note(760,0,.12);note(760,.2,.12)}else if(name==='Beep')note(880,0,.18);else{note(660,0,.14);note(990,.11,.22)}}catch(_){}}
      function apply(encoded){let p;try{p=JSON.parse(atob(encoded))}catch(e){return}const items=p.items||[];if(encoded!==last)dismissed='';last=encoded;targets=[];for(const item of items)for(const t of(item.targets||[]))if(!targets.some(x=>x.key===t.key&&x.style===t.style))targets.push(t);const due=items.filter(x=>x.level==='red').map(x=>x.mouse+':'+x.event).sort().join('|');if(due&&due!==lastDue&&p.soundEnabled)beep(p.soundName||'Chime');lastDue=due;if(!items.length||dismissed===encoded)bar.style.display='none';else{bar.innerHTML=items.map(i=>`<span class="${i.level}" style="margin-right:14px">${i.name}: ${i.event}</span>`).join('')+`<span class="x">×</span>`;bar.querySelector('.x').onclick=()=>{dismissed=encoded;bar.style.display='none'};bar.style.display='block'}}
      function highlights(){const wanted=new Map(targets.map(t=>[t.key,t.style==='delay'?D:P]));doc.querySelectorAll(`.${P},.${D}`).forEach(n=>{const kc=[...n.classList].find(c=>c.startsWith('st-key-'));const k=kc?kc.slice(7):null,w=k?wanted.get(k):null;if(!w||!n.classList.contains(w))n.classList.remove(P,D)});for(const[k,c]of wanted.entries())doc.querySelectorAll(`.st-key-${k}`).forEach(n=>{const b=n.querySelector('button');if(b&&!b.disabled){n.classList.remove(P,D);n.classList.add(c)}})}
      function full(){const w=doc.querySelector('.st-key-fullscreen_view');if(!w||w.dataset.bound==='1')return;const b=w.querySelector('button');if(!b)return;w.dataset.bound='1';b.addEventListener('click',()=>{const r=doc.documentElement;if(!doc.fullscreenElement&&r.requestFullscreen)r.requestFullscreen().catch(()=>{});else if(doc.fullscreenElement&&doc.exitFullscreen)doc.exitFullscreen().catch(()=>{})},true)}
      function download(){const ms=doc.querySelectorAll('[data-lab-auto-download-token]');if(!ms.length)return;const m=ms[ms.length-1],t=m.dataset.labAutoDownloadToken,e=m.dataset.labAutoDownloadContent;if(!t||!e||doc.documentElement.dataset.labLastDownload===t)return;try{const bin=atob(e),bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);const url=URL.createObjectURL(new Blob([bytes],{type:'text/plain;charset=utf-8'}));const a=doc.createElement('a');a.href=url;a.download=m.dataset.labAutoDownloadFilename||'shock_timer_timesheets.txt';doc.body.appendChild(a);doc.documentElement.dataset.labLastDownload=t;a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500)}catch(_){}}
      function poll(){const ss=doc.querySelectorAll('[data-lab-attention-snapshot]');if(ss.length){const e=ss[ss.length-1].dataset.labAttentionSnapshot;if(e&&e!==last)apply(e)}highlights();full();download()}
      poll();setInterval(poll,150);
    })();
    </script>
    """,width=1,height=1,tab_index=-1)

# ============================================================
# DISPLAY / WORKFLOW
# ============================================================

def html_cell(primary,secondary=None,tone="normal"):
    cls="lab-primary-text"+(f" {tone}" if tone!="normal" else ""); second=f'<div class="lab-secondary-text">{html.escape(str(secondary))}</div>' if secondary else ""; return f'<div class="lab-cell"><div class="{cls}">{html.escape(str(primary))}</div>{second}</div>'

def mouse_status_tone(i,now):
    if is_paused(i) or is_ended(i) or st.session_state.get(f"experiment_start_{i}") is None: return "gray"
    levels=[urgency_for_remaining(rem) for _,rem in get_upcoming_events(i,now)]; return "red" if "red" in levels else "orange" if "orange" in levels else "green"

def get_next_event_display(i,now):
    if is_ended(i): return "Ended","gray"
    if st.session_state.get(f"experiment_start_{i}") is None: return "Not started","gray"
    upcoming=get_upcoming_events(i,now)
    if not upcoming: return "Ready","green"
    event,remaining=min(upcoming,key=lambda x:x[1]); tone=urgency_for_remaining(remaining); friendly={"Anesthesia redose":"Anesthesia","Shock":"Shock","Resuscitation":"Resus","Resuscitation complete":"Resus"}[event]
    if remaining<=0:
        overdue=format_timer(-remaining)
        if event=="Anesthesia redose": return f"Redose due +{overdue}",tone
        if event=="Resuscitation complete": return f"Resus complete +{overdue}",tone
        return f"{friendly} due +{overdue}",tone
    return f"{friendly} in {format_timer(remaining)}",tone

def anesthesia_display(i,now):
    start=st.session_state.get(f"anesthesia_start_{i}")
    if start is None: return "Not started",weight_label(i),"gray"
    remaining=anesthesia_remaining(i,now); tone=urgency_for_remaining(remaining); label="First redose" if anesthesia_dose_count(i)<=1 else "Redose"; return (f"{label} due",weight_label(i),tone) if remaining<=0 else (f"{label} in {format_timer(remaining)}",weight_label(i),tone if tone!="normal" else "normal")

def render_anesthesia_controls(i):
    delay=st.session_state[f"anesthesia_delay_duration_{i}"]; redose=st.session_state.get(f"anesthesia_initial_duration_{i}",DEFAULT_INITIAL_ANESTHESIA) if anesthesia_dose_count(i)<=1 else st.session_state.get(f"anesthesia_duration_{i}",DEFAULT_SUBSEQUENT_ANESTHESIA); disabled=st.session_state.get(f"experiment_start_{i}") is None or st.session_state.get(f"anesthesia_start_{i}") is None or is_paused(i) or is_ended(i); cols=st.columns(2,gap="small")
    with cols[0]:
        with st.container(key=f"anesthesia_redose_action_{i}"): st.button(f"Redose ({redose}{UNIT_SHORT})",key=f"redose_{i}",use_container_width=True,disabled=disabled,on_click=start_or_redose_anesthesia,args=(i,),help="Record the anesthesia redose now.")
    with cols[1]:
        with st.container(key=f"anesthesia_delay_action_{i}"): st.button(f"Delay ({delay}{UNIT_SHORT})",key=f"delay_{i}",use_container_width=True,disabled=disabled,on_click=delay_anesthesia_reminder,args=(i,),help="Delay the reminder from this moment.")

def workflow_statuses(i,now):
    anes,board,shock,resus=st.session_state.get(f"anesthesia_start_{i}"),st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}"); states=["pending"]*4
    if anes is None: return states
    states[0]="active" if board is None else "complete"
    if board is not None: states[1]="complete" if shock is not None else ("overdue" if urgency_for_remaining(remaining_from_start(board,FIXED_BOARD_DURATION,now))=="red" else "action" if urgency_for_remaining(remaining_from_start(board,FIXED_BOARD_DURATION,now))=="orange" else "active")
    if shock is not None: states[2]="complete" if resus is not None else ("overdue" if urgency_for_remaining(remaining_from_start(shock,FIXED_SHOCK_DURATION,now))=="red" else "action" if urgency_for_remaining(remaining_from_start(shock,FIXED_SHOCK_DURATION,now))=="orange" else "active")
    if resus is not None: states[3]="complete" if is_ended(i) else ("overdue" if urgency_for_remaining(remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now))=="red" else "action" if urgency_for_remaining(remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now))=="orange" else "active")
    return states

def workflow_step_times(i,now):
    anes,board,shock,resus=st.session_state.get(f"anesthesia_start_{i}"),st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}"); end_time=st.session_state.get(f"end_time_{i}") if is_ended(i) else None; times=[("","gray") for _ in range(4)]
    if anes is not None: times[0]=(format_phase_timer(elapsed_from(anes,board if board is not None else now)),"gray" if board is not None else "green")
    if board is not None:
        stop=shock if shock is not None else now; urgency=urgency_for_remaining(remaining_from_start(board,FIXED_BOARD_DURATION,now)); times[1]=(f"{format_phase_timer(elapsed_from(board,stop))} / {format_phase_timer(duration_to_seconds(FIXED_BOARD_DURATION))}","gray" if shock is not None else urgency if urgency!="normal" else "green")
    if shock is not None:
        stop=resus if resus is not None else now; urgency=urgency_for_remaining(remaining_from_start(shock,FIXED_SHOCK_DURATION,now)); times[2]=(f"{format_phase_timer(elapsed_from(shock,stop))} / {format_phase_timer(duration_to_seconds(FIXED_SHOCK_DURATION))}","gray" if resus is not None else urgency if urgency!="normal" else "green")
    if resus is not None:
        stop=end_time if end_time is not None else now; urgency=urgency_for_remaining(remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now)); times[3]=(f"{format_phase_timer(elapsed_from(resus,stop))} / {format_phase_timer(duration_to_seconds(FIXED_RESUSCITATION_DURATION))}","gray" if is_ended(i) else urgency if urgency!="normal" else "green")
    return times

def workflow_html(i,now):
    labels=["Anesthesia",f"Board {fixed_duration_label(FIXED_BOARD_DURATION)}",f"Shock {fixed_duration_label(FIXED_SHOCK_DURATION)}",f"Resus {fixed_duration_label(FIXED_RESUSCITATION_DURATION)}"]; parts=['<div class="lab-cell"><div class="lab-stepper">']
    for idx,(state,label) in enumerate(zip(workflow_statuses(i,now),labels)):
        timer,tone=workflow_step_times(i,now)[idx]; th=f'<div class="lab-step-time {tone}">{html.escape(timer)}</div>' if timer else '<div class="lab-step-time">&nbsp;</div>'; parts.append(f'<div class="lab-step {state}"><div class="lab-step-circle">{idx+1}</div><div class="lab-step-label">{html.escape(label)}</div>{th}</div>')
    parts.append('</div></div>'); return ''.join(parts)

# ============================================================
# ACTIONS / MENU
# ============================================================

def actionable_event_for_mouse(i,now):
    if is_ended(i): return None
    if is_paused(i): return "resume"
    anes,board,shock,resus=st.session_state.get(f"anesthesia_start_{i}"),st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}")
    if anes is None: return "start_anesthesia"
    due=[]
    if board is not None and shock is None:
        rem=remaining_from_start(board,FIXED_BOARD_DURATION,now)
        if rem<=0: due.append((rem,"start_shock"))
    if shock is not None and resus is None:
        rem=remaining_from_start(shock,FIXED_SHOCK_DURATION,now)
        if rem<=0: due.append((rem,"start_resus"))
    if resus is not None:
        rem=remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now)
        if rem<=0: due.append((rem,"end"))
    if due: return min(due,key=lambda x:x[0])[1]
    if board is None: return "start_board"
    return "pause"

def render_primary_action(i,now):
    action=actionable_event_for_mouse(i,now)
    if action is None: st.button("Ended",key=f"ended_display_button_{i}",disabled=True,use_container_width=True); return
    mapping={"resume":("▶ Resume",toggle_pause),"start_anesthesia":("▷ Start",start_or_redose_anesthesia),"start_board":("▷ Start board",start_board),"start_shock":("⚡ Start shock",start_shock),"start_resus":("♥ Start resus",start_resuscitation)}
    if action in mapping:
        label,fn=mapping[action]
        wrapper=f"primary_start_anesthesia_wrapper_{i}" if action=="start_anesthesia" else f"primary_action_{i}"
        with st.container(key=wrapper): st.button(label,key=f"primary_{action}_{i}",use_container_width=True,on_click=fn,args=(i,)); return
    if action=="end":
        with st.container(key=f"primary_action_{i}"): st.button("■ End",key=f"primary_end_{i}",use_container_width=True,on_click=request_dialog,args=(i,"end")); return
    with st.container(key=f"primary_pause_{i}"): st.button("Ⅱ Pause",key=f"primary_pause_button_{i}",use_container_width=True,on_click=toggle_pause,args=(i,))

def force_advance_label(i,now):
    if is_ended(i) or is_paused(i): return None
    board,shock,resus=st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}")
    if board is not None and shock is None and not board_is_complete(i,now): return "⏭ Force start shock"
    if shock is not None and resus is None and not shock_is_complete(i,now): return "⏭ Force start resus"
    if resus is not None and not resus_is_complete(i,now): return "⏭ Force end subject"
    return None

def force_advance(i):
    now=time.time(); label=force_advance_label(i,now)
    if label=="⏭ Force start shock": start_shock(i,True)
    elif label=="⏭ Force start resus": start_resuscitation(i,True)
    elif label=="⏭ Force end subject": end_mouse(i,True)

def _process_menu(i,selection):
    if not selection: return
    if selection=="View timesheet": request_dialog(i,"timesheet"); st.rerun()
    elif selection=="Add comment": request_dialog(i,"comment"); st.rerun()
    elif selection=="Edit subject": request_dialog(i,"edit"); st.rerun()
    elif selection in ("Ⅱ Pause","▶ Resume"): toggle_pause(i); st.rerun()
    elif selection=="↑ Move up": move_subject(i,-1); st.rerun()
    elif selection=="↓ Move down": move_subject(i,1); st.rerun()
    elif selection.startswith("↶ Undo"): undo_last_stage_action(i); st.rerun()
    elif selection.startswith("⏭ Force"): force_advance(i); st.rerun()
    elif selection=="↻ Reset subject": request_dialog(i,"reset"); st.rerun()
    elif selection=="■ End subject": request_dialog(i,"end"); st.rerun()

def render_overflow_control(i,now):
    options=["View timesheet","Add comment","Edit subject"]; group=_reorder_group(i,time.time()); peers=[j for j in ordered_subject_indices() if _reorder_group(j,time.time())==group]
    if i in peers:
        pos=peers.index(i)
        if pos>0: options.append("↑ Move up")
        if pos<len(peers)-1: options.append("↓ Move down")
    undo=latest_undo_action(i)
    if undo and not is_ended(i): options.append(f"↶ Undo {_undo_label(undo)}")
    force=force_advance_label(i,now)
    if force: options.append(force)
    if st.session_state.get(f"experiment_start_{i}") is not None and not is_ended(i): options += ["▶ Resume" if is_paused(i) else "Ⅱ Pause","↻ Reset subject","■ End subject"]
    with st.container(key=f"mouse_action_menu_{i}"):
        if hasattr(st,"menu_button"):
            selection=st.menu_button("⋮",options=options,key=f"menu_{i}",width="stretch"); _process_menu(i,selection)
        else:
            with st.popover("⋮",use_container_width=True):
                for option in options:
                    if st.button(option,key=f"fallback_menu_{i}_{option}",use_container_width=True): _process_menu(i,option)

# ============================================================
# V40 CARD ROW
# ============================================================

def _v40_mouse_icon():
    return ('<span class="lab-mouse-icon" aria-hidden="true"><svg viewBox="0 0 32 32">'
            '<path d="M8.4 18.6c0-5.3 3.6-9.1 8.7-9.1 4.2 0 7.4 2.5 8.4 6.1 2.6.1 4.4 1.5 4.4 3.5 0 2.4-2.3 4-5.5 4h-1.2c-1.6 2.1-4.1 3.4-7.1 3.4-4.6 0-7.7-3-7.7-7.9Z"/>'
            '<path d="M11.1 10.8c-1.6-1.6-1.7-4.2-.1-5.7 1.6-1.5 4.4-.9 5.4 1.4"/>'
            '<path d="M18.9 9.7c.1-2.3 2.1-4.3 4.4-4.2 2.4.1 3.8 2.4 3.1 4.4"/><circle cx="21.2" cy="15.3" r=".8"/><path d="M8.6 21.7c-3.2.2-5.5 1.5-6.4 3.7"/></svg></span>')

def _v40_next_event_html(text,tone):
    safe=html.escape(str(text)); tc="" if tone=="normal" else f" {tone}"
    if " in " in str(text):
        prefix,metric=str(text).rsplit(" ",1); return f'<div class="lab-cell"><div class="lab-mini-label">Next event</div><div class="lab-next-caption">{html.escape(prefix)}</div><div class="lab-next-time{tc}">{html.escape(metric)}</div></div>'
    cls=f"lab-primary-text {tone}" if tone!="normal" else "lab-primary-text"; return f'<div class="lab-cell"><div class="lab-mini-label">Next event</div><div class="{cls}">{safe}</div></div>'

def render_mouse_row(i,wall_now,finished=False):
    now=effective_now(i,wall_now); exp_start=st.session_state.get(f"experiment_start_{i}"); total=elapsed_from(exp_start,now) if exp_start is not None else 0.0
    with st.container(key=f"mouse_row_{i}"):
        st.markdown(f'<span class="v40-row-state" data-v40-finished="{"true" if finished else "false"}"></span>',unsafe_allow_html=True); cols=st.columns([1.42,1.18,.78,3.32,1.92,1.62],gap="small",vertical_alignment="center")
        with cols[0]:
            tone=mouse_status_tone(i,now); paused=""
            if is_paused(i):
                ps=st.session_state.get(f"pause_started_{i}"); paused=f'<div class="lab-paused-label">Paused {format_timer(elapsed_from(ps,wall_now) if ps else 0)}</div>'
            st.markdown(f'<div class="lab-mouse-wrap"><span class="lab-dot {tone}"></span><div class="lab-mouse-identity">{_v40_mouse_icon()}<div style="min-width:0">{paused}<div class="lab-mouse-name">{html.escape(subject_name(i))}</div></div></div></div>',unsafe_allow_html=True)
        with cols[1]:
            text,tone=get_next_event_display(i,now); st.markdown(_v40_next_event_html(text,tone),unsafe_allow_html=True)
        with cols[2]: st.markdown(f'<div class="lab-cell"><div class="lab-mini-label">Total</div><div class="lab-total">{format_total_elapsed(total)}</div></div>',unsafe_allow_html=True)
        with cols[3]: st.markdown(workflow_html(i,now),unsafe_allow_html=True)
        with cols[4]:
            p,s,t=anesthesia_display(i,now); st.markdown('<div class="lab-mini-label" style="margin-top:.06rem;">Anesthesia</div>',unsafe_allow_html=True); st.markdown(html_cell(p,s,t),unsafe_allow_html=True); render_anesthesia_controls(i)
        with cols[5]:
            actions=st.columns([1,.28],gap="small")
            with actions[0]: render_primary_action(i,now)
            with actions[1]: render_overflow_control(i,now)

@st.fragment(run_every=REFRESH_INTERVAL)
def show_timers():
    if st.session_state.get("_pending_dialog"): st.rerun()
    if st.session_state.pop("_needs_full_rerun",False): st.rerun()
    wall_now=time.time(); render_attention_snapshot(collect_attention_items(wall_now)); active=[]; completed=[]
    for i in ordered_subject_indices(): (completed if mouse_is_complete(i,effective_now(i,wall_now)) else active).append(i)
    for i in active: render_mouse_row(i,wall_now,False)
    with st.container(key="add_mouse_card"): st.button("⊕  + Add mouse",key="add_mouse_subject",use_container_width=True,on_click=request_add_mouse_dialog)
    if completed:
        st.markdown('<div class="lab-completed-section-title">Completed / Ended</div>',unsafe_allow_html=True)
        for i in completed: render_mouse_row(i,wall_now,True)

# ============================================================
# ENTRY POINT
# ============================================================

initialize_state()

if not st.session_state.get("_active_experiment_id"):
    render_experiment_home(); st.stop()

retry_unsaved_subjects()
if st.session_state.get("_pending_weight_warning"): weight_warning_dialog()
else: render_pending_dialog()
render_pending_auto_download_marker(); install_browser_helpers()

header=st.columns([1.02,4.10,.90,.88,1.42,1.22,.88],vertical_alignment="center")
with header[0]:
    if st.button("← Experiments",key="back_to_experiments",use_container_width=True): return_to_experiment_home()
with header[1]:
    exp_name=html.escape(str(st.session_state.get("_active_experiment_name","Experiment"))); st.markdown(f'<div class="lab-header-title">{exp_name}</div><div class="lab-header-subtitle">{mouse_count()} mice · persistent session</div>',unsafe_allow_html=True)
with header[2]: st.button("⛶ Full screen",key="fullscreen_view",use_container_width=True)
with header[3]:
    available=global_undo_available(); target=global_undo_label(); help_text=f"Undo: {target}" if available else "No action available to undo"
    if st.button("↶ Undo",key=f"global_undo_{global_undo_token()}",use_container_width=True,disabled=not available,help=help_text): global_undo_last_action(); st.rerun()
with header[4]: st.download_button("⇩ Export timesheets",data=build_all_timesheets_text(),file_name=f"shock_timer_timesheets_{wall_datetime().strftime('%Y-%m-%d')}.txt",mime="text/plain",key="export_timesheets",use_container_width=True)
with header[5]:
    if st.button("■ End all subjects",key="end_all_subjects",use_container_width=True): end_all_subjects_dialog()
with header[6]:
    if st.button("⚙ Settings",key="open_settings",use_container_width=True): settings_dialog()

if st.session_state.get("_storage_error"): st.error("SAVE WARNING: recent changes have not been confirmed by persistent storage. "+str(st.session_state["_storage_error"]))
st.markdown('<div class="lab-divider"></div>',unsafe_allow_html=True)
show_timers()
