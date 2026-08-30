"""Shock Timer

Multi-subject experiment timer with persistent experiment state, audit-safe undo,
MAP capture, anesthesia tracking, exported timesheets, and a compact Streamlit UI.

Maintenance notes
-----------------
* TESTING_MODE is the single production/testing switch.
* Subject state lives in ``st.session_state`` and is persisted as JSON per mouse.
* Timer callbacks record global undo snapshots before mutating persistent state.
* Browser-side JavaScript is limited to UI behavior that Streamlit cannot provide
  directly (attention highlighting, fullscreen handling, scheduled alert audio,
  and automatic downloads).
* Visual CSS is intentionally installed once in cascade order. Keeping a single
  style element reduces Streamlit DOM overhead while preserving the exact rule
  precedence of prior versions.
* Refactor pass removes shadowed function definitions, centralizes repeated
  state/event rules, and avoids duplicate export-time event parsing while preserving
  database schema, widget keys, session payload names, and visible behavior.
"""

import base64
import html
import io
import json
import math
import os
import random
import re
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

# ============================================================
# APP SETTINGS.
# ============================================================

# Change ONLY this line to switch modes:
TESTING_MODE = False

# Production uses minutes. Testing uses the same numeric durations as seconds.
TIME_UNIT = "seconds" if TESTING_MODE else "minutes"
REFRESH_INTERVAL = 1.0

DEFAULT_INITIAL_ANESTHESIA = 45
DEFAULT_SUBSEQUENT_ANESTHESIA = 30
DEFAULT_ANESTHESIA_DELAY = 5
DEFAULT_NOTIFICATION_SOUND_ENABLED = True
DEFAULT_NOTIFICATION_SOUND = "Chime"
NOTIFICATION_SOUND_OPTIONS = ["Chime", "Beep", "Double beep"]

# Both the initial anesthetic and each redose are administered at 0.01 mL/g.
# They are summarized separately in exports because they come from different vials.
ANESTHESIA_DOSE_VOLUME_ML_PER_G = 0.01

FIXED_BOARD_DURATION = 10
FIXED_SHOCK_DURATION = 60
FIXED_RESUSCITATION_DURATION = 20

INITIAL_MOUSE_COUNT = 8
WARNING_UNITS = 1
APP_TIMEZONE = "America/New_York"
STATE_VERSION = "lab_multitimer_v70_reliability_preflight"

UNIT_SECONDS = 1.0 if TIME_UNIT == "seconds" else 60.0
UNIT_SHORT = "s" if TIME_UNIT == "seconds" else "m"
UNIT_LABEL = "sec" if TIME_UNIT == "seconds" else "min"
UNIT_WORD = "seconds" if TIME_UNIT == "seconds" else "minutes"
TEST_WEIGHT_MIN_G = 22.0
TEST_WEIGHT_MAX_G = 35.0

# Reused immutable objects / layout definitions. Keeping these centralized makes
# the UI easier to tune without scattering numeric column ratios through the app.
APP_TZ = ZoneInfo(APP_TIMEZONE)
RUNNING_ROW_COLUMNS = [1.38, 1.14, 0.74, 3.22, 1.96, 0.18, 1.58]
RUNNING_ACTION_COLUMNS = [1.0, 0.28]
HEADER_COLUMNS = [1.02, 4.10, 0.90, 0.88, 1.42, 1.22, 0.88]
CONFIGURATION_COLUMNS = [0.58, 3.52, 1.58, 0.58]

# Event/state groups used in several timer and audit paths. Centralizing these
# avoids subtle drift between UI validation, corrections, and pause handling.
ANESTHESIA_EVENT_NAMES = ("Anesthesia started", "Anesthesia redosed")
BACKTIME_EDITABLE_EVENTS = frozenset(
    (*ANESTHESIA_EVENT_NAMES, "Board acclimation started", "Shock started", "Resuscitation started")
)
PAUSE_SHIFT_FIELDS = (
    "experiment_start",
    "anesthesia_start",
    "board_start",
    "shock_start",
    "resus_start",
    "anesthesia_due_override",
)

st.set_page_config(
    page_title="Shock Timer",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# VISUAL SYSTEM
# ============================================================

# All historical UI rules are retained in their original cascade order, but are
# injected as one style element instead of 16 separate Streamlit markdown nodes.
# This reduces frontend DOM work on every rerun without changing visual behavior.
APP_CSS = r"""
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

    .st-key-configuration_table [data-testid="stVerticalBlock"]{gap:.16rem!important}
    .st-key-configuration_table input,.st-key-configuration_table button{min-height:2.35rem!important;height:2.35rem!important}
    .st-key-configuration_table .lab-config-header{
        display:flex!important;align-items:flex-end!important;min-height:1.45rem!important;
        padding:.18rem .08rem .34rem!important;margin:0!important;line-height:1.15!important;
        position:relative!important;z-index:5!important;overflow:visible!important;white-space:nowrap!important;
    }
    .st-key-configuration_table [data-testid="stMarkdownContainer"]:has(.lab-config-header),
    .st-key-configuration_table [data-testid="stMarkdown"]:has(.lab-config-header){
        min-height:1.45rem!important;overflow:visible!important;
    }
    div[class*="st-key-delete_exp_confirm_"] button,div[class*="st-key-end_exp_confirm_"] button,div[class*="st-key-end_confirm_"] button,div[class*="st-key-reset_confirm_"] button,div[class*="st-key-end_all_confirm"] button{
        background:linear-gradient(180deg,rgba(185,55,75,.96),rgba(139,38,55,.96))!important;border-color:rgba(239,101,120,.72)!important;color:#fff!important}
    #lab-attention-v40{left:1.35rem!important;right:1.35rem!important;bottom:1rem!important;padding:.72rem .92rem!important;border-radius:11px!important;background:rgba(11,20,30,.97)!important;border:1px solid rgba(245,161,38,.30)!important;box-shadow:0 16px 48px rgba(0,0,0,.36)!important;color:#e8edf2!important;font:650 13px/1.25 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important}
    #lab-attention-v40 .orange{color:#ffc169!important}#lab-attention-v40 .red{color:#ff9cab!important}#lab-attention-v40 .x{color:#99a6b3!important;cursor:pointer;float:right}
    @media(max-width:1180px){.stMainBlockContainer{min-width:1140px}}

    .stMainBlockContainer{
        padding:.62rem 1.20rem 4.75rem!important;
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

    [data-testid="stVerticalBlock"]{gap:.34rem}
    [data-testid="stHorizontalBlock"]{gap:.52rem}

    .lab-header-title{
        font-size:1.58rem!important;
        line-height:1.00!important;
    }
    .lab-header-subtitle{
        font-size:.74rem!important;
        margin-top:.16rem!important;
    }
    .lab-divider{
        margin:.44rem 0 .42rem!important;
    }

    div[class*="st-key-back_to_experiments"] button,
    div[class*="st-key-fullscreen_view"] button,
    div[class*="st-key-global_undo_"] button,
    div[class*="st-key-open_settings"] button,
    div[class*="st-key-export_timesheets"] button,
    div[class*="st-key-end_all_subjects"] button{
        min-height:2.55rem!important;
        height:2.55rem!important;
        font-size:.78rem!important;
        padding-top:0!important;
        padding-bottom:0!important;
    }

    div[class*="st-key-mouse_row_"]{
        padding:.42rem .78rem!important;
        margin-bottom:.08rem!important;
        border-radius:10px!important;
    }

    div[class*="st-key-mouse_row_"] [data-testid="stVerticalBlock"]{
        gap:.10rem!important;
    }
    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"]{
        gap:.42rem!important;
    }

    .lab-cell{
        min-height:3.70rem!important;
        padding:0 .02rem!important;
    }

    .lab-mouse-wrap{
        min-height:3.70rem!important;
        gap:.42rem!important;
    }
    .lab-mouse-identity{gap:.46rem!important}
    .lab-mouse-icon{
        width:1.70rem!important;
        height:1.70rem!important;
    }
    .lab-dot{
        width:.54rem!important;
        height:.54rem!important;
    }
    .lab-mouse-name{
        font-size:.91rem!important;
    }
    .lab-paused-label{
        font-size:.54rem!important;
        margin-bottom:.10rem!important;
    }

    .lab-mini-label{
        font-size:.55rem!important;
        margin-bottom:.24rem!important;
    }
    .lab-primary-text{
        font-size:.79rem!important;
        line-height:1.08!important;
    }
    .lab-secondary-text{
        font-size:.63rem!important;
        margin-top:.14rem!important;
        line-height:1.05!important;
    }
    .lab-next-caption{
        font-size:.74rem!important;
    }
    .lab-next-time{
        margin-top:.18rem!important;
        font-size:.98rem!important;
    }
    .lab-total{
        font-size:.82rem!important;
    }

    .lab-stepper{
        padding:.02rem .04rem 0!important;
    }
    .lab-step:not(:last-child)::after{
        top:.60rem!important;
        left:calc(50% + .69rem)!important;
        right:calc(-50% + .69rem)!important;
        height:1.5px!important;
    }
    .lab-step-circle{
        width:1.20rem!important;
        height:1.20rem!important;
        font-size:.59rem!important;
    }
    .lab-step-label{
        font-size:.63rem!important;
        margin-top:.18rem!important;
        line-height:1.00!important;
    }
    .lab-step-time{
        min-height:.62rem!important;
        margin-top:.08rem!important;
        font-size:.61rem!important;
        line-height:1.00!important;
    }

    .lab-anesthesia-copy{
        display:flex;
        flex-direction:column;
        justify-content:flex-end;
        min-height:2.20rem;
        margin:0;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        min-height:1.82rem!important;
        height:1.82rem!important;
        margin-top:.04rem!important;
        padding:0 .36rem!important;
        border-radius:7px!important;
        font-size:.65rem!important;
    }

    div[class*="st-key-primary_action_"] button,
    div[class*="st-key-primary_pause_"] button,
    div[class*="st-key-primary_start_anesthesia_"] button,
    div[class*="st-key-primary_start_anesthesia_wrapper_"] button{
        min-height:2.55rem!important;
        height:2.55rem!important;
        font-size:.78rem!important;
    }

    div[class*="st-key-mouse_action_menu_"] button{
        min-height:2.55rem!important;
        height:2.55rem!important;
        min-width:2.35rem!important;
        font-size:.93rem!important;
    }

    div[class*="st-key-add_mouse_card"] button{
        min-height:2.85rem!important;
        height:2.85rem!important;
        font-size:.78rem!important;
        border-radius:9px!important;
    }

    .lab-completed-section-title{
        margin-top:.38rem!important;
        padding:.48rem .10rem .08rem!important;
        font-size:.58rem!important;
    }

    @media (min-height:1050px){
        div[class*="st-key-mouse_row_"]{padding:.48rem .82rem!important}
        .lab-cell,.lab-mouse-wrap{min-height:3.92rem!important}
    }

    .home-brand {
        display:flex;
        align-items:center;
        gap:.72rem;
        margin:.18rem 0 .08rem;
    }
    .home-brand-icon {
        width:2.15rem;
        height:2.15rem;
        flex:0 0 auto;
        display:grid;
        place-items:center;
        border:1px solid rgba(137,160,184,.22);
        border-radius:50%;
        background:linear-gradient(180deg,rgba(20,34,49,.88),rgba(12,22,33,.88));
        color:#f5a126;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.025);
    }
    .home-brand-icon svg {
        width:1.28rem;
        height:1.28rem;
        fill:none;
        stroke:currentColor;
        stroke-width:1.7;
        stroke-linecap:round;
        stroke-linejoin:round;
    }
    .home-brand-title {
        color:#f7f9fb;
        font-size:1.58rem;
        line-height:1;
        font-weight:780;
        letter-spacing:-.04em;
    }
    .home-brand-subtitle {
        color:#8492a1;
        font-size:.76rem;
        margin-top:.22rem;
    }

    div[class*="st-key-home_cloud_warning"] [data-testid="stAlert"] {
        min-height:auto!important;
        padding:.52rem .72rem!important;
        margin:.18rem 0 .10rem!important;
        background:rgba(75,45,16,.32)!important;
        border:1px solid rgba(245,161,38,.32)!important;
        color:#ffd49a!important;
    }
    div[class*="st-key-home_cloud_warning"] [data-testid="stAlert"] p {
        font-size:.75rem!important;
        line-height:1.18!important;
    }

    div[class*="st-key-home_new_experiment"],
    div[class*="st-key-home_active_section"],
    div[class*="st-key-home_completed_section"] {
        position:relative;
        overflow:hidden;
        background:
            radial-gradient(circle at 45% -115%,rgba(72,105,139,.11),transparent 52%),
            linear-gradient(180deg,rgba(18,31,45,.94),rgba(12,22,33,.94))!important;
        border:1px solid rgba(137,160,184,.20)!important;
        border-radius:11px!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.020),0 5px 18px rgba(0,0,0,.06)!important;
    }

    div[class*="st-key-home_new_experiment"] {
        padding:.76rem .90rem .70rem!important;
        margin-top:.68rem!important;
        margin-bottom:.46rem!important;
    }
    div[class*="st-key-home_active_section"],
    div[class*="st-key-home_completed_section"] {
        padding:.72rem .90rem .78rem!important;
        margin-top:.08rem!important;
        margin-bottom:.44rem!important;
    }

    div[class*="st-key-home_new_experiment"] [data-testid="stVerticalBlock"],
    div[class*="st-key-home_active_section"] [data-testid="stVerticalBlock"],
    div[class*="st-key-home_completed_section"] [data-testid="stVerticalBlock"] {
        gap:.34rem!important;
    }

    .home-section-title {
        color:#f2f5f8;
        font-size:1.01rem;
        line-height:1.08;
        font-weight:735;
        letter-spacing:-.018em;
        margin:.02rem 0 .32rem;
    }
    .home-section-count {
        color:#748393;
        font-size:.66rem;
        font-weight:650;
        margin-left:.34rem;
    }

    div[class*="st-key-home_new_experiment"] [data-testid="stForm"] {
        padding:0!important;
        border:0!important;
        background:transparent!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stWidgetLabel"] p {
        font-size:.68rem!important;
        color:#aeb9c4!important;
        margin-bottom:.12rem!important;
    }
    div[class*="st-key-home_new_experiment"] input {
        min-height:2.62rem!important;
        height:2.62rem!important;
        font-size:.78rem!important;
        border-radius:8px!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stNumberInput"] button {
        min-height:2.62rem!important;
        height:2.62rem!important;
        width:2.48rem!important;
        border-radius:0!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stFormSubmitButton"] button {
        min-height:2.62rem!important;
        height:2.62rem!important;
        margin-top:0!important;
        border-radius:8px!important;
        border-color:rgba(245,161,38,.82)!important;
        background:linear-gradient(180deg,#ec961c,#c87309)!important;
        color:#fff7eb!important;
        font-size:.80rem!important;
        font-weight:735!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 7px 18px rgba(245,161,38,.10)!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stFormSubmitButton"] button:hover {
        background:linear-gradient(180deg,#f2a128,#d27b0c)!important;
        border-color:#ffad36!important;
    }

    div[class*="st-key-home_exp_card_"] {
        background:linear-gradient(180deg,rgba(13,24,36,.68),rgba(10,19,29,.68))!important;
        border:1px solid rgba(137,160,184,.16)!important;
        border-radius:9px!important;
        padding:.43rem .58rem!important;
        margin:.08rem 0!important;
        box-shadow:none!important;
    }
    div[class*="st-key-home_exp_card_"] [data-testid="stVerticalBlock"] {
        gap:.08rem!important;
    }
    div[class*="st-key-home_exp_card_"] [data-testid="stHorizontalBlock"] {
        gap:.38rem!important;
    }

    .home-exp-info {
        display:flex;
        align-items:center;
        gap:.62rem;
        min-height:2.66rem;
        min-width:0;
    }
    .home-exp-status {
        width:.50rem;
        height:.50rem;
        border-radius:50%;
        flex:0 0 auto;
        background:#5ed276;
        box-shadow:0 0 0 3px rgba(94,210,118,.055);
    }
    .home-exp-status.completed {
        width:1.08rem;
        height:1.08rem;
        display:grid;
        place-items:center;
        color:#72869a;
        background:transparent;
        border:1.5px solid rgba(114,134,154,.64);
        box-shadow:none;
        font-size:.66rem;
        font-weight:800;
    }
    .home-exp-text {
        min-width:0;
    }
    .home-exp-name {
        color:#edf2f6;
        font-size:.82rem;
        line-height:1.05;
        font-weight:720;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
    }
    .home-exp-meta {
        color:#7f8e9e;
        font-size:.67rem;
        line-height:1.06;
        margin-top:.20rem;
        white-space:nowrap;
        overflow:hidden;
        text-overflow:ellipsis;
    }

    div[class*="st-key-home_exp_card_"] .stButton>button {
        min-height:2.30rem!important;
        height:2.30rem!important;
        padding:0 .50rem!important;
        border-radius:8px!important;
        font-size:.72rem!important;
        font-weight:650!important;
        background:linear-gradient(180deg,rgba(19,32,46,.86),rgba(13,23,34,.86))!important;
        border-color:rgba(137,160,184,.21)!important;
        box-shadow:none!important;
    }
    div[class*="st-key-home_exp_card_"] .stButton>button:hover {
        background:linear-gradient(180deg,rgba(25,42,59,.92),rgba(16,28,41,.92))!important;
        border-color:rgba(152,178,204,.36)!important;
    }

    div[class*="st-key-home_delete_"] button {
        color:#ff8e9e!important;
        border-color:rgba(239,101,120,.52)!important;
        background:rgba(239,101,120,.025)!important;
    }
    div[class*="st-key-home_delete_"] button:hover {
        color:#ffadba!important;
        border-color:rgba(239,101,120,.72)!important;
        background:rgba(239,101,120,.07)!important;
    }

    .home-empty-state {
        color:#718090;
        font-size:.72rem;
        padding:.42rem .10rem .26rem;
    }

    div[class*="st-key-home_new_experiment"] [data-testid="stAlert"] {
        padding:.48rem .64rem!important;
        margin-top:.18rem!important;
    }

    @media(max-width:1180px) {
        .home-exp-meta { font-size:.63rem; }
    }

    .home-brand-title{
        font-size:1.74rem!important;
        line-height:1.00!important;
    }
    .home-brand-subtitle{
        font-size:.82rem!important;
        margin-top:.20rem!important;
    }
    .home-section-title{
        font-size:1.08rem!important;
        margin:.02rem 0 .36rem!important;
    }
    .home-section-count{
        font-size:.72rem!important;
    }

    div[class*="st-key-home_new_experiment"]{
        padding:.84rem .98rem .78rem!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stWidgetLabel"] p{
        font-size:.73rem!important;
        font-weight:660!important;
        color:#bcc7d1!important;
        margin-bottom:.15rem!important;
    }
    div[class*="st-key-home_new_experiment"] input{
        min-height:2.74rem!important;
        height:2.74rem!important;
        font-size:.86rem!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stNumberInput"] button{
        min-height:2.74rem!important;
        height:2.74rem!important;
        width:2.58rem!important;
    }
    div[class*="st-key-home_new_experiment"] [data-testid="stFormSubmitButton"] button{
        min-height:2.74rem!important;
        height:2.74rem!important;
        font-size:.92rem!important;
        font-weight:745!important;
        padding:0 .78rem!important;
    }

    .home-exp-name{
        font-size:.90rem!important;
    }
    .home-exp-meta{
        font-size:.72rem!important;
        margin-top:.22rem!important;
    }
    div[class*="st-key-home_exp_card_"]{
        padding:.48rem .64rem!important;
    }
    div[class*="st-key-home_exp_card_"] .stButton>button{
        min-height:2.22rem!important;
        height:2.22rem!important;
        font-size:.78rem!important;
        font-weight:665!important;
        padding:0 .52rem!important;
    }

    .cfg-dialog-name{
        color:#eef3f7!important;
        font-size:1.02rem!important;
        font-weight:740!important;
        line-height:1.10!important;
        margin:.12rem 0 .12rem!important;
    }
    .cfg-dialog-subtitle{
        color:#8492a1!important;
        font-size:.76rem!important;
        line-height:1.26!important;
        margin:0 0 .54rem!important;
    }

    .st-key-configuration_table [data-testid="stVerticalBlock"]{
        gap:.18rem!important;
    }
    .st-key-configuration_table input,
    .st-key-configuration_table button{
        min-height:2.38rem!important;
        height:2.38rem!important;
    }
    .st-key-configuration_table input{
        font-size:.84rem!important;
    }
    .st-key-configuration_table .lab-config-header{
        color:#93a2b1!important;
        font-size:.64rem!important;
        font-weight:760!important;
        letter-spacing:.08em!important;
        text-transform:uppercase!important;
        display:flex!important;
        align-items:flex-end!important;
        min-height:1.18rem!important;
        padding:.06rem .08rem .20rem!important;
        margin:0!important;
        white-space:nowrap!important;
    }

    div[class*="st-key-cfg_row_card_"]{
        background:linear-gradient(180deg,rgba(13,24,36,.66),rgba(10,19,29,.66))!important;
        border:1px solid rgba(137,160,184,.15)!important;
        border-radius:9px!important;
        padding:.22rem .26rem!important;
        margin:.02rem 0!important;
    }
    div[class*="st-key-cfg_row_card_"] [data-testid="stVerticalBlock"]{
        gap:.06rem!important;
    }
    div[class*="st-key-cfg_row_card_"] [data-testid="stHorizontalBlock"]{
        gap:.34rem!important;
    }

    .cfg-row-index{
        color:#edf2f6!important;
        font-size:.80rem!important;
        font-weight:730!important;
        min-height:2.32rem!important;
        display:flex!important;
        align-items:center!important;
        padding-left:.08rem!important;
    }

    div[class*="st-key-cfg_remove_wrap_"] button{
        min-height:2.32rem!important;
        height:2.32rem!important;
        border-radius:8px!important;
        font-size:.98rem!important;
        font-weight:720!important;
    }

    div[class*="st-key-cfg_add_mouse_wrap"] button{
        min-height:2.86rem!important;
        height:2.86rem!important;
        border-radius:9px!important;
        border:1px dashed rgba(137,160,184,.28)!important;
        background:linear-gradient(180deg,rgba(17,29,42,.44),rgba(11,21,31,.44))!important;
        color:#e2e8ee!important;
        font-size:.85rem!important;
        font-weight:690!important;
    }

    div[class*="st-key-cfg_cancel_wrap"] button,
    div[class*="st-key-cfg_start_wrap"] button{
        min-height:2.82rem!important;
        height:2.82rem!important;
        border-radius:9px!important;
        font-size:.88rem!important;
        font-weight:710!important;
    }
    div[class*="st-key-cfg_start_wrap"] button{
        border-color:rgba(245,161,38,.82)!important;
        background:linear-gradient(180deg,#ec961c,#c87309)!important;
        color:#fff7eb!important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,.10),0 7px 18px rgba(245,161,38,.10)!important;
    }
    div[class*="st-key-cfg_start_wrap"] button:hover{
        background:linear-gradient(180deg,#f2a128,#d27b0c)!important;
        border-color:#ffad36!important;
    }

    [data-testid="stDialog"] [role="dialog"]{
        padding-top:.18rem!important;
    }

    div[class*="st-key-cfg_dialog_intro"]{
        margin:.08rem 0 .46rem!important;
        padding:.02rem 0 .04rem!important;
    }
    .cfg-dialog-expname{
        color:#eef3f7!important;
        font-size:1.06rem!important;
        font-weight:760!important;
        line-height:1.14!important;
        letter-spacing:-.01em!important;
        margin:0 0 .16rem!important;
    }
    .cfg-dialog-subcopy{
        color:#8492a1!important;
        font-size:.77rem!important;
        line-height:1.28!important;
        margin:0!important;
    }

    .st-key-configuration_table [data-testid="stVerticalBlock"]{
        gap:.20rem!important;
    }
    .st-key-configuration_table [data-testid="stHorizontalBlock"]{
        gap:.42rem!important;
    }
    .st-key-configuration_table .lab-config-header{
        min-height:1.08rem!important;
        padding:.02rem .14rem .16rem!important;
        margin:0 0 .02rem!important;
        color:#96a4b3!important;
        font-size:.65rem!important;
        font-weight:760!important;
        letter-spacing:.08em!important;
        text-transform:uppercase!important;
        display:flex!important;
        align-items:flex-end!important;
    }

    div[class*="st-key-cfg_row_shell_"]{
        background:linear-gradient(180deg,rgba(13,24,36,.66),rgba(10,19,29,.66))!important;
        border:1px solid rgba(137,160,184,.15)!important;
        border-radius:10px!important;
        padding:.22rem .26rem!important;
        margin:.03rem 0!important;
    }

    .cfg-index-cell{
        min-height:2.42rem!important;
        display:flex!important;
        align-items:center!important;
        justify-content:flex-start!important;
        padding-left:.18rem!important;
        color:#edf2f6!important;
        font-size:.86rem!important;
        font-weight:740!important;
        line-height:1!important;
    }

    .st-key-configuration_table input,
    .st-key-configuration_table button{
        min-height:2.42rem!important;
        height:2.42rem!important;
    }
    .st-key-configuration_table input{
        font-size:.85rem!important;
    }

    div[class*="st-key-cfg_remove_wrap_"] button{
        min-height:2.42rem!important;
        height:2.42rem!important;
        border-radius:8px!important;
        font-size:1.02rem!important;
        font-weight:720!important;
        padding:0!important;
    }

    div[class*="st-key-cfg_add_mouse_wrap"]{
        margin-top:.10rem!important;
        margin-bottom:.10rem!important;
    }
    div[class*="st-key-cfg_add_mouse_wrap"] button{
        min-height:2.94rem!important;
        height:2.94rem!important;
        border-radius:10px!important;
        border:1px dashed rgba(137,160,184,.28)!important;
        background:linear-gradient(180deg,rgba(17,29,42,.44),rgba(11,21,31,.44))!important;
        color:#e2e8ee!important;
        font-size:.86rem!important;
        font-weight:700!important;
    }

    div[class*="st-key-cfg_cancel_wrap"] button,
    div[class*="st-key-cfg_start_wrap"] button{
        min-height:2.90rem!important;
        height:2.90rem!important;
        border-radius:10px!important;
        font-size:.89rem!important;
        font-weight:720!important;
    }

    [data-testid="stDialog"] [role="dialog"]{
        padding-top:.22rem!important;
    }

    .lab-anesthesia-copy{
        min-height:2.28rem!important;
        margin:0 0 .24rem 0!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        margin-top:.08rem!important;
    }

    div[class*="st-key-anesthesia_redose_action_"],
    div[class*="st-key-anesthesia_delay_action_"]{
        padding-top:.02rem!important;
        padding-bottom:.02rem!important;
    }

    .lab-anesthesia-copy{
        display:grid!important;
        grid-template-rows:auto auto auto!important;
        row-gap:.12rem!important;
        min-height:0!important;
        height:auto!important;
        justify-content:stretch!important;
        align-content:start!important;
        margin:0!important;
        padding:0 0 .24rem 0!important;
        overflow:visible!important;
    }

    .lab-anesthesia-copy .lab-mini-label{
        margin:0!important;
        padding:0!important;
        line-height:1.05!important;
    }

    .lab-anesthesia-copy .lab-primary-text{
        margin:0!important;
        padding:0!important;
        line-height:1.16!important;
        white-space:nowrap!important;
    }

    .lab-anesthesia-weight{
        color:#7f8c9a!important;
        font-size:.65rem!important;
        font-weight:560!important;
        line-height:1.12!important;
        margin:0!important;
        padding:0!important;
        white-space:nowrap!important;
    }

    div[class*="st-key-anesthesia_controls_"]{
        margin-top:.18rem!important;
        padding-top:.08rem!important;
        padding-bottom:.02rem!important;
    }

    div[class*="st-key-anesthesia_controls_"] [data-testid="stHorizontalBlock"]{
        gap:.58rem!important;
    }

    div[class*="st-key-anesthesia_redose_action_"],
    div[class*="st-key-anesthesia_delay_action_"]{
        padding:0!important;
        margin:0!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        margin:0!important;
        min-height:1.90rem!important;
        height:1.90rem!important;
    }

    .lab-subject-copy{
        min-width:0!important;
        display:flex!important;
        flex-direction:column!important;
        justify-content:center!important;
    }

    .lab-starting-map{
        color:#7f8d9b!important;
        font-size:.61rem!important;
        font-weight:600!important;
        line-height:1.08!important;
        margin-top:.16rem!important;
        white-space:nowrap!important;
    }

    .lab-anesthesia-copy{
        display:block!important;
        min-height:0!important;
        height:auto!important;
        margin:0!important;
        padding:0 0 .30rem 0!important;
        overflow:visible!important;
    }

    .lab-anesthesia-copy .lab-mini-label{
        margin:0 0 .18rem 0!important;
        padding:0!important;
        line-height:1!important;
    }

    .lab-anesthesia-status-row{
        display:flex!important;
        align-items:baseline!important;
        justify-content:space-between!important;
        gap:.55rem!important;
        width:100%!important;
        min-width:0!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-anesthesia-status-row .lab-primary-text{
        min-width:0!important;
        flex:1 1 auto!important;
        margin:0!important;
        padding:0!important;
        line-height:1.10!important;
        white-space:nowrap!important;
        overflow:hidden!important;
        text-overflow:ellipsis!important;
    }

    .lab-anesthesia-weight-inline{
        flex:0 0 auto!important;
        margin-left:auto!important;
        padding:0!important;
        color:#7f8c9a!important;
        font-size:.64rem!important;
        font-weight:580!important;
        line-height:1!important;
        white-space:nowrap!important;
        text-align:right!important;
    }

    .lab-anesthesia-weight{
        display:none!important;
    }

    div[class*="st-key-anesthesia_controls_"]{
        margin-top:.20rem!important;
        padding-top:.04rem!important;
        padding-bottom:.02rem!important;
    }

    div[class*="st-key-anesthesia_controls_"] [data-testid="stHorizontalBlock"]{
        gap:.56rem!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        margin:0!important;
    }

    .lab-anesthesia-weight-inline{
        color:#eef2f5!important;
        font-size:.79rem!important;
        font-weight:680!important;
        line-height:1.10!important;
        white-space:nowrap!important;
        text-align:right!important;
    }

    .lab-anesthesia-copy{
        padding-bottom:.52rem!important;
    }

    div[class*="st-key-anesthesia_controls_"]{
        margin-top:.28rem!important;
        padding-top:.06rem!important;
    }

    .lab-anesthesia-copy{
        padding-bottom:.72rem!important;
    }

    div[class*="st-key-anesthesia_controls_"]{
        margin-top:.34rem!important;
        padding-top:.06rem!important;
        padding-bottom:.02rem!important;
    }

    div[class*="st-key-anesthesia_controls_"] [data-testid="stHorizontalBlock"]{
        gap:.48rem!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        min-height:1.66rem!important;
        height:1.66rem!important;
        padding:0 .30rem!important;
        border-radius:7px!important;
        font-size:.62rem!important;
        font-weight:680!important;
        margin:0!important;
    }

    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1),
    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2),
    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3){
        align-self:stretch!important;
        display:flex!important;
        flex-direction:column!important;
        justify-content:center!important;
    }

    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(1) > [data-testid="stVerticalBlock"],
    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) > [data-testid="stVerticalBlock"],
    div[class*="st-key-mouse_row_"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(3) > [data-testid="stVerticalBlock"]{
        height:100%!important;
        justify-content:center!important;
    }

    .lab-mouse-wrap,
    .lab-cell{
        justify-content:center!important;
        margin-top:auto!important;
        margin-bottom:auto!important;
    }

    .lab-starting-map{
        color:#aab6c2!important;
        font-size:.73rem!important;
        font-weight:680!important;
        line-height:1.12!important;
        margin-top:.22rem!important;
    }

    .lab-starting-map{
        min-height:.82rem!important;
        height:.82rem!important;
        display:block!important;
        margin-top:.20rem!important;
        font-size:.73rem!important;
        line-height:.82rem!important;
    }

    .lab-starting-map-placeholder{
        visibility:hidden!important;
        user-select:none!important;
    }

    div[class*="st-key-overdue_sound_"],
    div[class*="st-key-hidden_audio_"]{
        position:absolute!important;
        width:1px!important;
        height:1px!important;
        overflow:hidden!important;
        opacity:.001!important;
        pointer-events:none!important;
    }

    div[class*="st-key-overdue_sound_"] audio,
    div[class*="st-key-hidden_audio_"] audio{
        width:1px!important;
        height:1px!important;
    }

    .lab-mouse-wrap{
        position:relative!important;
        align-items:center!important;
        justify-content:flex-start!important;
        margin-top:0!important;
        margin-bottom:0!important;
    }

    .lab-mouse-identity{
        align-items:center!important;
    }

    .lab-subject-copy{
        position:relative!important;
        display:flex!important;
        align-items:center!important;
        justify-content:center!important;
        min-height:1.20rem!important;
        height:1.20rem!important;
    }

    .lab-mouse-name{
        line-height:1.20rem!important;
        margin:0!important;
    }

    .lab-starting-map{
        position:absolute!important;
        top:1.30rem!important;
        left:0!important;
        margin:0!important;
        min-height:.82rem!important;
        height:.82rem!important;
        line-height:.82rem!important;
    }

    .lab-paused-label{
        position:absolute!important;
        bottom:1.28rem!important;
        left:0!important;
        margin:0!important;
    }

    .lab-next-event-cell,
    .lab-total-cell{
        position:relative!important;
        display:flex!important;
        flex-direction:column!important;
        justify-content:center!important;
        min-height:3.70rem!important;
        margin:0!important;
    }

    .lab-next-main,
    .lab-total{
        margin:0!important;
        padding:0!important;
        line-height:1.05!important;
    }

    .lab-next-single-label,
    .lab-total-cell > .lab-mini-label{
        position:absolute!important;
        left:0!important;
        bottom:calc(50% + .52rem)!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-overline{
        position:absolute!important;
        left:0!important;
        bottom:calc(50% + .48rem)!important;
        display:flex!important;
        flex-direction:column!important;
        gap:.10rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-overline .lab-mini-label,
    .lab-next-overline .lab-next-caption{
        margin:0!important;
        padding:0!important;
        line-height:1!important;
    }

    .lab-next-time{
        margin:0!important;
    }

    .lab-subject-copy{
        position:relative!important;
        display:flex!important;
        flex-direction:column!important;
        align-items:flex-start!important;
        justify-content:center!important;
        min-height:2.30rem!important;
        height:2.30rem!important;
        gap:.20rem!important;
    }

    .lab-mouse-name{
        line-height:1.08!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map{
        position:static!important;
        top:auto!important;
        left:auto!important;
        display:block!important;
        min-height:.80rem!important;
        height:.80rem!important;
        line-height:.80rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map-placeholder{
        visibility:hidden!important;
    }

    .lab-paused-label{
        position:absolute!important;
        left:0!important;
        bottom:2.38rem!important;
        margin:0!important;
    }

    .lab-next-event-cell{
        padding-left:.42rem!important;
        box-sizing:border-box!important;
    }

    .lab-next-overline{
        left:.42rem!important;
    }

    .lab-next-single-label{
        left:.42rem!important;
    }

    .lab-next-main{
        margin-left:.42rem!important;
    }

    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-orange)
    div[class*="st-key-anesthesia_redose_action_"] button{
        color:#ffd18a!important;
        border-color:#f5a126!important;
        background:rgba(245,161,38,.10)!important;
        box-shadow:0 0 0 1px rgba(245,161,38,.12)!important;
    }

    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-orange)
    .lab-anesthesia-status-row .lab-primary-text,
    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-orange)
    .lab-anesthesia-weight-inline{
        color:#ffc15f!important;
    }

    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-red)
    .lab-anesthesia-status-row .lab-primary-text,
    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-red)
    .lab-anesthesia-weight-inline{
        color:#ff8798!important;
        font-weight:760!important;
    }

    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-red)
    div[class*="st-key-anesthesia_redose_action_"] button{
        color:#fff1f3!important;
        border-color:#ef6578!important;
        background:linear-gradient(
            180deg,
            rgba(174,54,72,.86),
            rgba(119,35,49,.86)
        )!important;
        box-shadow:
            0 0 0 1px rgba(239,101,120,.20),
            0 5px 14px rgba(239,101,120,.12)!important;
    }

    div[class*="st-key-mouse_row_"]:has(.anesthesia-tone-red)
    div[class*="st-key-anesthesia_redose_action_"] button:hover{
        background:linear-gradient(
            180deg,
            rgba(194,62,81,.94),
            rgba(137,39,56,.94)
        )!important;
        border-color:#ff7d90!important;
    }

    .lab-mouse-wrap{
        min-height:3.20rem!important;
        display:flex!important;
        align-items:center!important;
        justify-content:flex-start!important;
        gap:.68rem!important;
        margin:0!important;
    }

    .lab-mouse-identity{
        display:flex!important;
        align-items:center!important;
        gap:.68rem!important;
    }

    .lab-subject-copy{
        position:relative!important;
        display:grid!important;
        grid-template-rows:1.08rem .86rem!important;
        align-content:center!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:2.34rem!important;
        height:2.34rem!important;
        margin:0!important;
    }

    .lab-mouse-name{
        align-self:end!important;
        line-height:1.06rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map{
        position:static!important;
        display:block!important;
        align-self:start!important;
        min-height:.86rem!important;
        height:.86rem!important;
        line-height:.86rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map-placeholder{
        visibility:hidden!important;
    }

    .lab-paused-label{
        position:absolute!important;
        left:0!important;
        bottom:2.46rem!important;
        margin:0!important;
    }

    .lab-next-event-cell{
        display:grid!important;
        grid-template-rows:auto auto!important;
        align-content:center!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:3.20rem!important;
        padding-left:.50rem!important;
        box-sizing:border-box!important;
        margin:0!important;
    }

    .lab-next-overline{
        position:static!important;
        left:auto!important;
        bottom:auto!important;
        display:flex!important;
        flex-direction:column!important;
        gap:.10rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-single-label{
        position:static!important;
        left:auto!important;
        bottom:auto!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-overline .lab-mini-label,
    .lab-next-overline .lab-next-caption,
    .lab-next-single-label{
        line-height:1.00!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-main{
        margin:0!important;
        padding:0!important;
        line-height:1.06!important;
    }

    .lab-total-cell{
        display:grid!important;
        grid-template-rows:auto auto!important;
        align-content:center!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:3.20rem!important;
        margin:0!important;
    }

    .lab-total-cell > .lab-mini-label{
        position:static!important;
        left:auto!important;
        bottom:auto!important;
        margin:0!important;
        padding:0!important;
        line-height:1.00!important;
    }

    .lab-total{
        margin:0!important;
        padding:0!important;
        line-height:1.06!important;
    }

    .lab-cell{
        margin-top:0!important;
        margin-bottom:0!important;
    }

    .lab-mouse-wrap{
        min-height:2.34rem!important;
        height:2.34rem!important;
        display:flex!important;
        align-items:flex-start!important;
        justify-content:flex-start!important;
        gap:.66rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-mouse-identity{
        min-height:2.34rem!important;
        height:2.34rem!important;
        display:flex!important;
        align-items:flex-start!important;
        gap:.66rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-subject-copy{
        display:grid!important;
        grid-template-rows:1.08rem .86rem!important;
        align-content:start!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:2.34rem!important;
        height:2.34rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-mouse-name{
        align-self:center!important;
        line-height:1.08rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map{
        position:static!important;
        align-self:center!important;
        min-height:.86rem!important;
        height:.86rem!important;
        line-height:.86rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-starting-map-placeholder{
        visibility:hidden!important;
    }

    .lab-dot{
        flex:0 0 auto!important;
        margin-top:.27rem!important;
    }

    .lab-mouse-icon{
        flex:0 0 auto!important;
        margin-top:-.31rem!important;
    }

    .lab-next-event-cell{
        display:grid!important;
        grid-template-rows:.72rem 1.10rem!important;
        align-content:center!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:2.34rem!important;
        height:2.34rem!important;
        margin:0!important;
        padding:0 0 0 .50rem!important;
        box-sizing:border-box!important;
    }

    .lab-next-event-cell > .lab-mini-label{
        position:static!important;
        align-self:end!important;
        margin:0!important;
        padding:0!important;
        line-height:.72rem!important;
    }

    .lab-next-inline{
        display:flex!important;
        align-items:center!important;
        gap:.28rem!important;
        align-self:start!important;
        min-width:0!important;
        height:1.10rem!important;
        line-height:1.10rem!important;
        margin:0!important;
        padding:0!important;
        white-space:nowrap!important;
    }

    .lab-next-copy{
        color:#dfe5eb!important;
        font-size:.72rem!important;
        font-weight:680!important;
        line-height:1.10rem!important;
        white-space:nowrap!important;
    }

    .lab-next-metric{
        color:#eef2f5!important;
        font-size:.98rem!important;
        font-weight:760!important;
        line-height:1.10rem!important;
        white-space:nowrap!important;
    }

    .lab-next-metric.orange{color:#f5a126!important}
    .lab-next-metric.red{color:#ff8798!important}
    .lab-next-metric.green{color:#73dc87!important}
    .lab-next-metric.gray{color:#8d99a6!important}

    .lab-next-overline,
    .lab-next-single-label{
        position:static!important;
        left:auto!important;
        bottom:auto!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-next-main{
        margin:0!important;
        padding:0!important;
    }

    .lab-total-cell{
        display:grid!important;
        grid-template-rows:.72rem 1.10rem!important;
        align-content:center!important;
        justify-items:start!important;
        row-gap:.18rem!important;
        min-height:2.34rem!important;
        height:2.34rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-total-cell > .lab-mini-label{
        position:static!important;
        align-self:end!important;
        margin:0!important;
        padding:0!important;
        line-height:.72rem!important;
    }

    .lab-total{
        align-self:start!important;
        height:1.10rem!important;
        line-height:1.10rem!important;
        margin:0!important;
        padding:0!important;
    }

    .lab-paused-label{
        position:absolute!important;
        left:0!important;
        bottom:2.42rem!important;
        margin:0!important;
    }

    .lab-next-inline,
    .lab-next-inline.lab-primary-text,
    .lab-next-copy,
    .lab-next-metric{
        font-size:.73rem!important;
        font-weight:680!important;
        line-height:1.10rem!important;
    }

    .lab-next-inline{
        height:1.10rem!important;
        white-space:nowrap!important;
    }

    .lab-next-inline.gray,
    .lab-next-metric.gray{
        color:#8d99a6!important;
    }

    .lab-next-inline.green,
    .lab-next-metric.green{
        color:#73dc87!important;
    }

    .lab-next-inline.orange,
    .lab-next-metric.orange{
        color:#f5a126!important;
    }

    .lab-next-inline.red,
    .lab-next-metric.red{
        color:#ff8798!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button:disabled,
    div[class*="st-key-anesthesia_delay_action_"] button:disabled{
        color:rgba(190,201,212,.36)!important;
        border-color:rgba(137,160,184,.10)!important;
        background:rgba(137,160,184,.025)!important;
        box-shadow:none!important;
        opacity:.72!important;
    }

    .ts-title{
        color:#f6f9fc!important;
        font-size:1.08rem!important;
        font-weight:760!important;
        letter-spacing:-.015em!important;
        margin:.06rem 0 .56rem!important;
    }

    .ts-summary-grid{
        display:grid!important;
        grid-template-columns:repeat(4,minmax(0,1fr))!important;
        gap:.62rem!important;
        margin:.10rem 0 .92rem!important;
    }

    .ts-summary-card{
        min-width:0!important;
        padding:.68rem .76rem!important;
        border:1px solid rgba(137,160,184,.18)!important;
        border-radius:9px!important;
        background:linear-gradient(
            180deg,
            rgba(16,29,42,.86),
            rgba(11,22,33,.86)
        )!important;
    }

    .ts-summary-label{
        color:#94a6b8!important;
        font-size:.67rem!important;
        font-weight:730!important;
        text-transform:uppercase!important;
        letter-spacing:.055em!important;
        line-height:1.05!important;
        margin-bottom:.28rem!important;
        white-space:nowrap!important;
    }

    .ts-summary-value{
        color:#f3f7fa!important;
        font-size:.91rem!important;
        font-weight:740!important;
        line-height:1.10!important;
        white-space:nowrap!important;
    }

    .ts-section-title{
        color:#f1f5f8!important;
        font-size:.90rem!important;
        font-weight:740!important;
        line-height:1.10!important;
        margin:.76rem 0 .34rem!important;
    }

    .ts-note{
        color:#9eafbf!important;
        font-size:.72rem!important;
        line-height:1.30!important;
        margin:.08rem 0 .52rem!important;
    }

    .ts-table-wrap{
        width:100%!important;
        overflow-x:auto!important;
        border:1px solid rgba(137,160,184,.16)!important;
        border-radius:9px!important;
        background:rgba(9,19,29,.44)!important;
        margin:.08rem 0 .74rem!important;
    }

    .ts-table{
        width:100%!important;
        border-collapse:collapse!important;
        table-layout:fixed!important;
        font-variant-numeric:tabular-nums!important;
    }

    .ts-table th{
        color:#a9b8c7!important;
        background:rgba(137,160,184,.055)!important;
        font-size:.63rem!important;
        font-weight:770!important;
        text-transform:uppercase!important;
        letter-spacing:.055em!important;
        line-height:1.05!important;
        text-align:left!important;
        padding:.54rem .60rem!important;
        border-bottom:1px solid rgba(137,160,184,.17)!important;
        white-space:nowrap!important;
    }

    .ts-table td{
        color:#d7e1ea!important;
        font-size:.73rem!important;
        font-weight:560!important;
        line-height:1.22!important;
        padding:.52rem .60rem!important;
        border-bottom:1px solid rgba(137,160,184,.09)!important;
        vertical-align:middle!important;
        white-space:nowrap!important;
        overflow:hidden!important;
        text-overflow:ellipsis!important;
    }

    .ts-table tr:last-child td{
        border-bottom:0!important;
    }

    .ts-table td.ts-strong{
        color:#f1f5f8!important;
        font-weight:690!important;
    }

    div[class*="st-key-timesheet_event_header_"]{
        padding:.38rem .44rem!important;
        margin:.06rem 0 .06rem!important;
        border-top:1px solid rgba(137,160,184,.15)!important;
        border-bottom:1px solid rgba(137,160,184,.15)!important;
        background:rgba(137,160,184,.045)!important;
        border-radius:7px 7px 0 0!important;
    }

    div[class*="st-key-timesheet_event_header_"] [data-testid="stHorizontalBlock"]{
        gap:.62rem!important;
        align-items:center!important;
    }

    .ts-event-header{
        min-height:1.08rem!important;
        display:flex!important;
        align-items:center!important;
        color:#a9b8c7!important;
        font-size:.62rem!important;
        font-weight:770!important;
        text-transform:uppercase!important;
        letter-spacing:.055em!important;
        line-height:1!important;
        white-space:nowrap!important;
    }

    div[class*="st-key-timesheet_event_row_"]{
        padding:.40rem .44rem!important;
        margin:0!important;
        border-bottom:1px solid rgba(137,160,184,.09)!important;
        background:rgba(8,18,28,.18)!important;
    }

    div[class*="st-key-timesheet_event_row_"]:last-of-type{
        border-radius:0 0 7px 7px!important;
    }

    div[class*="st-key-timesheet_event_row_"] [data-testid="stHorizontalBlock"]{
        gap:.62rem!important;
        align-items:center!important;
    }

    .ts-event-cell{
        min-height:2.10rem!important;
        display:flex!important;
        align-items:center!important;
        color:#cbd7e1!important;
        font-size:.72rem!important;
        font-weight:560!important;
        line-height:1.25!important;
        font-variant-numeric:tabular-nums!important;
        word-break:break-word!important;
    }

    .ts-event-cell.primary{
        color:#f0f4f8!important;
        font-size:.76rem!important;
        font-weight:690!important;
    }

    .ts-event-cell.details{
        color:#bcc9d5!important;
        white-space:normal!important;
    }

    div[class*="st-key-timesheet_event_row_"] .stButton>button{
        min-height:2.12rem!important;
        height:2.12rem!important;
        padding:0 .52rem!important;
        border-radius:8px!important;
        font-size:.70rem!important;
        font-weight:670!important;
        white-space:nowrap!important;
    }

    .ts-adjust-placeholder{
        min-height:2.12rem!important;
    }

    div[class*="st-key-timesheet_backtime_panel_"]{
        margin-top:.72rem!important;
        padding:.74rem .78rem!important;
        border:1px solid rgba(137,160,184,.17)!important;
        border-radius:9px!important;
        background:rgba(13,24,35,.66)!important;
    }

    div[class*="st-key-timesheet_backtime_panel_"] [data-testid="stWidgetLabel"] p{
        color:#c0ccd7!important;
    }

    @media(max-width:1180px){
        .ts-summary-grid{
            grid-template-columns:repeat(2,minmax(0,1fr))!important;
        }
    }

    .preflight-browser-status{
        margin:.42rem 0 .62rem!important;
        padding:.58rem .68rem!important;
        border:1px solid rgba(137,160,184,.18)!important;
        border-radius:9px!important;
        background:rgba(12,23,34,.72)!important;
        color:#cbd6e0!important;
        font-size:.74rem!important;
        line-height:1.35!important;
    }
    .preflight-browser-status .ok{color:#92dfa0!important;font-weight:700!important}
    .preflight-browser-status .warn{color:#ffc169!important;font-weight:700!important}

"""


def install_app_styles():
    """Install the complete application stylesheet once per script rerun."""
    st.markdown("<style>" + APP_CSS + "</style>", unsafe_allow_html=True)



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
def wall_datetime(epoch=None):
    """Return an application-local datetime for an epoch (or the current time)."""
    value = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(value, APP_TZ)
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
        f"starting_map_mmhg_{i}":None, f"ending_map_mmhg_{i}":None,
        f"shock_volume_ml_{i}":None, f"resuscitation_volume_ml_{i}":None,
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
    st.session_state.setdefault("_show_storage_exit_dialog", False)
    st.session_state.setdefault("_pending_run_preflight", None)
    for i in range(1, int(st.session_state["_mouse_count"]) + 1): initialize_mouse_state(i)

def mouse_count(): return int(st.session_state.get("_mouse_count", INITIAL_MOUSE_COUNT))
def subject_name(i): return str(st.session_state.get(f"subject_name_{i}", f"Mouse {i}")).strip() or f"Mouse {i}"
def _subject_float(i, field):
    """Return a per-subject numeric value as float, or ``None`` when unset."""
    try:
        value = st.session_state.get(f"{field}_{i}")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def mouse_weight(i):
    return _subject_float(i, "mouse_weight_g")


def weight_label(i):
    value = mouse_weight(i)
    return "Weight —" if value is None or value <= 0 else f"{value:.1f} g"


def _random_test_weight():
    return round(random.uniform(TEST_WEIGHT_MIN_G, TEST_WEIGHT_MAX_G), 1)


def _default_entry_weight():
    return _random_test_weight() if TESTING_MODE else 0.0


def starting_map(i):
    return _subject_float(i, "starting_map_mmhg")


def ending_map(i):
    return _subject_float(i, "ending_map_mmhg")


def shock_volume(i):
    return _subject_float(i, "shock_volume_ml")


def resuscitation_volume(i):
    return _subject_float(i, "resuscitation_volume_ml")

def _map_summary(i):
    start=starting_map(i); end=ending_map(i); parts=[]
    if start is not None: parts.append(f"Starting MAP {start:g} mmHg")
    if end is not None: parts.append(f"Ending MAP {end:g} mmHg")
    return " · ".join(parts)

def _volume_summary(i):
    shock=shock_volume(i); resus=resuscitation_volume(i); parts=[]
    if shock is not None: parts.append(f"Shock volume removed {shock:g} mL")
    if resus is not None: parts.append(f"Resuscitation volume given {resus:g} mL")
    return " · ".join(parts)

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
    """Retry pending subject saves and report whether all changes are confirmed."""
    pending=list(st.session_state.get("_unsaved_subjects",[]))
    if pending:
        persist_subjects(pending)
    return not bool(st.session_state.get("_unsaved_subjects",[]))

def build_emergency_backup_text():
    """
    Build a standalone recovery file containing the complete in-memory subject
    state plus the human-readable timesheet. This is intentionally independent
    of database persistence so a failed save never traps the only copy in the UI.
    """
    indices=ordered_subject_indices()
    backup={
        "backup_format":"shock_timer_emergency_backup_v1",
        "state_version":STATE_VERSION,
        "created_at":wall_datetime().isoformat(),
        "timezone":APP_TIMEZONE,
        "database_kind":DATABASE_KIND,
        "experiment":{
            "id":st.session_state.get("_active_experiment_id"),
            "name":st.session_state.get("_active_experiment_name"),
            "mouse_count":mouse_count(),
        },
        "unsaved_subjects":list(st.session_state.get("_unsaved_subjects",[])),
        "storage_error":st.session_state.get("_storage_error"),
        "subjects":{
            str(i):_subject_payload(i)
            for i in indices
        },
        "timesheet_text":build_all_timesheets_text(),
    }
    return json.dumps(backup,indent=2,ensure_ascii=False)

def emergency_backup_filename():
    name=re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(st.session_state.get("_active_experiment_name","experiment")).strip(),
    ).strip("_") or "experiment"
    return (
        f"{name}_EMERGENCY_BACKUP_"
        f"{wall_datetime().strftime('%Y%m%d_%H%M%S')}.json"
    )

def storage_preflight_check():
    """Confirm that the configured persistence backend is currently reachable."""
    try:
        rows=_db_query("SELECT 1 AS ok")
        if not rows:
            return False,"Storage check returned no response."
        label=(
            "Cloud database reachable"
            if DATABASE_KIND=="postgres"
            else "Local SQLite storage reachable"
        )
        return True,label
    except Exception as exc:
        return False,str(exc)

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

def relative_time_map(i, log):
    """Map each event id to its relative time without reparsing timestamps."""
    base = st.session_state.get(f"experiment_start_{i}")
    parsed_epochs = [event_epoch(event) for event in log]
    valid_epochs = [epoch for epoch in parsed_epochs if epoch is not None]
    if base is None and valid_epochs:
        base = min(valid_epochs)

    result = {}
    for order, (event, epoch) in enumerate(zip(log, parsed_epochs)):
        value = (
            "—"
            if epoch is None or base is None
            else _format_relative(epoch - float(base))
        )
        key = event.get("_id") or f"__order_{order}"
        result[key] = value
    return result

def is_backtime_editable_event(entry):
    return entry.get("Event") in BACKTIME_EDITABLE_EVENTS

def backtime_start_event(i, event_id, minutes):
    """Move a timer-start event earlier by the requested number of minutes."""
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return False, "Enter a valid number of minutes."
    if minutes <= 0:
        return False, "Back-time must be greater than 0 minutes."

    key = f"event_log_{i}"
    log = list(st.session_state.get(key, []))
    index = next(
        (position for position, event in enumerate(log) if event.get("_id") == event_id),
        None,
    )
    if index is None:
        return False, "That event could not be found."

    entry = dict(log[index])
    if not is_backtime_editable_event(entry):
        return False, "That event is not a timer start and cannot be back-timed here."

    old_epoch = event_epoch(entry)
    if old_epoch is None:
        return False, "The saved event time could not be parsed."

    new_epoch = old_epoch - minutes * 60.0
    event_name = entry.get("Event")
    _record_global_undo(f"Back-time {event_name} — {subject_name(i)}", [i])

    entry["_epoch"] = new_epoch
    entry["Absolute time"] = wall_datetime(new_epoch).strftime("%Y-%m-%d %H:%M:%S")
    log[index] = entry
    st.session_state[key] = log

    if event_name == "Board acclimation started":
        st.session_state[f"board_start_{i}"] = new_epoch
    elif event_name == "Shock started":
        st.session_state[f"shock_start_{i}"] = new_epoch
        st.session_state[f"shock_wallclock_{i}"] = wall_datetime(new_epoch).strftime("%H:%M:%S")
    elif event_name == "Resuscitation started":
        st.session_state[f"resus_start_{i}"] = new_epoch
    elif event_name in ANESTHESIA_EVENT_NAMES:
        anesthesia_events = [
            event for event in log if event.get("Event") in ANESTHESIA_EVENT_NAMES
        ]
        if anesthesia_events and anesthesia_events[-1].get("_id") == event_id:
            st.session_state[f"anesthesia_start_{i}"] = new_epoch
        if event_name == "Anesthesia started":
            current_start = st.session_state.get(f"experiment_start_{i}")
            if current_start is None or new_epoch < float(current_start):
                st.session_state[f"experiment_start_{i}"] = new_epoch

    log_event(i, "Time correction", f"{event_name} moved {minutes:g} min earlier")
    persist_subject(i)
    clear_mouse_alerts(i)
    st.session_state["_needs_full_rerun"] = True
    return True, None

def _anesthesia_event_weight(i,event):
    """Return the weight associated with an anesthesia event."""
    try:
        value=event.get("_weight_g")
        if value is not None:
            return float(value)
    except (TypeError,ValueError):
        pass

    # V53+ writes a readable weight into Details too. This fallback also
    # supports events created just before upgrading to V53.
    details=str(event.get("Details",""))
    if details.startswith("Weight ") and details.endswith(" g"):
        try:
            return float(details[len("Weight "):-2].strip())
        except (TypeError,ValueError):
            pass

    # Legacy events did not snapshot the event-time weight. Use the current
    # saved subject weight rather than leaving the summary blank.
    return mouse_weight(i)


def anesthesia_summary_rows(i):
    log=list(st.session_state.get(f"event_log_{i}",[]))
    rel=relative_time_map(i,log)
    rows=[]
    dose_number=0

    for order,event in enumerate(log):
        event_name=str(event.get("Event",""))
        if event_name not in ANESTHESIA_EVENT_NAMES:
            continue

        dose_number += 1
        weight=_anesthesia_event_weight(i,event)
        dose_volume_ml=(
            None
            if weight is None
            else float(weight)*ANESTHESIA_DOSE_VOLUME_ML_PER_G
        )
        rows.append({
            "dose":dose_number,
            "type":"Initial" if event_name=="Anesthesia started" else "Redose",
            "relative":rel.get(event.get("_id"),rel.get(f"__order_{order}","—")),
            "absolute":str(event.get("Absolute time","")),
            "weight_g":weight,
            "weight":"—" if weight is None else f"{weight:.1f} g",
            "volume_ml":dose_volume_ml,
            "volume":"—" if dose_volume_ml is None else f"{dose_volume_ml:.3f} mL",
        })

    return rows

def anesthesia_usage_totals(indices=None, rows_by_subject=None):
    """Summarize administration count and total volume by anesthetic vial."""
    if indices is None:
        indices = ordered_subject_indices()

    totals = {
        "Initial": {"doses": 0, "volume_ml": 0.0, "missing_weight": 0},
        "Redose": {"doses": 0, "volume_ml": 0.0, "missing_weight": 0},
    }

    for i in indices:
        rows = (
            rows_by_subject.get(i, [])
            if rows_by_subject is not None
            else anesthesia_summary_rows(i)
        )
        for row in rows:
            stats = totals[row["type"]]
            stats["doses"] += 1
            if row["volume_ml"] is None:
                stats["missing_weight"] += 1
            else:
                stats["volume_ml"] += float(row["volume_ml"])

    return totals

def _format_anesthesia_usage_lines(usage):
    """Return aligned initial-dose and redose vial totals for text export."""
    rows=[
        ("Initial dose",usage["Initial"]),
        ("Redose",usage["Redose"]),
    ]

    dose_texts=[]
    for _,stats in rows:
        dose_word="dose" if stats["doses"]==1 else "doses"
        dose_texts.append(f"{stats['doses']} {dose_word}")

    label_width=max(len(label) for label,_ in rows)
    dose_width=max(len(value) for value in dose_texts)

    lines=[]
    for (label,stats),dose_text in zip(rows,dose_texts):
        line=(
            f"{label:<{label_width}} | "
            f"{dose_text:<{dose_width}} | "
            f"{stats['volume_ml']:.1f} mL total"
        )
        if stats["missing_weight"]:
            missing_word="dose" if stats["missing_weight"]==1 else "doses"
            line += f" | {stats['missing_weight']} {missing_word} missing weight"
        lines.append(line)

    return lines





def _anesthesia_export_rows(indices, rows_by_subject):
    rows = []
    for i in indices:
        for row in rows_by_subject[i]:
            rows.append({
                "subject": subject_name(i),
                "dose": str(row["dose"]),
                "type": str(row["type"]),
                "relative": str(row["relative"]),
                "absolute": str(row["absolute"]),
                "weight": str(row["weight"]),
                "volume": str(row["volume"]),
            })
    return rows


def _anesthesia_export_lines(indices, rows_by_subject):
    export_rows = _anesthesia_export_rows(indices, rows_by_subject)
    if not export_rows:
        return ["-" * 96, "No anesthesia administrations recorded."]

    headers = {
        "subject": "Subj",
        "dose": "#",
        "type": "Type",
        "relative": "Rel time",
        "absolute": "Abs time",
        "weight": "Wt",
        "volume": "Vol",
    }
    fields = tuple(headers)
    widths = {
        field: max(
            len(headers[field]),
            max(len(row[field]) for row in export_rows),
        )
        for field in fields
    }

    def table_line(values):
        return (
            f"{values['subject']:<{widths['subject']}} | "
            f"{values['dose']:>{widths['dose']}} | "
            f"{values['type']:<{widths['type']}} | "
            f"{values['relative']:<{widths['relative']}} | "
            f"{values['absolute']:<{widths['absolute']}} | "
            f"{values['weight']:>{widths['weight']}} | "
            f"{values['volume']:>{widths['volume']}}"
        )

    header_line = table_line(headers)
    lines = ["-" * len(header_line), header_line, "-" * len(header_line)]
    lines.extend(table_line(row) for row in export_rows)

    usage = anesthesia_usage_totals(indices, rows_by_subject)
    lines.extend([
        "",
        "ANESTHESIA USE TOTALS (0.01 mL/g per administration)",
        *_format_anesthesia_usage_lines(usage),
    ])
    return lines


def _blood_pressure_export_lines(indices):
    lines = [
        "",
        "BLOOD PRESSURE SUMMARY",
        "-" * 96,
        "Subject | Weight | Starting MAP | Ending MAP",
    ]
    for i in indices:
        start = starting_map(i)
        end = ending_map(i)
        lines.append(
            f"{subject_name(i)} | {weight_label(i)} | "
            f"{'—' if start is None else f'{start:g} mmHg'} | "
            f"{'—' if end is None else f'{end:g} mmHg'}"
        )
    return lines


def _volume_export_lines(indices):
    lines = [
        "",
        "VOLUME SUMMARY",
        "-" * 96,
        "Subject | Shock volume removed | Resuscitation volume given",
    ]
    for i in indices:
        shock_vol = shock_volume(i)
        resus_vol = resuscitation_volume(i)
        lines.append(
            f"{subject_name(i)} | "
            f"{'—' if shock_vol is None else f'{shock_vol:g} mL'} | "
            f"{'—' if resus_vol is None else f'{resus_vol:g} mL'}"
        )
    return lines


def _subject_timesheet_export_lines(i):
    lines = [
        "=" * 96,
        f"{subject_name(i)} (Mouse {i}; {weight_label(i)})",
        "=" * 96,
    ]

    map_summary = _map_summary(i)
    if map_summary:
        lines.append(map_summary)

    volume_summary = _volume_summary(i)
    if volume_summary:
        lines.append(volume_summary)

    log = list(st.session_state.get(f"event_log_{i}", []))
    relative_times = relative_time_map(i, log)
    if not log:
        lines.append("No events recorded.")
    else:
        lines.extend([
            "Relative time | Absolute time        | Event | Details",
            "-" * 96,
        ])

    for order, event in enumerate(log):
        relative = relative_times.get(
            event.get("_id"),
            relative_times.get(f"__order_{order}", "—"),
        )
        line = (
            f"{relative:>13} | "
            f"{event.get('Absolute time', '')} | "
            f"{event.get('Event', '')}"
        )
        details = str(event.get("Details", "")).strip()
        lines.append(line + (f" | {details}" if details else ""))

    lines.append("")
    return lines


def build_all_timesheets_text():
    """Build the complete text export using one stable subject ordering."""
    indices = ordered_subject_indices()
    anesthesia_rows_by_subject = {
        i: anesthesia_summary_rows(i)
        for i in indices
    }

    lines = [
        "Shock Timer - Aggregated Timesheets",
        f"Experiment: {st.session_state.get('_active_experiment_name', '')}",
        f"Timezone: {APP_TIMEZONE}",
        f"Exported: {wall_datetime().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "ANESTHESIA SUMMARY",
    ]
    lines.extend(_anesthesia_export_lines(indices, anesthesia_rows_by_subject))
    lines.extend(_blood_pressure_export_lines(indices))
    lines.extend(_volume_export_lines(indices))
    lines.extend(["", "DETAILED SUBJECT TIMESHEETS", ""])
    for i in indices:
        lines.extend(_subject_timesheet_export_lines(i))

    return "\n".join(lines).rstrip() + "\n"

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
    elif action=="start_resus":
        st.session_state[f"resus_start_{i}"]=None
        st.session_state[f"shock_volume_ml_{i}"]=None
    elif action=="start_shock":
        st.session_state[f"shock_start_{i}"]=None; st.session_state[f"shock_wallclock_{i}"]=None; st.session_state[f"starting_map_mmhg_{i}"]=None
    elif action=="start_board": st.session_state[f"board_start_{i}"]=None
    st.session_state[key]=h; clear_mouse_alerts(i); log_event(i,"Undo",f"Reverted {_undo_label(action)}"); persist_subject(i); st.session_state["_needs_full_rerun"]=True; return True

def start_or_redose_anesthesia(i):
    if not mouse_is_running(i): return
    now=time.time()
    previous=st.session_state.get(f"anesthesia_start_{i}")
    first=previous is None
    _record_global_undo(f"{'Start anesthesia' if first else 'Anesthesia redose'} — {subject_name(i)}",[i])
    snap=None
    if not first:
        snap={
            "anesthesia_start":previous,
            "anesthesia_due_override":st.session_state.get(f"anesthesia_due_override_{i}"),
            "anesthesia_dose_count":anesthesia_dose_count(i),
        }

    ensure_experiment_started(i,now)
    st.session_state[f"anesthesia_start_{i}"]=now
    st.session_state[f"anesthesia_due_override_{i}"]=None
    st.session_state[f"anesthesia_dose_count_{i}"]=1 if first else anesthesia_dose_count(i)+1

    dose_weight=mouse_weight(i)
    weight_detail="Weight —" if dose_weight is None else f"Weight {dose_weight:.1f} g"
    event=log_event(
        i,
        "Anesthesia started" if first else "Anesthesia redosed",
        weight_detail,
        when_epoch=now,
    )
    event["_weight_g"]=dose_weight

    if not first:
        _push_undo(i,"anesthesia_redose",event,snapshot=snap)

    clear_alert(i,"Anesthesia redose")
    persist_subject(i)

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
    st.session_state["_pending_dialog"]={"mouse":int(i),"kind":"starting_map"}
    st.session_state["_needs_full_rerun"]=True

def start_resuscitation(i,force=False):
    if not mouse_is_running(i): return
    now=time.time()
    if starting_map(i) is None:
        request_dialog(i,"starting_map")
        return
    if st.session_state.get(f"resus_start_{i}") is not None or st.session_state.get(f"shock_start_{i}") is None or (not force and not shock_is_complete(i,now)): return
    _record_global_undo(f"{'Force start resus' if force else 'Start resus'} — {subject_name(i)}",[i])
    st.session_state[f"resus_start_{i}"]=now
    st.session_state[f"shock_volume_ml_{i}"]=None
    event=log_event(i,"Resuscitation started","Forced advance before shock completed" if force else "",when_epoch=now)
    _push_undo(i,"start_resus",event)
    clear_alert(i,"Resuscitation")
    persist_subject(i)
    st.session_state["_pending_dialog"]={"mouse":int(i),"kind":"shock_volume"}
    st.session_state["_needs_full_rerun"]=True

def toggle_pause(i):
    if is_ended(i): return
    now=time.time(); _record_global_undo(f"{'Resume' if is_paused(i) else 'Pause'} — {subject_name(i)}",[i])
    if not is_paused(i):
        st.session_state[f"paused_{i}"]=True; st.session_state[f"pause_started_{i}"]=now; log_event(i,"Paused",when_epoch=now)
    else:
        started=st.session_state.get(f"pause_started_{i}") or now; delta=max(0,now-float(started))
        for field in PAUSE_SHIFT_FIELDS:
            key=f"{field}_{i}"; value=st.session_state.get(key)
            if value is not None: st.session_state[key]=float(value)+delta
        st.session_state[f"paused_{i}"]=False; st.session_state[f"pause_started_{i}"]=None; log_event(i,"Resumed",f"Paused {format_timer(delta)}",when_epoch=now)
    clear_mouse_alerts(i); persist_subject(i)

def end_mouse(i,forced=False,ending_map_mmhg=None,resuscitation_volume_ml=None):
    if is_ended(i): return False
    if st.session_state.get(f"shock_start_{i}") is not None and starting_map(i) is None:
        return False
    # Once resuscitation has started, shock volume and both ending measurements
    # are required before the subject can be marked ended.
    if st.session_state.get(f"resus_start_{i}") is not None:
        if (
            shock_volume(i) is None
            or ending_map_mmhg is None
            or resuscitation_volume_ml is None
        ):
            return False
    now=time.time()
    _record_global_undo(f"{'Force end subject' if forced else 'End subject'} — {subject_name(i)}",[i])
    end_at=st.session_state.get(f"pause_started_{i}") or now
    if ending_map_mmhg is not None:
        st.session_state[f"ending_map_mmhg_{i}"]=float(ending_map_mmhg)
        log_event(i,"Ending MAP",f"{float(ending_map_mmhg):g} mmHg",when_epoch=now)
    if resuscitation_volume_ml is not None:
        st.session_state[f"resuscitation_volume_ml_{i}"]=float(resuscitation_volume_ml)
        log_event(i,"Resuscitation volume",f"{float(resuscitation_volume_ml):g} mL given",when_epoch=now)
    st.session_state[f"ended_{i}"]=True
    st.session_state[f"end_time_{i}"]=end_at
    st.session_state[f"paused_{i}"]=False
    st.session_state[f"pause_started_{i}"]=None
    clear_mouse_alerts(i)
    log_event(i,"Experiment ended","Forced advance before resuscitation completed" if forced else "",when_epoch=now)
    persist_subject(i)
    maybe_mark_experiment_complete()
    return True

def reset_mouse(i):
    _record_global_undo(f"Reset subject — {subject_name(i)}", [i])

    preserved = {
        "subject_name": subject_name(i),
        "mouse_weight_g": mouse_weight(i),
        "display_order": st.session_state.get(f"display_order_{i}", i),
        "anesthesia_initial_duration": st.session_state.get(
            f"anesthesia_initial_duration_{i}", DEFAULT_INITIAL_ANESTHESIA
        ),
        "anesthesia_duration": st.session_state.get(
            f"anesthesia_duration_{i}", DEFAULT_SUBSEQUENT_ANESTHESIA
        ),
        "anesthesia_delay_duration": st.session_state.get(
            f"anesthesia_delay_duration_{i}", DEFAULT_ANESTHESIA_DELAY
        ),
        "notification_sound": st.session_state.get(
            f"notification_sound_{i}", DEFAULT_NOTIFICATION_SOUND
        ),
        "notification_sound_enabled": st.session_state.get(
            f"notification_sound_enabled_{i}", DEFAULT_NOTIFICATION_SOUND_ENABLED
        ),
    }

    for key, value in mouse_defaults(i).items():
        st.session_state[key] = _copy_value(value)
    for field, value in preserved.items():
        st.session_state[f"{field}_{i}"] = value

    clear_mouse_alerts(i)
    persist_subject(i)
    _sync_experiment_completion_from_session()

def end_all_subjects_current_experiment(
    ending_maps=None,
    resuscitation_volumes=None,
    starting_maps=None,
    shock_volumes=None,
):
    targets=[i for i in ordered_subject_indices() if not is_ended(i)]
    if not targets:
        return True

    ending_maps={int(k):float(v) for k,v in (ending_maps or {}).items()}
    resuscitation_volumes={
        int(k):float(v) for k,v in (resuscitation_volumes or {}).items()
    }
    starting_maps={int(k):float(v) for k,v in (starting_maps or {}).items()}
    shock_volumes={int(k):float(v) for k,v in (shock_volumes or {}).items()}

    _record_global_undo("End all subjects",targets)
    now=time.time()

    for i in targets:
        if i in starting_maps:
            st.session_state[f"starting_map_mmhg_{i}"]=starting_maps[i]
            shock_time=st.session_state.get(f"shock_start_{i}") or now
            log_event(
                i,
                "Starting MAP",
                f"{starting_maps[i]:g} mmHg",
                when_epoch=shock_time,
            )

        if i in shock_volumes:
            st.session_state[f"shock_volume_ml_{i}"]=shock_volumes[i]
            resus_time=st.session_state.get(f"resus_start_{i}") or now
            log_event(
                i,
                "Shock volume",
                f"{shock_volumes[i]:g} mL removed",
                when_epoch=resus_time,
            )

        if i in ending_maps:
            st.session_state[f"ending_map_mmhg_{i}"]=ending_maps[i]
            log_event(i,"Ending MAP",f"{ending_maps[i]:g} mmHg",when_epoch=now)

        if i in resuscitation_volumes:
            st.session_state[f"resuscitation_volume_ml_{i}"]=resuscitation_volumes[i]
            log_event(
                i,
                "Resuscitation volume",
                f"{resuscitation_volumes[i]:g} mL given",
                when_epoch=now,
            )

        st.session_state[f"ended_{i}"]=True
        st.session_state[f"end_time_{i}"]=(
            st.session_state.get(f"pause_started_{i}") or now
        )
        st.session_state[f"paused_{i}"]=False
        st.session_state[f"pause_started_{i}"]=None
        clear_mouse_alerts(i)
        log_event(
            i,
            "Experiment ended",
            "Ended with End all subjects",
            when_epoch=now,
        )

    ok=persist_subjects(targets)
    if ok:
        exp_id=st.session_state.get("_active_experiment_id")
        if exp_id:
            _db_execute(
                "UPDATE experiments SET completed_at=COALESCE(completed_at,?),"
                "updated_at=? WHERE id=?",
                (now,now,exp_id),
            )
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


def _edit_subject_widget_keys(i):
    return [
        f"edit_name_{i}",
        f"edit_weight_{i}",
        f"edit_starting_map_{i}",
        f"edit_shock_volume_{i}",
        f"edit_ending_map_{i}",
        f"edit_resuscitation_volume_{i}",
    ]

def _clear_edit_subject_widgets(i):
    for key in _edit_subject_widget_keys(i):
        st.session_state.pop(key,None)

def _format_corrected_value(value,unit):
    if value is None:
        return "—"
    return f"{float(value):g} {unit}"

def edit_subject_field_availability(i,now=None):
    """
    Return which correction fields have been reached by this subject's workflow.

    Name and weight are always editable.
    Starting MAP unlocks when shock starts.
    Shock volume unlocks when resuscitation starts.
    Ending MAP and resuscitation volume unlock when the resuscitation endpoint
    is reached, or when a subject is force-ended after resuscitation has begun.
    Existing recorded values also keep their corresponding field available so
    legacy/corrected data can always be repaired.
    """
    wall_now=time.time() if now is None else float(now)
    effective=effective_now(i,wall_now)

    shock_started=st.session_state.get(f"shock_start_{i}") is not None
    resus_started=st.session_state.get(f"resus_start_{i}") is not None

    starting_map_reached=shock_started or starting_map(i) is not None
    shock_volume_reached=resus_started or shock_volume(i) is not None

    resus_endpoint_reached=(
        resus_started
        and (
            is_ended(i)
            or resus_is_complete(i,effective)
        )
    )
    ending_measurements_reached=(
        resus_endpoint_reached
        or ending_map(i) is not None
        or resuscitation_volume(i) is not None
    )

    return {
        "name":True,
        "weight":True,
        "starting_map":starting_map_reached,
        "shock_volume":shock_volume_reached,
        "ending_map":ending_measurements_reached,
        "resuscitation_volume":ending_measurements_reached,
    }

def save_subject_data_edits(
    i,
    name,
    weight,
    starting_map_mmhg,
    shock_volume_ml,
    ending_map_mmhg,
    resuscitation_volume_ml,
):
    """Persist corrected subject-entry fields without requiring an active timer."""
    name=(name or "").strip()
    if not name:
        return False,"Subject name cannot be blank.",False
    try:
        weight=round(float(weight),1)
    except (TypeError,ValueError):
        return False,"Enter a valid weight.",False
    if weight<=0:
        return False,"Weight must be greater than 0 g.",False

    old_name=subject_name(i)
    old_weight=mouse_weight(i)
    old_start=starting_map(i)
    old_shock=shock_volume(i)
    old_end=ending_map(i)
    old_resus=resuscitation_volume(i)

    changes=[]
    if old_name!=name:
        changes.append(f'Name "{old_name}" → "{name}"')
    if old_weight!=weight:
        changes.append(
            f"Weight {_format_corrected_value(old_weight,'g')} → "
            f"{_format_corrected_value(weight,'g')}"
        )
    if old_start!=starting_map_mmhg:
        changes.append(
            f"Starting MAP {_format_corrected_value(old_start,'mmHg')} → "
            f"{_format_corrected_value(starting_map_mmhg,'mmHg')}"
        )
    if old_shock!=shock_volume_ml:
        changes.append(
            f"Shock volume {_format_corrected_value(old_shock,'mL')} → "
            f"{_format_corrected_value(shock_volume_ml,'mL')}"
        )
    if old_end!=ending_map_mmhg:
        changes.append(
            f"Ending MAP {_format_corrected_value(old_end,'mmHg')} → "
            f"{_format_corrected_value(ending_map_mmhg,'mmHg')}"
        )
    if old_resus!=resuscitation_volume_ml:
        changes.append(
            f"Resuscitation volume {_format_corrected_value(old_resus,'mL')} → "
            f"{_format_corrected_value(resuscitation_volume_ml,'mL')}"
        )

    if not changes:
        return True,None,False

    # Keep corrections undoable while retaining an audit trail in the timesheet.
    _record_global_undo(f"Edit subject data — {old_name}",[i])
    st.session_state[f"subject_name_{i}"]=name
    st.session_state[f"mouse_weight_g_{i}"]=weight
    st.session_state[f"starting_map_mmhg_{i}"]=starting_map_mmhg
    st.session_state[f"shock_volume_ml_{i}"]=shock_volume_ml
    st.session_state[f"ending_map_mmhg_{i}"]=ending_map_mmhg
    st.session_state[f"resuscitation_volume_ml_{i}"]=resuscitation_volume_ml

    # Anesthesia volumes are calculated from the recorded subject weight.
    # If that weight is corrected, update prior anesthesia event snapshots so
    # the per-dose and vial-total calculations use the corrected value.
    if old_weight!=weight:
        event_key=f"event_log_{i}"
        corrected_log=[]
        for event in st.session_state.get(event_key,[]):
            corrected=dict(event)
            if corrected.get("Event") in ANESTHESIA_EVENT_NAMES:
                corrected["_weight_g"]=weight
                corrected["Details"]=f"Weight {weight:.1f} g"
            corrected_log.append(corrected)
        st.session_state[event_key]=corrected_log

    log_event(i,"Subject data edited","; ".join(changes))
    persist_subject(i)
    return True,None,True

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
    # Completing the resuscitation timer makes the End action due, but it does
    # NOT complete the subject. A subject moves to Completed / Ended only after
    # the user explicitly ends it. Normal post-resuscitation ending is gated by
    # the ending-MAP dialog before end_mouse() is called.
    return is_ended(i)

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
        if (
            key.startswith("_cfg_name_")
            or key.startswith("_cfg_weight_")
            or key.startswith("_preflight_")
        ):
            st.session_state.pop(key,None)
    for key in (
        "_configuration_draft",
        "_configuration_experiment_name",
        "_show_configuration_dialog",
        "_configuration_error",
        "_pending_run_preflight",
    ):
        st.session_state.pop(key,None)

def _new_draft_mouse(number): return {"draft_id":uuid.uuid4().hex,"name":f"Mouse {number}","weight_g":_default_entry_weight()}

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

def queue_run_preflight(mode,**payload):
    st.session_state["_pending_run_preflight"]={"mode":str(mode),**payload}
    st.session_state["_preflight_audio_tested"]=False
    st.session_state["_preflight_audio_confirmed"]=False
    st.session_state["_preflight_awake_confirmed"]=False

def _clear_run_preflight():
    st.session_state.pop("_pending_run_preflight",None)
    for key in (
        "_preflight_audio_tested",
        "_preflight_audio_confirmed",
        "_preflight_awake_confirmed",
    ):
        st.session_state.pop(key,None)

@st.dialog("Run preflight")
def run_preflight_dialog():
    payload=st.session_state.get("_pending_run_preflight") or {}
    mode=str(payload.get("mode",""))
    if not mode:
        return

    st.markdown("### Preflight check")
    st.caption(
        "Confirm storage, alert audio, and screen-wake readiness before "
        "starting or resuming live timers."
    )

    storage_ok,storage_message=storage_preflight_check()
    if storage_ok:
        st.success(f"Storage ✓  {storage_message}")
    else:
        st.error(f"Storage ✕  {storage_message}")

    # Browser helper fills this with live capability information.
    st.html(
        '<div class="preflight-browser-status" '
        'data-lab-preflight-browser-status>'
        'Checking browser audio and screen-wake support…</div>'
    )

    if st.button(
        "🔊 Play test alert",
        key="preflight_test_audio",
        use_container_width=True,
    ):
        st.session_state["_preflight_audio_tested"]=True
        render_hidden_autoplay_audio(
            DEFAULT_NOTIFICATION_SOUND,
            "preflight_test",
        )

    audio_tested=bool(st.session_state.get("_preflight_audio_tested",False))
    st.checkbox(
        "I heard the test alert",
        key="_preflight_audio_confirmed",
        disabled=not audio_tested,
    )
    st.checkbox(
        "Keep the screen awake during the run. Use automatic Wake Lock when "
        "supported; otherwise I will prevent sleep manually.",
        key="_preflight_awake_confirmed",
    )

    ready=(
        storage_ok
        and bool(st.session_state.get("_preflight_audio_confirmed",False))
        and bool(st.session_state.get("_preflight_awake_confirmed",False))
    )

    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="preflight_cancel",use_container_width=True):
            _clear_run_preflight()
            st.rerun()

    with right:
        label="Start experiment" if mode=="create" else "Resume experiment"
        if st.button(
            label,
            key="preflight_continue",
            use_container_width=True,
            type="primary",
            disabled=not ready,
        ):
            try:
                if mode=="create":
                    configured=list(payload.get("configured") or [])
                    exp_name=str(payload.get("name") or "Experiment")
                    exp_id=create_experiment_record(exp_name,configured)
                    _clear_run_preflight()
                    _clear_configuration()
                    load_experiment_into_session(exp_id)
                    st.rerun()

                if mode=="resume":
                    exp_id=str(payload.get("exp_id") or "")
                    _clear_run_preflight()
                    if load_experiment_into_session(exp_id):
                        st.rerun()
                    st.error("Experiment could not be loaded.")
            except Exception as exc:
                st.error(f"Preflight launch failed: {exc}")

@st.dialog("Configure experiment",width="large")
def configure_experiment_dialog():
    name=st.session_state.get("_configuration_experiment_name","")
    draft=list(st.session_state.get("_configuration_draft",[]))

    with st.container(key="cfg_dialog_intro"):
        st.markdown(f'<div class="cfg-dialog-expname">{html.escape(str(name))}</div>',unsafe_allow_html=True)
        st.markdown(
            '<div class="cfg-dialog-subcopy">Confirm each mouse name and weight before starting the experiment.</div>',
            unsafe_allow_html=True,
        )

    with st.container(key="configuration_table"):
        header_cols=st.columns(CONFIGURATION_COLUMNS, vertical_alignment="bottom")
        for col,label in zip(header_cols,["#","Mouse name","Weight (g)",""]):
            with col:
                st.markdown(f'<div class="lab-config-header">{label}</div>',unsafe_allow_html=True)

        remove=None
        for idx,row in enumerate(draft,start=1):
            did=row["draft_id"]
            nk=f"_cfg_name_{did}"
            wk=f"_cfg_weight_{did}"

            if nk not in st.session_state:
                st.session_state[nk]=row.get("name",f"Mouse {idx}")
            if wk not in st.session_state:
                st.session_state[wk]=float(row.get("weight_g",0.0) or 0.0)

            with st.container(key=f"cfg_row_shell_{did}"):
                cols=st.columns(CONFIGURATION_COLUMNS, vertical_alignment="center")
                with cols[0]:
                    st.markdown(f'<div class="cfg-index-cell">{idx}</div>',unsafe_allow_html=True)
                with cols[1]:
                    st.text_input("Mouse name",key=nk,label_visibility="collapsed")
                with cols[2]:
                    st.number_input(
                        "Weight (g)",
                        min_value=0.0,
                        max_value=100.0,
                        step=.1,
                        format="%.1f",
                        key=wk,
                        label_visibility="collapsed",
                    )
                with cols[3]:
                    with st.container(key=f"cfg_remove_wrap_{did}"):
                        if len(draft)>1 and st.button("×",key=f"cfg_remove_{did}",use_container_width=True):
                            remove=did

        if remove:
            _sync_cfg_from_widgets()
            st.session_state["_configuration_draft"]=[
                r for r in st.session_state.get("_configuration_draft",[]) if r["draft_id"]!=remove
            ]
            st.rerun()

    with st.container(key="cfg_add_mouse_wrap"):
        if st.button("+ Add mouse",key="cfg_add_mouse",use_container_width=True):
            current=_sync_cfg_from_widgets()
            current.append(_new_draft_mouse(len(current)+1))
            st.session_state["_configuration_draft"]=current
            st.rerun()

    error=st.session_state.pop("_configuration_error",None)
    if error:
        st.error(error)

    left,right=st.columns(2)
    with left:
        with st.container(key="cfg_cancel_wrap"):
            if st.button("Cancel",key="cfg_cancel",use_container_width=True):
                _clear_configuration()
                st.rerun()
    with right:
        with st.container(key="cfg_start_wrap"):
            if st.button("Start experiment",key="cfg_start",use_container_width=True,type="primary"):
                current=_sync_cfg_from_widgets()
                configured=[]
                errors=[]
                for idx,row in enumerate(current,start=1):
                    n,w,e=validate_mouse_name_weight(row.get("name"),row.get("weight_g"),f"Mouse {idx}")
                    if e:
                        errors.append(e)
                    else:
                        configured.append({"name":n,"weight_g":w})
                if errors:
                    st.session_state["_configuration_error"]=" ".join(errors)
                    st.rerun()
                atypical=[x for x in configured if weight_requires_confirmation(x["weight_g"])]
                if atypical:
                    queue_weight_warning("configuration",configured)
                    st.rerun()
                queue_run_preflight(
                    "create",
                    name=name,
                    configured=configured,
                )
                st.rerun()


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
                st.session_state.pop("_pending_weight_warning",None)
                queue_run_preflight(
                    "create",
                    name=st.session_state.get(
                        "_configuration_experiment_name",
                        "Experiment",
                    ),
                    configured=entries,
                )
                st.rerun()
            elif context=="add_mouse":
                e=entries[0] if entries else {}; ok,error=create_mouse_subject(e.get("name"),e.get("weight_g"))
                if ok: st.session_state.pop("_pending_weight_warning",None); st.session_state.pop("_add_mouse_name",None); st.session_state.pop("_add_mouse_weight",None); st.rerun()
                st.warning(error)
            elif context=="edit_subject":
                e=entries[0] if entries else {}
                i=int(payload.get("mouse",0))
                edits=dict(payload.get("edits") or {})
                ok,error,changed=save_subject_data_edits(
                    i,
                    e.get("name"),
                    e.get("weight_g"),
                    edits.get("starting_map_mmhg"),
                    edits.get("shock_volume_ml"),
                    edits.get("ending_map_mmhg"),
                    edits.get("resuscitation_volume_ml"),
                )
                if ok:
                    st.session_state.pop("_pending_weight_warning",None)
                    _clear_edit_subject_widgets(i)
                    st.toast("Subject data updated" if changed else "No subject data changes")
                    st.rerun()
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
    exp_id,name=str(exp["id"]),str(exp["name"])
    card_key=f"home_exp_card_{'completed' if completed else 'active'}_{exp_id}"

    with st.container(key=card_key):
        widths=[5.2,1.05,.98,.92] if completed else [4.8,1.05,.98,.88,.92]
        cols=st.columns(widths,vertical_alignment="center")

        with cols[0]:
            status_html=(
                '<span class="home-exp-status completed">✓</span>'
                if completed else
                '<span class="home-exp-status"></span>'
            )
            st.markdown(
                '<div class="home-exp-info">'
                f'{status_html}'
                '<div class="home-exp-text">'
                f'<div class="home-exp-name">{html.escape(name)}</div>'
                f'<div class="home-exp-meta">{int(exp["mouse_count"])} mice · Last saved {_fmt_epoch(exp["updated_at"])}</div>'
                '</div></div>',
                unsafe_allow_html=True,
            )

        with cols[1]:
            if st.button(
                "Open" if completed else "Resume",
                key=f"open_exp_{exp_id}",
                use_container_width=True,
            ):
                if completed:
                    if load_experiment_into_session(exp_id):
                        st.rerun()
                    st.error("Experiment could not be loaded.")
                else:
                    queue_run_preflight(
                        "resume",
                        exp_id=exp_id,
                        name=name,
                    )
                    st.rerun()

        with cols[2]:
            if st.button(
                "Rename",
                key=f"rename_exp_{exp_id}",
                use_container_width=True,
            ):
                rename_experiment_dialog(exp_id,name)

        if completed:
            with cols[3]:
                with st.container(key=f"home_delete_{exp_id}"):
                    if st.button(
                        "Delete",
                        key=f"delete_exp_{exp_id}",
                        use_container_width=True,
                    ):
                        delete_experiment_dialog(exp_id,name)
        else:
            with cols[3]:
                if st.button(
                    "End",
                    key=f"end_exp_{exp_id}",
                    use_container_width=True,
                ):
                    end_experiment_home_dialog(exp_id,name)
            with cols[4]:
                with st.container(key=f"home_delete_{exp_id}"):
                    if st.button(
                        "Delete",
                        key=f"delete_exp_{exp_id}",
                        use_container_width=True,
                    ):
                        delete_experiment_dialog(exp_id,name)

def render_experiment_home():
    st.markdown(
        """
        <div class="home-brand">
          <div class="home-brand-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <circle cx="12" cy="13" r="7.2"></circle>
              <path d="M12 5.8V3.2M9.4 3.2h5.2M17.1 7.8l1.8-1.8"></path>
              <path d="M12.8 8.6 9.9 13h2.5l-1.2 4.4 3.2-5h-2.5z"></path>
            </svg>
          </div>
          <div>
            <div class="home-brand-title">Shock Timer</div>
            <div class="home-brand-subtitle">Create a new experiment or resume a saved session.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Connected cloud storage is intentionally silent.
    # Only show an exception state when shared/cloud persistence is unavailable.
    if DATABASE_KIND != "postgres":
        with st.container(key="home_cloud_warning"):
            st.warning(
                "Cloud storage is unavailable. Local SQLite storage is active; "
                "sessions will not sync across computers."
            )

    with st.container(key="home_new_experiment"):
        st.markdown('<div class="home-section-title">New experiment</div>',unsafe_allow_html=True)

        with st.form("new_experiment_form",clear_on_submit=False):
            cols=st.columns([4.75,1.20,1.72],vertical_alignment="bottom")

            with cols[0]:
                experiment_name=st.text_input(
                    "Experiment name",
                    placeholder="e.g. Plasma resuscitation 08-22-2026",
                )

            with cols[1]:
                subject_count=st.number_input(
                    "Mouse subjects",
                    min_value=1,
                    max_value=64,
                    value=INITIAL_MOUSE_COUNT,
                    step=1,
                )

            with cols[2]:
                submitted=st.form_submit_button(
                    "Configure experiment",
                    use_container_width=True,
                    type="primary",
                )

        if submitted:
            begin_experiment_configuration(experiment_name,subject_count)

        error=st.session_state.pop("_home_error",None)
        if error:
            st.error(error)

    experiments=list_experiment_records()
    active=[x for x in experiments if x.get("completed_at") is None]
    completed=[x for x in experiments if x.get("completed_at") is not None]

    with st.container(key="home_active_section"):
        st.markdown(
            f'<div class="home-section-title">Active experiments'
            f'<span class="home-section-count">{len(active)}</span></div>',
            unsafe_allow_html=True,
        )

        if active:
            for exp in active:
                _render_experiment_card(exp,False)
        else:
            st.markdown(
                '<div class="home-empty-state">No active experiments.</div>',
                unsafe_allow_html=True,
            )

    with st.container(key="home_completed_section"):
        st.markdown(
            f'<div class="home-section-title">Completed experiments'
            f'<span class="home-section-count">{len(completed)}</span></div>',
            unsafe_allow_html=True,
        )

        if completed:
            for exp in completed:
                _render_experiment_card(exp,True)
        else:
            st.markdown(
                '<div class="home-empty-state">Completed experiments will appear here once all subjects are ended.</div>',
                unsafe_allow_html=True,
            )

    if st.session_state.get("_pending_weight_warning"):
        weight_warning_dialog()
    elif st.session_state.get("_pending_run_preflight"):
        run_preflight_dialog()
    elif st.session_state.get("_show_configuration_dialog"):
        configure_experiment_dialog()

def return_to_experiment_home():
    """
    Never discard the active in-memory record while persistent writes are
    unconfirmed. A failed retry opens the protected exit dialog instead.
    """
    if retry_unsaved_subjects():
        st.session_state.clear()
        st.rerun()
        return

    st.session_state["_show_storage_exit_dialog"]=True
    st.rerun()

# ============================================================
# ACTIVE EXPERIMENT DIALOGS
# ============================================================

def _render_timesheet_measurement_summary(i):
    summary_items = [
        ("Starting MAP", "—" if starting_map(i) is None else f"{starting_map(i):g} mmHg"),
        ("Ending MAP", "—" if ending_map(i) is None else f"{ending_map(i):g} mmHg"),
        ("Shock volume", "—" if shock_volume(i) is None else f"{shock_volume(i):g} mL"),
        (
            "Resuscitation volume",
            "—" if resuscitation_volume(i) is None else f"{resuscitation_volume(i):g} mL",
        ),
    ]
    summary_html = "".join(
        '<div class="ts-summary-card">'
        f'<div class="ts-summary-label">{html.escape(label)}</div>'
        f'<div class="ts-summary-value">{html.escape(value)}</div>'
        "</div>"
        for label, value in summary_items
    )
    st.markdown(
        f'<div class="ts-summary-grid">{summary_html}</div>',
        unsafe_allow_html=True,
    )


def _render_timesheet_anesthesia_summary(i):
    rows = anesthesia_summary_rows(i)
    if not rows:
        return

    st.markdown(
        '<div class="ts-section-title">Anesthesia summary</div>',
        unsafe_allow_html=True,
    )
    body = []
    for row_data in rows:
        body.append(
            "<tr>"
            f'<td class="ts-strong">{html.escape(str(row_data["dose"]))}</td>'
            f'<td>{html.escape(str(row_data["type"]))}</td>'
            f'<td>{html.escape(str(row_data["relative"]))}</td>'
            f'<td>{html.escape(str(row_data["absolute"]))}</td>'
            f'<td>{html.escape(str(row_data["weight"]))}</td>'
            f'<td>{html.escape(str(row_data["volume"]))}</td>'
            "</tr>"
        )

    st.markdown(
        """
        <div class="ts-table-wrap">
          <table class="ts-table">
            <colgroup>
              <col style="width:7%">
              <col style="width:12%">
              <col style="width:15%">
              <col style="width:31%">
              <col style="width:16%">
              <col style="width:19%">
            </colgroup>
            <thead>
              <tr>
                <th>Dose</th>
                <th>Type</th>
                <th>Relative</th>
                <th>Absolute time</th>
                <th>Weight</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
        """
        + "".join(body)
        + """
            </tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_timesheet_event_table(i, log):
    relative_times = relative_time_map(i, log)
    event_columns = [1.78, 1.02, 1.66, 2.35, .92]

    with st.container(key=f"timesheet_event_header_{i}"):
        header = st.columns(event_columns, gap="small")
        for column, label in zip(
            header,
            ["Event", "Relative time", "Absolute time", "Details", "Adjust"],
        ):
            with column:
                st.markdown(
                    f'<div class="ts-event-header">{html.escape(label)}</div>',
                    unsafe_allow_html=True,
                )

    for order, event in enumerate(log):
        event_id = event.get("_id") or f"row_{order}"
        relative = relative_times.get(
            event.get("_id"),
            relative_times.get(f"__order_{order}", "—"),
        )
        event_name = str(event.get("Event", ""))
        absolute = str(event.get("Absolute time", ""))
        details = str(event.get("Details", "")).strip() or "—"

        with st.container(key=f"timesheet_event_row_{i}_{order}"):
            row = st.columns(
                event_columns,
                gap="small",
                vertical_alignment="center",
            )
            values = (
                (row[0], event_name, "ts-event-cell primary"),
                (row[1], relative, "ts-event-cell"),
                (row[2], absolute, "ts-event-cell"),
                (row[3], details, "ts-event-cell details"),
            )
            for column, value, css_class in values:
                with column:
                    st.markdown(
                        f'<div class="{css_class}">{html.escape(value)}</div>',
                        unsafe_allow_html=True,
                    )

            with row[4]:
                if is_backtime_editable_event(event):
                    if st.button(
                        "Back-time",
                        key=f"backtime_select_{i}_{event_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"_backtime_target_{i}"] = event.get("_id")
                        st.rerun()
                else:
                    st.markdown(
                        '<div class="ts-adjust-placeholder"></div>',
                        unsafe_allow_html=True,
                    )


def _render_timesheet_backtime_panel(i, log):
    target = st.session_state.get(f"_backtime_target_{i}")
    if not target:
        return

    selected = next((event for event in log if event.get("_id") == target), None)
    selected_name = (
        str(selected.get("Event", "Selected event"))
        if selected
        else "Selected event"
    )

    with st.container(key=f"timesheet_backtime_panel_{i}"):
        st.markdown(
            f'<div class="ts-section-title">Back-time '
            f'{html.escape(selected_name)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="ts-note">Move this timer-start event earlier. '
            'The correction is recorded in the permanent event log.</div>',
            unsafe_allow_html=True,
        )

        amount = st.number_input(
            f"{UNIT_WORD.capitalize()} earlier",
            min_value=.1,
            step=.5,
            value=1.0,
            key=f"backtime_amount_{i}",
        )
        left, right = st.columns(2)

        with left:
            if st.button(
                "Cancel adjustment",
                key=f"backtime_cancel_{i}",
                use_container_width=True,
            ):
                st.session_state.pop(f"_backtime_target_{i}", None)
                st.rerun()

        with right:
            if st.button(
                "Apply back-time",
                key=f"backtime_apply_{i}",
                use_container_width=True,
                type="primary",
            ):
                ok, error = backtime_start_event(i, target, amount)
                if ok:
                    st.session_state.pop(f"_backtime_target_{i}", None)
                    st.rerun()
                st.warning(error)


@st.dialog("Timesheet", width="large")
def timesheet_dialog(i):
    st.markdown(
        f'<div class="ts-title">{html.escape(subject_name(i))} timesheet</div>',
        unsafe_allow_html=True,
    )
    _render_timesheet_measurement_summary(i)
    _render_timesheet_anesthesia_summary(i)

    st.markdown(
        '<div class="ts-section-title">Event log</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ts-note">{html.escape(weight_label(i))} · '
        f'{html.escape(APP_TIMEZONE)} · '
        'Timer-start events can be back-timed when a button was clicked late.'
        '</div>',
        unsafe_allow_html=True,
    )

    log = list(st.session_state.get(f"event_log_{i}", []))
    if not log:
        st.info("No events have been recorded.")
        return

    _render_timesheet_event_table(i, log)
    _render_timesheet_backtime_panel(i, log)


@st.dialog("Add comment")
def comment_dialog(i):
    key=f"comment_text_{i}"
    st.session_state.setdefault(key,"")
    st.markdown(f"**{html.escape(subject_name(i))}**",unsafe_allow_html=True)
    st.caption("Comments are timestamped and can be added even after this subject has ended.")
    st.text_area("Comment",key=key,height=130)
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"comment_cancel_{i}",use_container_width=True):
            st.session_state.pop(key,None)
            st.rerun()
    with right:
        if st.button("Accept",key=f"comment_accept_{i}",use_container_width=True,type="primary"):
            text=str(st.session_state.get(key,"")).strip()
            if not text:
                st.warning("Enter a comment.")
            else:
                log_event(i,"Comment",text)
                persist_subject(i)
                st.session_state.pop(key,None)
                st.rerun()

def _edit_subject_keys(i):
    return {
        "name": f"edit_name_{i}",
        "weight": f"edit_weight_{i}",
        "starting_map": f"edit_starting_map_{i}",
        "shock_volume": f"edit_shock_volume_{i}",
        "ending_map": f"edit_ending_map_{i}",
        "resuscitation_volume": f"edit_resuscitation_volume_{i}",
    }


def _initialize_edit_subject_widgets(i, keys):
    current_values = {
        "name": subject_name(i),
        "weight": float(mouse_weight(i) or 0.0),
        "starting_map": "" if starting_map(i) is None else f"{starting_map(i):g}",
        "shock_volume": "" if shock_volume(i) is None else f"{shock_volume(i):g}",
        "ending_map": "" if ending_map(i) is None else f"{ending_map(i):g}",
        "resuscitation_volume": (
            "" if resuscitation_volume(i) is None else f"{resuscitation_volume(i):g}"
        ),
    }
    for field, key in keys.items():
        st.session_state.setdefault(key, current_values[field])


def _parse_edit_subject_form(i, keys, availability):
    name, weight, profile_error = validate_mouse_name_weight(
        st.session_state.get(keys["name"]),
        st.session_state.get(keys["weight"]),
        f"Mouse {i}",
    )

    field_specs = (
        (
            "starting_map",
            starting_map,
            _parse_optional_map_value,
            "Starting MAP",
        ),
        (
            "shock_volume",
            shock_volume,
            _parse_optional_volume_ml,
            "Shock volume",
        ),
        (
            "ending_map",
            ending_map,
            _parse_optional_map_value,
            "Ending MAP",
        ),
        (
            "resuscitation_volume",
            resuscitation_volume,
            _parse_optional_volume_ml,
            "Resuscitation volume",
        ),
    )

    values = {}
    errors = [profile_error] if profile_error else []
    for field, current_getter, parser, label in field_specs:
        if availability[field]:
            value, error = parser(st.session_state.get(keys[field]), label)
        else:
            value, error = current_getter(i), None
        values[field] = value
        if error:
            errors.append(error)

    edits = {
        "starting_map_mmhg": values["starting_map"],
        "shock_volume_ml": values["shock_volume"],
        "ending_map_mmhg": values["ending_map"],
        "resuscitation_volume_ml": values["resuscitation_volume"],
    }
    return name, weight, edits, errors


def _commit_edit_subject_form(i, name, weight, edits):
    if weight_requires_confirmation(weight):
        queue_weight_warning(
            "edit_subject",
            [{"name": name, "weight_g": weight}],
            mouse=i,
            edits=edits,
        )
        st.rerun()
        return

    ok, error, changed = save_subject_data_edits(
        i,
        name,
        weight,
        edits["starting_map_mmhg"],
        edits["shock_volume_ml"],
        edits["ending_map_mmhg"],
        edits["resuscitation_volume_ml"],
    )
    if ok:
        _clear_edit_subject_widgets(i)
        st.toast("Subject data updated" if changed else "No subject data changes")
        st.rerun()
    st.warning(error)


@st.dialog("Edit subject", width="large")
def edit_subject_dialog(i):
    keys = _edit_subject_keys(i)
    availability = edit_subject_field_availability(i)
    _initialize_edit_subject_widgets(i, keys)

    st.markdown(
        f"### {html.escape(subject_name(i))} — correct subject data",
        unsafe_allow_html=True,
    )
    st.caption(
        "Name and weight can always be corrected. Measurement fields unlock only "
        "after this subject reaches the corresponding data-collection point."
    )

    profile_cols = st.columns([1.8, 1.0], gap="medium")
    with profile_cols[0]:
        st.text_input("Subject name", key=keys["name"])
    with profile_cols[1]:
        st.number_input(
            "Weight (g)",
            min_value=0.0,
            max_value=100.0,
            step=.1,
            format="%.1f",
            key=keys["weight"],
        )

    st.markdown("**Recorded measurements**")
    measurement_cols = st.columns(2, gap="medium")
    with measurement_cols[0]:
        st.text_input(
            "Starting MAP (mmHg)",
            key=keys["starting_map"],
            placeholder=(
                "Not recorded"
                if availability["starting_map"]
                else "Available after shock starts"
            ),
            disabled=not availability["starting_map"],
        )
        st.text_input(
            "Shock volume removed (mL)",
            key=keys["shock_volume"],
            placeholder=(
                "Not recorded"
                if availability["shock_volume"]
                else "Available when resuscitation starts"
            ),
            disabled=not availability["shock_volume"],
        )

    with measurement_cols[1]:
        st.text_input(
            "Ending MAP (mmHg)",
            key=keys["ending_map"],
            placeholder=(
                "Not recorded"
                if availability["ending_map"]
                else "Available at the end of resuscitation"
            ),
            disabled=not availability["ending_map"],
        )
        st.text_input(
            "Resuscitation volume given (mL)",
            key=keys["resuscitation_volume"],
            placeholder=(
                "Not recorded"
                if availability["resuscitation_volume"]
                else "Available at the end of resuscitation"
            ),
            disabled=not availability["resuscitation_volume"],
        )

    st.caption(
        "Unlocked measurement fields may be left blank to clear an incorrect "
        "recorded value."
    )

    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key=f"edit_cancel_{i}", use_container_width=True):
            _clear_edit_subject_widgets(i)
            st.rerun()

    with right:
        if st.button(
            "Save corrections",
            key=f"edit_save_{i}",
            use_container_width=True,
            type="primary",
        ):
            name, weight, edits, errors = _parse_edit_subject_form(
                i,
                keys,
                availability,
            )
            if errors:
                st.warning(" ".join(errors))
            else:
                _commit_edit_subject_form(i, name, weight, edits)


@st.cache_data(show_spinner=False)
def notification_sound_wav(sound_name):
    """Generate and cache the small WAV used by the Settings sound preview."""
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

def render_hidden_autoplay_audio(sound_name,key):
    """Autoplay a sound without exposing Streamlit's audio-player controls."""
    with st.container(key=f"hidden_audio_{key}"):
        st.audio(
            notification_sound_wav(str(sound_name)),
            format="audio/wav",
            autoplay=True,
        )

def queue_notification_sound_sample(): st.session_state["_pending_sound_sample"]={"token":uuid.uuid4().hex,"sound":str(st.session_state.get("settings_notification_sound",DEFAULT_NOTIFICATION_SOUND))}
def render_notification_sound_sample():
    pending=st.session_state.pop("_pending_sound_sample",None)
    if pending:
        render_hidden_autoplay_audio(
            pending.get("sound",DEFAULT_NOTIFICATION_SOUND),
            "settings_sample",
        )

@st.dialog("Settings",width="large")
def settings_dialog():
    st.markdown("### Global anesthesia schedule"); st.caption("These values apply to every mouse in this experiment. The first redose interval runs from the initial anesthesia dose; every redose after that uses the subsequent interval.")
    first=ordered_subject_indices()[0] if mouse_count() else 1; ik="settings_global_initial_anesthesia"; sk="settings_global_subsequent_anesthesia"; dk="settings_global_anesthesia_delay"; ek="settings_notification_sound_enabled"; nk="settings_notification_sound"
    st.session_state.setdefault(ik,int(st.session_state.get(f"anesthesia_initial_duration_{first}",DEFAULT_INITIAL_ANESTHESIA))); st.session_state.setdefault(sk,int(st.session_state.get(f"anesthesia_duration_{first}",DEFAULT_SUBSEQUENT_ANESTHESIA))); st.session_state.setdefault(dk,int(st.session_state.get(f"anesthesia_delay_duration_{first}",DEFAULT_ANESTHESIA_DELAY))); st.session_state.setdefault(ek,bool(st.session_state.get(f"notification_sound_enabled_{first}",DEFAULT_NOTIFICATION_SOUND_ENABLED))); st.session_state.setdefault(nk,str(st.session_state.get(f"notification_sound_{first}",DEFAULT_NOTIFICATION_SOUND)))
    cols=st.columns(3)
    with cols[0]: st.number_input(f"First redose ({UNIT_LABEL})",min_value=1,step=1,key=ik,help=f"Default: 45 {UNIT_WORD} after the initial anesthesia dose.")
    with cols[1]: st.number_input(f"Subsequent redoses ({UNIT_LABEL})",min_value=1,step=1,key=sk,help=f"Default: every 30 {UNIT_WORD} after each redose.")
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

def _parse_map_value(raw):
    try: value=float(raw)
    except (TypeError,ValueError): return None,"Enter a valid MAP in mmHg."
    if not (1.0 <= value <= 300.0): return None,"MAP must be between 1 and 300 mmHg."
    return round(value,1),None

def _parse_volume_ml(raw,label="Volume"):
    try: value=float(raw)
    except (TypeError,ValueError): return None,f"Enter a valid {label.lower()} in mL."
    if not (0.0 <= value <= 100.0): return None,f"{label} must be between 0 and 100 mL."
    return round(value,3),None

def _parse_optional_map_value(raw,label):
    raw=str(raw or "").strip()
    if not raw:
        return None,None
    value,error=_parse_map_value(raw)
    return value,(f"{label}: {error}" if error else None)

def _parse_optional_volume_ml(raw,label):
    raw=str(raw or "").strip()
    if not raw:
        return None,None
    value,error=_parse_volume_ml(raw,label)
    return value,error

@st.dialog("Starting blood pressure")
def starting_map_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} — starting MAP",unsafe_allow_html=True)
    st.caption("The shock timer has already started. Record the mean arterial pressure at shock start.")
    key=f"starting_map_entry_{i}"
    existing=starting_map(i)
    st.session_state.setdefault(key,"" if existing is None else f"{existing:g}")
    st.text_input("MAP (mmHg)",key=key,placeholder="e.g. 85")
    if st.button("Save starting MAP",key=f"starting_map_save_{i}",use_container_width=True,type="primary"):
        value,error=_parse_map_value(st.session_state.get(key))
        if error: st.warning(error)
        else:
            st.session_state[f"starting_map_mmhg_{i}"]=value
            shock_time=st.session_state.get(f"shock_start_{i}") or time.time()
            log_event(i,"Starting MAP",f"{value:g} mmHg",when_epoch=shock_time)
            persist_subject(i); st.session_state.pop(key,None); st.toast(f"Starting MAP saved: {value:g} mmHg"); st.rerun()

@st.dialog("Start resuscitation")
def shock_volume_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} — shock volume",unsafe_allow_html=True)
    st.caption("Resuscitation has started. Record the total volume removed by the end of the shock phase.")
    key=f"shock_volume_entry_{i}"
    existing=shock_volume(i)
    st.session_state.setdefault(key,"" if existing is None else f"{existing:g}")
    st.text_input("Shock volume removed (mL)",key=key,placeholder="e.g. 0.8")
    if st.button("Save shock volume",key=f"shock_volume_save_{i}",use_container_width=True,type="primary"):
        value,error=_parse_volume_ml(st.session_state.get(key),"Shock volume")
        if error:
            st.warning(error)
        else:
            st.session_state[f"shock_volume_ml_{i}"]=value
            event_time=st.session_state.get(f"resus_start_{i}") or time.time()
            log_event(i,"Shock volume",f"{value:g} mL removed",when_epoch=event_time)
            persist_subject(i)
            st.session_state.pop(key,None)
            st.toast(f"Shock volume saved: {value:g} mL")
            st.rerun()

@st.dialog("Ending measurements")
def ending_map_dialog(i,forced=False):
    st.markdown(f"### {html.escape(subject_name(i))} — ending measurements",unsafe_allow_html=True)
    st.caption("Record the final MAP and total resuscitation volume before ending this subject.")
    map_key=f"ending_map_entry_{i}"
    volume_key=f"resuscitation_volume_entry_{i}"
    existing_map=ending_map(i)
    existing_volume=resuscitation_volume(i)
    st.session_state.setdefault(map_key,"" if existing_map is None else f"{existing_map:g}")
    st.session_state.setdefault(volume_key,"" if existing_volume is None else f"{existing_volume:g}")
    st.text_input("Ending MAP (mmHg)",key=map_key,placeholder="e.g. 75")
    st.text_input("Resuscitation volume given (mL)",key=volume_key,placeholder="e.g. 0.8")
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"ending_map_cancel_{i}",use_container_width=True):
            st.session_state.pop(map_key,None)
            st.session_state.pop(volume_key,None)
            st.rerun()
    with right:
        if st.button("Save & end",key=f"ending_map_save_{i}",use_container_width=True,type="primary"):
            map_value,map_error=_parse_map_value(st.session_state.get(map_key))
            volume_value,volume_error=_parse_volume_ml(st.session_state.get(volume_key),"Resuscitation volume")
            errors=[error for error in (map_error,volume_error) if error]
            if errors:
                st.warning(" ".join(errors))
            else:
                st.session_state.pop(map_key,None)
                st.session_state.pop(volume_key,None)
                end_mouse(i,bool(forced),ending_map_mmhg=map_value,resuscitation_volume_ml=volume_value)
                st.rerun()

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

END_ALL_INPUT_PREFIXES = (
    "end_all_start_map_",
    "end_all_shock_volume_",
    "end_all_map_",
    "end_all_resus_volume_",
)


def _end_all_measurement_targets(remaining):
    return {
        "starting_map": [
            i for i in remaining
            if st.session_state.get(f"shock_start_{i}") is not None
            and starting_map(i) is None
        ],
        "shock_volume": [
            i for i in remaining
            if st.session_state.get(f"resus_start_{i}") is not None
            and shock_volume(i) is None
        ],
        "ending": [
            i for i in remaining
            if st.session_state.get(f"resus_start_{i}") is not None
        ],
    }


def _clear_end_all_inputs(remaining):
    for i in remaining:
        for prefix in END_ALL_INPUT_PREFIXES:
            st.session_state.pop(f"{prefix}{i}", None)


def _render_end_all_measurement_inputs(remaining, targets):
    for i in remaining:
        fields = []
        if i in targets["starting_map"]:
            key = f"end_all_start_map_{i}"
            st.session_state.setdefault(key, "")
            fields.append(("Starting MAP (mmHg)", key, "e.g. 85"))

        if i in targets["shock_volume"]:
            key = f"end_all_shock_volume_{i}"
            st.session_state.setdefault(key, "")
            fields.append(("Shock volume removed (mL)", key, "e.g. 0.8"))

        if i in targets["ending"]:
            map_key = f"end_all_map_{i}"
            resus_key = f"end_all_resus_volume_{i}"
            existing_map = ending_map(i)
            existing_resus = resuscitation_volume(i)
            st.session_state.setdefault(
                map_key,
                "" if existing_map is None else f"{existing_map:g}",
            )
            st.session_state.setdefault(
                resus_key,
                "" if existing_resus is None else f"{existing_resus:g}",
            )
            fields.extend([
                ("Ending MAP (mmHg)", map_key, "e.g. 75"),
                ("Resuscitation volume (mL)", resus_key, "e.g. 0.8"),
            ])

        if not fields:
            continue

        st.markdown(f"**{html.escape(subject_name(i))}**")
        cols = st.columns(2)
        for position, (label, key, placeholder) in enumerate(fields):
            with cols[position % 2]:
                st.text_input(label, key=key, placeholder=placeholder)


def _collect_end_all_measurements(targets):
    starting_maps = {}
    shock_volumes = {}
    ending_maps = {}
    resuscitation_volumes = {}
    errors = []

    for i in targets["starting_map"]:
        value, error = _parse_map_value(st.session_state.get(f"end_all_start_map_{i}"))
        if error:
            errors.append(f"{subject_name(i)} starting MAP: {error}")
        else:
            starting_maps[i] = value

    for i in targets["shock_volume"]:
        value, error = _parse_volume_ml(
            st.session_state.get(f"end_all_shock_volume_{i}"),
            "Shock volume",
        )
        if error:
            errors.append(f"{subject_name(i)} shock volume: {error}")
        else:
            shock_volumes[i] = value

    for i in targets["ending"]:
        map_value, map_error = _parse_map_value(
            st.session_state.get(f"end_all_map_{i}")
        )
        resus_value, resus_error = _parse_volume_ml(
            st.session_state.get(f"end_all_resus_volume_{i}"),
            "Resuscitation volume",
        )

        if map_error:
            errors.append(f"{subject_name(i)} ending MAP: {map_error}")
        else:
            ending_maps[i] = map_value

        if resus_error:
            errors.append(f"{subject_name(i)} resuscitation volume: {resus_error}")
        else:
            resuscitation_volumes[i] = resus_value

    return (
        starting_maps,
        shock_volumes,
        ending_maps,
        resuscitation_volumes,
        errors,
    )


@st.dialog("End all subjects", width="large")
def end_all_subjects_dialog():
    remaining = [i for i in ordered_subject_indices() if not is_ended(i)]
    targets = _end_all_measurement_targets(remaining)

    st.markdown("### End all subjects?")
    st.write(
        f"This ends {len(remaining)} remaining subject"
        f"{'s' if len(remaining) != 1 else ''} and downloads the aggregate timesheet."
    )

    if any(targets.values()):
        st.caption(
            "Required measurements that have already been reached must be "
            "completed before these subjects can end."
        )

    _render_end_all_measurement_inputs(remaining, targets)

    left, right = st.columns(2)
    with left:
        if st.button("Cancel", key="end_all_cancel", use_container_width=True):
            _clear_end_all_inputs(remaining)
            st.rerun()

    with right:
        if st.button(
            "End all subjects",
            key="end_all_confirm",
            use_container_width=True,
            type="primary",
        ):
            (
                starting_maps,
                shock_volumes,
                ending_maps,
                resuscitation_volumes,
                errors,
            ) = _collect_end_all_measurements(targets)

            if errors:
                st.warning(" ".join(errors))
            elif end_all_subjects_current_experiment(
                ending_maps,
                resuscitation_volumes,
                starting_maps,
                shock_volumes,
            ):
                _clear_end_all_inputs(remaining)
                queue_timesheet_auto_download()
                st.rerun()
            else:
                st.error(
                    "Subjects were ended locally, but persistent storage has "
                    "not confirmed the save yet."
                )


@st.dialog("Unsaved changes")
def storage_exit_dialog():
    pending=list(st.session_state.get("_unsaved_subjects",[]))
    names=[
        subject_name(i)
        for i in pending
        if 1<=int(i)<=mouse_count()
    ]

    st.error(
        "Recent changes are still only in this browser session. "
        "Navigation is blocked until persistent storage confirms the save."
    )
    if names:
        st.write("Pending: "+", ".join(names))

    if st.session_state.get("_storage_error"):
        st.caption(str(st.session_state.get("_storage_error")))

    st.download_button(
        "⇩ Download emergency backup",
        data=build_emergency_backup_text(),
        file_name=emergency_backup_filename(),
        mime="application/json",
        key="storage_exit_emergency_download",
        use_container_width=True,
    )

    left,right=st.columns(2)
    with left:
        if st.button(
            "Stay in experiment",
            key="storage_exit_cancel",
            use_container_width=True,
        ):
            st.session_state["_show_storage_exit_dialog"]=False
            st.rerun()

    with right:
        if st.button(
            "Retry save & leave",
            key="storage_exit_retry",
            use_container_width=True,
            type="primary",
        ):
            if retry_unsaved_subjects():
                st.session_state.clear()
                st.rerun()
            st.error(
                "Save is still unconfirmed. Download the emergency backup "
                "and retry when storage is available."
            )

@st.dialog("Add mouse")
def add_mouse_dialog():
    new_i=mouse_count()+1; nk,wk="_add_mouse_name","_add_mouse_weight"; st.session_state.setdefault(nk,f"Mouse {new_i}"); st.session_state.setdefault(wk,_default_entry_weight()); st.caption("Enter the mouse name and weight before adding it to the running experiment."); st.text_input("Mouse name",key=nk); st.number_input("Weight (g)",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk); left,right=st.columns(2)
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

def request_add_mouse_dialog():
    st.session_state["_pending_dialog"]={"mouse":0,"kind":"add_mouse"}
    st.session_state["_needs_full_rerun"]=True

def request_dialog(i,kind,**extra):
    st.session_state["_pending_dialog"]={"mouse":int(i),"kind":kind,**extra}
    st.session_state["_needs_full_rerun"]=True
def request_end_dialog(i,forced=False):
    if st.session_state.get(f"shock_start_{i}") is not None and starting_map(i) is None:
        request_dialog(i,"starting_map")
        return
    if st.session_state.get(f"resus_start_{i}") is not None:
        if shock_volume(i) is None:
            request_dialog(i,"shock_volume")
            return
        request_dialog(i,"ending_map",forced=bool(forced))
        return
    request_dialog(i,"end")
def _rerun_entire_app():
    """Force an app-level rerun even when invoked from inside a Streamlit fragment."""
    try:
        st.rerun(scope="app")
    except TypeError:
        # Compatibility fallback for Streamlit versions without the scope kwarg.
        st.rerun()

def render_pending_dialog():
    req=st.session_state.pop("_pending_dialog",None)
    if not req: return
    kind=req.get("kind")
    if kind=="add_mouse": add_mouse_dialog(); return
    i=int(req.get("mouse",0))
    if not 1<=i<=mouse_count(): return
    if kind=="starting_map": starting_map_dialog(i); return
    if kind=="shock_volume": shock_volume_dialog(i); return
    if kind=="ending_map": ending_map_dialog(i,bool(req.get("forced",False))); return
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

def collect_attention_items(wall_now, indices=None):
    """Return sticky alerts for time-based workflow events only."""
    if indices is None:
        indices=ordered_subject_indices()

    sticky=st.session_state.setdefault("_sticky_alerts",{})
    active_keys=set()

    for i in indices:
        if is_ended(i):
            clear_mouse_alerts(i)
            continue

        now=effective_now(i,wall_now)

        # Data-entry recovery states (for example Enter MAP / Enter shock vol)
        # intentionally stay in the row action model, not the global alert/audio
        # system. Only time-based workflow events belong in this collection.
        for event,remaining in get_upcoming_events(i,now):
            key=alert_key(i,event)
            active_keys.add(key)
            level=urgency_for_remaining(remaining)

            if level in ("orange","red"):
                sticky[key]={
                    "mouse":i,
                    "name":subject_name(i),
                    "event":event,
                    "remaining":remaining,
                    "level":level,
                }

    for key in tuple(sticky):
        if key not in active_keys:
            sticky.pop(key,None)

    items=[]
    for alert in sticky.values():
        item=dict(alert)
        item["targets"]=action_targets_for_alert(
            item["mouse"],
            item["event"],
            item["remaining"],
        )
        items.append(item)

    return sorted(
        items,
        key=lambda item:(
            0 if item["level"]=="red" else 1,
            item["remaining"],
        ),
    )


def render_attention_snapshot(items):
    payload_items=[]
    for x in items:
        mouse=int(x["mouse"])
        payload_items.append({
            "mouse":mouse,
            "name":x["name"],
            "event":x["event"],
            "level":x["level"],
            "remaining":float(x.get("remaining",0.0)),
            "targets":x.get("targets",[]),
            "soundEnabled":bool(
                st.session_state.get(
                    f"notification_sound_enabled_{mouse}",
                    DEFAULT_NOTIFICATION_SOUND_ENABLED,
                )
            ),
            "soundName":str(
                st.session_state.get(
                    f"notification_sound_{mouse}",
                    DEFAULT_NOTIFICATION_SOUND,
                )
            ),
        })

    payload={"items":payload_items}
    encoded=base64.b64encode(
        json.dumps(payload,separators=(",",":")).encode()
    ).decode()
    st.html(
        f'<div data-lab-attention-snapshot="{encoded}" '
        f'style="display:none!important"></div>'
    )


def _safe_export_filename_part(value):
    text=str(value or "experiment").strip()
    text=re.sub(r"[^A-Za-z0-9._-]+","_",text)
    text=re.sub(r"_+","_",text).strip("._-")
    return text or "experiment"

def timesheet_export_filename():
    experiment=_safe_export_filename_part(st.session_state.get("_active_experiment_name","experiment"))
    stamp=wall_datetime().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{experiment}_{stamp}_timesheets.txt"

def queue_timesheet_auto_download():
    st.session_state["_pending_auto_download"]={
        "token":uuid.uuid4().hex,
        "filename":timesheet_export_filename(),
        "content_b64":base64.b64encode(build_all_timesheets_text().encode()).decode(),
    }
def render_pending_auto_download_marker():
    pending=st.session_state.get("_pending_auto_download")
    if pending: st.html(f'<div data-lab-auto-download-token="{html.escape(pending["token"],quote=True)}" data-lab-auto-download-filename="{html.escape(pending["filename"],quote=True)}" data-lab-auto-download-content="{pending["content_b64"]}" style="display:none!important"></div>')

def render_run_active_marker():
    st.html(
        '<div data-lab-run-active="1" '
        'style="display:none!important"></div>'
    )

BROWSER_HELPERS_HTML = r"""
    <script>
    (()=>{
      const root=window.parent;
      const doc=root.document;
      const BAR='lab-attention-v40',P='lab-next-primary-v40',D='lab-next-delay-v40';

      let bar=doc.getElementById(BAR);
      if(!bar){
        bar=doc.createElement('div');
        bar.id=BAR;
        bar.style.cssText='display:none;position:fixed;z-index:999999';
        doc.body.appendChild(bar);
      }

      if(!doc.getElementById('lab-v40-browser-style')){
        const s=doc.createElement('style');
        s.id='lab-v40-browser-style';
        s.textContent=`.${P} button{outline:2px solid rgba(245,161,38,.55)!important;outline-offset:1px}.${D} button{outline:2px solid rgba(184,122,244,.5)!important;outline-offset:1px}`;
        doc.head.appendChild(s);
      }

      /*
        Persist audio state on the parent window. This survives Streamlit
        component remounts and prevents the notification from being delayed
        until some later click.
      */
      const A=root.__shockTimerAudioState||(root.__shockTimerAudioState={
        ctx:null,
        unlocked:false,
        bound:false,
        timers:{},
        dueAt:{},
        sounded:new Set(),
        active:new Set()
      });

      function getAudioContext(){
        try{
          if(!A.ctx){
            const C=root.AudioContext||root.webkitAudioContext;
            if(C) A.ctx=new C();
          }
          return A.ctx;
        }catch(_){
          return null;
        }
      }

      function primeAudio(c){
        try{
          const o=c.createOscillator();
          const g=c.createGain();
          g.gain.setValueAtTime(.00001,c.currentTime);
          o.frequency.value=40;
          o.connect(g);
          g.connect(c.destination);
          o.start();
          o.stop(c.currentTime+.025);
          A.unlocked=true;
        }catch(_){}
      }

      function unlockAudio(){
        const c=getAudioContext();
        if(!c) return;
        if(c.state==='suspended'){
          c.resume().then(()=>primeAudio(c)).catch(()=>{});
        }else{
          primeAudio(c);
        }
      }

      if(!A.bound){
        ['pointerdown','mousedown','touchstart','keydown'].forEach(ev=>{
          doc.addEventListener(ev,unlockAudio,{capture:true,passive:true});
        });
        A.bound=true;
      }

      function beep(name){
        try{
          const c=getAudioContext();

          /*
            Do not queue a blocked sound. If audio was not unlocked when the
            timer became due, mark the due event as handled rather than playing
            it late on a later button click.
          */
          if(!c||!A.unlocked||c.state!=='running') return false;

          const note=(f,t,d)=>{
            const o=c.createOscillator();
            const g=c.createGain();
            o.frequency.value=f;
            g.gain.setValueAtTime(.0001,c.currentTime+t);
            g.gain.exponentialRampToValueAtTime(.14,c.currentTime+t+.01);
            g.gain.exponentialRampToValueAtTime(.0001,c.currentTime+t+d);
            o.connect(g);
            g.connect(c.destination);
            o.start(c.currentTime+t);
            o.stop(c.currentTime+t+d+.02);
          };

          if(name==='Double beep'){
            note(760,0,.12);
            note(760,.20,.12);
          }else if(name==='Beep'){
            note(880,0,.18);
          }else{
            note(660,0,.14);
            note(990,.11,.22);
          }
          return true;
        }catch(_){
          return false;
        }
      }

      function alertKey(item){
        return String(item.mouse)+':'+String(item.event);
      }

      function cancelTimer(key){
        if(A.timers[key]){
          clearTimeout(A.timers[key]);
          delete A.timers[key];
        }
        delete A.dueAt[key];
      }

      function scheduleDue(item){
        const key=alertKey(item);
        const remaining=Number(item.remaining);
        if(!Number.isFinite(remaining)||remaining<=0) return;

        const dueAt=Date.now()+(remaining*1000);
        const prior=A.dueAt[key];

        // A meaningful due-time change means pause/delay/back-timing changed.
        if(prior&&Math.abs(prior-dueAt)<350) return;

        cancelTimer(key);
        A.dueAt[key]=dueAt;

        A.timers[key]=setTimeout(()=>{
          delete A.timers[key];
          delete A.dueAt[key];

          // The task may have been resolved before the scheduled boundary.
          if(!A.active.has(key)) return;

          if(!A.sounded.has(key)){
            if(item.soundEnabled) beep(item.soundName||'Chime');
            A.sounded.add(key);
          }
        },Math.max(0,dueAt-Date.now()));
      }

      let last='',dismissed='',targets=[];

      function apply(encoded){
        let p;
        try{
          p=JSON.parse(atob(encoded));
        }catch(_){
          return;
        }

        const items=p.items||[];

        if(encoded!==last) dismissed='';
        last=encoded;

        targets=[];
        for(const item of items){
          for(const t of(item.targets||[])){
            if(!targets.some(x=>x.key===t.key&&x.style===t.style)){
              targets.push(t);
            }
          }
        }

        const nextActive=new Set(items.map(alertKey));

        // Remove timers/state for alerts that have been resolved.
        for(const key of Object.keys(A.timers)){
          if(!nextActive.has(key)) cancelTimer(key);
        }
        for(const key of [...A.sounded]){
          if(!nextActive.has(key)) A.sounded.delete(key);
        }
        A.active=nextActive;

        for(const item of items){
          const key=alertKey(item);
          const remaining=Number(item.remaining);

          if(item.level==='red'||remaining<=0){
            cancelTimer(key);
            if(!A.sounded.has(key)){
              if(item.soundEnabled) beep(item.soundName||'Chime');
              // Mark handled even if browser audio was not yet unlocked:
              // never play this notification late.
              A.sounded.add(key);
            }
          }else{
            // A recurring event (e.g. anesthesia redose) has been reset.
            if(remaining>0&&A.sounded.has(key)) A.sounded.delete(key);

            // Schedule directly from remaining time so sound is tied to the
            // actual due boundary rather than a later Streamlit rerender.
            if(item.level==='orange'&&remaining>0){
              scheduleDue(item);
            }else{
              cancelTimer(key);
            }
          }
        }

        if(!items.length||dismissed===encoded){
          bar.style.display='none';
        }else{
          bar.innerHTML=items.map(
            i=>`<span class="${i.level}" style="margin-right:14px">${i.name}: ${i.event}</span>`
          ).join('')+`<span class="x">×</span>`;
          bar.querySelector('.x').onclick=()=>{
            dismissed=encoded;
            bar.style.display='none';
          };
          bar.style.display='block';
        }
      }

      function highlights(){
        const wanted=new Map(targets.map(t=>[t.key,t.style==='delay'?D:P]));

        doc.querySelectorAll(`.${P},.${D}`).forEach(n=>{
          const kc=[...n.classList].find(c=>c.startsWith('st-key-'));
          const k=kc?kc.slice(7):null;
          const w=k?wanted.get(k):null;
          if(!w||!n.classList.contains(w)) n.classList.remove(P,D);
        });

        for(const[k,c]of wanted.entries()){
          doc.querySelectorAll(`.st-key-${k}`).forEach(n=>{
            const b=n.querySelector('button');
            if(b&&!b.disabled){
              n.classList.remove(P,D);
              n.classList.add(c);
            }
          });
        }
      }

      function full(){
        const w=doc.querySelector('.st-key-fullscreen_view');
        if(!w||w.dataset.bound==='1') return;
        const b=w.querySelector('button');
        if(!b) return;

        w.dataset.bound='1';
        b.addEventListener('click',()=>{
          const r=doc.documentElement;
          if(!doc.fullscreenElement&&r.requestFullscreen){
            r.requestFullscreen().catch(()=>{});
          }else if(doc.fullscreenElement&&doc.exitFullscreen){
            doc.exitFullscreen().catch(()=>{});
          }
        },true);
      }

      function download(){
        const ms=doc.querySelectorAll('[data-lab-auto-download-token]');
        if(!ms.length) return;

        const m=ms[ms.length-1];
        const t=m.dataset.labAutoDownloadToken;
        const e=m.dataset.labAutoDownloadContent;

        if(!t||!e||doc.documentElement.dataset.labLastDownload===t) return;

        try{
          const bin=atob(e);
          const bytes=new Uint8Array(bin.length);
          for(let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);

          const url=URL.createObjectURL(
            new Blob([bytes],{type:'text/plain;charset=utf-8'})
          );
          const a=doc.createElement('a');
          a.href=url;
          a.download=m.dataset.labAutoDownloadFilename||'shock_timer_timesheets.txt';
          doc.body.appendChild(a);
          doc.documentElement.dataset.labLastDownload=t;
          a.click();
          a.remove();
          setTimeout(()=>URL.revokeObjectURL(url),1500);
        }catch(_){}
      }

      /*
        Autofocus data-entry dialogs. Streamlit does not expose a reliable
        per-widget autofocus option, so detect the visible dialog in the parent
        document and select its first editable text/numeric field. Reset the
        signature when the dialog closes so reopening the same dialog focuses
        it again.
      */
      const F=root.__shockTimerDialogFocusState||(root.__shockTimerDialogFocusState={
        signature:null
      });

      function closeSubjectMenuForDialog(dialog){
        /*
          The subject popover can otherwise remain visually open after one of
          its buttons launches a Streamlit dialog. Close only the individual
          subject menu, not unrelated selects/popovers inside the dialog.
        */
        const popovers=[...doc.querySelectorAll(
          '[data-testid="stPopoverBody"],[data-baseweb="popover"]'
        )].filter(p=>p.getClientRects().length && !dialog.contains(p));

        const subjectPopover=popovers.find(p=>{
          const t=(p.textContent||'');
          return t.includes('View timesheet') &&
                 t.includes('Add comment') &&
                 t.includes('Edit subject');
        });

        if(!subjectPopover) return;

        const trigger=[...doc.querySelectorAll('button[aria-expanded="true"]')]
          .find(b=>{
            if(dialog.contains(b)) return false;
            const t=(b.textContent||'').trim();
            return t==='⋮' || t.includes('⋮');
          });

        if(trigger){
          try{
            trigger.click();
            return;
          }catch(_){}
        }

        // Fallback for Streamlit/BaseWeb versions that do not expose
        // aria-expanded on the popover trigger.
        try{
          subjectPopover.dispatchEvent(new KeyboardEvent('keydown',{
            key:'Escape',
            code:'Escape',
            bubbles:true,
            cancelable:true
          }));
        }catch(_){}
      }

      function autofocusDialog(){
        const dialogs=[...doc.querySelectorAll(
          '[data-testid="stDialog"] [role="dialog"],[role="dialog"][aria-modal="true"]'
        )].filter(d=>d.getClientRects().length);

        if(!dialogs.length){
          F.signature=null;
          return;
        }

        const dialog=dialogs[dialogs.length-1];
        closeSubjectMenuForDialog(dialog);

        const target=dialog.querySelector(
          '[data-testid="stTextInput"] input:not(:disabled):not([readonly]),' +
          '[data-testid="stNumberInput"] input:not(:disabled):not([readonly]),' +
          '[data-testid="stTextArea"] textarea:not(:disabled):not([readonly])'
        );
        if(!target) return;

        const heading=[...dialog.querySelectorAll('h1,h2,h3,strong')]
          .slice(0,2)
          .map(n=>(n.textContent||'').trim())
          .join('|');
        const label=target.getAttribute('aria-label')||
                    target.getAttribute('placeholder')||
                    target.getAttribute('name')||'entry';
        const signature=heading+'|'+label;

        if(F.signature===signature) return;

        try{
          target.focus({preventScroll:true});
          if(typeof target.select==='function') target.select();
          if(doc.activeElement===target) F.signature=signature;
        }catch(_){}
      }

      const W=root.__shockTimerWakeState||(root.__shockTimerWakeState={
        lock:null,
        bound:false,
        requesting:false
      });

      async function maintainWakeLock(){
        const active=!!doc.querySelector('[data-lab-run-active="1"]');
        const wakeApi=root.navigator&&root.navigator.wakeLock;

        if(!active){
          if(W.lock){
            try{ await W.lock.release(); }catch(_){}
            W.lock=null;
          }
          return;
        }

        if(!wakeApi||!wakeApi.request||doc.visibilityState!=='visible'){
          return;
        }

        if(W.lock||W.requesting) return;
        W.requesting=true;
        try{
          const lock=await wakeApi.request('screen');
          W.lock=lock;
          lock.addEventListener('release',()=>{
            if(W.lock===lock) W.lock=null;
          });
        }catch(_){
          W.lock=null;
        }finally{
          W.requesting=false;
        }
      }

      if(!W.bound){
        doc.addEventListener('visibilitychange',()=>{
          if(doc.visibilityState==='visible') maintainWakeLock();
        });
        W.bound=true;
      }

      function preflightStatus(){
        const nodes=doc.querySelectorAll('[data-lab-preflight-browser-status]');
        if(!nodes.length) return;

        const C=root.AudioContext||root.webkitAudioContext;
        const audioSupported=!!C;
        const wakeSupported=!!(
          root.navigator&&
          root.navigator.wakeLock&&
          root.navigator.wakeLock.request
        );

        const audioReady=audioSupported&&A.unlocked;
        const html=
          `<span class="${audioReady?'ok':'warn'}">`+
          `Alert audio: ${audioReady?'ready':'needs test/interaction'}</span>`+
          ` &nbsp;·&nbsp; `+
          `<span class="${wakeSupported?'ok':'warn'}">`+
          `Screen wake: ${wakeSupported?'supported':'manual keep-awake required'}</span>`;

        nodes.forEach(n=>{ n.innerHTML=html; });
      }

      function poll(){
        const ss=doc.querySelectorAll('[data-lab-attention-snapshot]');
        if(ss.length){
          const e=ss[ss.length-1].dataset.labAttentionSnapshot;
          if(e&&e!==last) apply(e);
        }
        highlights();
        full();
        download();
        autofocusDialog();
        preflightStatus();
        maintainWakeLock();
      }

      poll();
      setInterval(poll,100);
    })();
    </script>
    """


def install_browser_helpers():
    """Mount the browser-only helper layer used by the Streamlit UI."""
    st.iframe(BROWSER_HELPERS_HTML, width=1, height=1, tab_index=-1)


def render_storage_failure_warning():
    if not st.session_state.get("_storage_error"):
        return

    with st.container(key="persistent_storage_failure"):
        st.error(
            "SAVE WARNING: recent changes have not been confirmed by "
            "persistent storage. The experiment remains available in this "
            "browser session."
        )
        st.caption(str(st.session_state.get("_storage_error")))

        retry_col,backup_col=st.columns(2)
        with retry_col:
            if st.button(
                "Retry save",
                key="retry_storage_save",
                use_container_width=True,
                type="primary",
            ):
                if retry_unsaved_subjects():
                    st.toast("Persistent save confirmed.")
                    st.rerun()
                st.error("Save is still unconfirmed.")

        with backup_col:
            st.download_button(
                "⇩ Emergency backup",
                data=build_emergency_backup_text(),
                file_name=emergency_backup_filename(),
                mime="application/json",
                key="storage_warning_emergency_download",
                use_container_width=True,
            )

# ============================================================
# DISPLAY / WORKFLOW
# ============================================================


def mouse_status_tone(i,now):
    if is_paused(i) or is_ended(i) or st.session_state.get(f"experiment_start_{i}") is None: return "gray"
    levels=[urgency_for_remaining(rem) for _,rem in get_upcoming_events(i,now)]; return "red" if "red" in levels else "orange" if "orange" in levels else "green"

def get_next_event_display(i,now):
    if is_ended(i): return "Ended","gray"
    if st.session_state.get(f"experiment_start_{i}") is None: return "Not started","gray"
    if (
        st.session_state.get(f"shock_start_{i}") is not None
        and starting_map(i) is None
    ):
        return "Starting MAP required","red"
    if (
        st.session_state.get(f"resus_start_{i}") is not None
        and shock_volume(i) is None
    ):
        return "Shock volume required","red"
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
    if is_ended(i): return "Ended",weight_label(i),"gray"
    start=st.session_state.get(f"anesthesia_start_{i}")
    if start is None: return "Not started",weight_label(i),"gray"
    remaining=anesthesia_remaining(i,now); tone=urgency_for_remaining(remaining); label="First redose" if anesthesia_dose_count(i)<=1 else "Redose"; return (f"{label} due",weight_label(i),tone) if remaining<=0 else (f"{label} in {format_timer(remaining)}",weight_label(i),tone if tone!="normal" else "normal")

def render_anesthesia_controls(i):
    delay=st.session_state[f"anesthesia_delay_duration_{i}"]
    redose=st.session_state.get(f"anesthesia_initial_duration_{i}",DEFAULT_INITIAL_ANESTHESIA) if anesthesia_dose_count(i)<=1 else st.session_state.get(f"anesthesia_duration_{i}",DEFAULT_SUBSEQUENT_ANESTHESIA)
    disabled=st.session_state.get(f"experiment_start_{i}") is None or st.session_state.get(f"anesthesia_start_{i}") is None or is_paused(i) or is_ended(i)

    with st.container(key=f"anesthesia_controls_{i}"):
        cols=st.columns(2,gap="small")
        with cols[0]:
            with st.container(key=f"anesthesia_redose_action_{i}"):
                st.button(
                    f"Redose ({redose}{UNIT_SHORT})",
                    key=f"redose_{i}",
                    use_container_width=True,
                    disabled=disabled,
                    on_click=start_or_redose_anesthesia,
                    args=(i,),
                    help="Record the anesthesia redose now.",
                )
        with cols[1]:
            with st.container(key=f"anesthesia_delay_action_{i}"):
                st.button(
                    f"Delay ({delay}{UNIT_SHORT})",
                    key=f"delay_{i}",
                    use_container_width=True,
                    disabled=disabled,
                    on_click=delay_anesthesia_reminder,
                    args=(i,),
                    help="Delay the reminder from this moment.",
                )

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
    if shock is not None and starting_map(i) is None:
        return "enter_starting_map"
    if resus is not None and shock_volume(i) is None:
        return "enter_shock_volume"
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
    if action is None:
        st.button(
            "Ended",
            key=f"ended_display_button_{i}",
            disabled=True,
            use_container_width=True,
        )
        return

    if action=="enter_starting_map":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "Enter MAP",
                key=f"primary_enter_starting_map_{i}",
                use_container_width=True,
                on_click=request_dialog,
                args=(i,"starting_map"),
            )
        return

    if action=="enter_shock_volume":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "Enter shock vol",
                key=f"primary_enter_shock_volume_{i}",
                use_container_width=True,
                on_click=request_dialog,
                args=(i,"shock_volume"),
            )
        return

    mapping={
        "resume":("▶ Resume",toggle_pause),
        "start_anesthesia":("▷ Start",start_or_redose_anesthesia),
        "start_board":("▷ Start board",start_board),
        "start_shock":("⚡ Start shock",start_shock),
        "start_resus":("♥ Start resus",start_resuscitation),
    }
    if action in mapping:
        label,fn=mapping[action]
        wrapper=(
            f"primary_start_anesthesia_wrapper_{i}"
            if action=="start_anesthesia"
            else f"primary_action_{i}"
        )
        with st.container(key=wrapper):
            st.button(
                label,
                key=f"primary_{action}_{i}",
                use_container_width=True,
                on_click=fn,
                args=(i,),
            )
        return

    if action=="end":
        with st.container(key=f"primary_action_{i}"):
            st.button(
                "■ End",
                key=f"primary_end_{i}",
                use_container_width=True,
                on_click=request_end_dialog,
                args=(i,False),
            )
        return

    with st.container(key=f"primary_pause_{i}"):
        st.button(
            "Ⅱ Pause",
            key=f"primary_pause_button_{i}",
            use_container_width=True,
            on_click=toggle_pause,
            args=(i,),
        )

def force_advance_label(i,now):
    if is_ended(i) or is_paused(i): return None
    board,shock,resus=st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}")
    if board is not None and shock is None and not board_is_complete(i,now):
        return "⏭ Force start shock"
    if shock is not None and resus is None:
        if starting_map(i) is None:
            return None
        if not shock_is_complete(i,now):
            return "⏭ Force start resus"
    if resus is not None:
        if shock_volume(i) is None:
            return None
        if not resus_is_complete(i,now):
            return "⏭ Force end subject"
    return None

def force_advance(i):
    now=time.time(); label=force_advance_label(i,now)
    if label=="⏭ Force start shock": start_shock(i,True)
    elif label=="⏭ Force start resus": start_resuscitation(i,True)
    elif label=="⏭ Force end subject": request_end_dialog(i,True)

def _process_menu(i,selection):
    """
    Handle one individual-subject menu action.

    This function is used as a button callback inside the timer fragment, so it
    deliberately does not call st.rerun(). The button interaction already
    triggers a fragment rerun. Dialog requests are promoted to a full-app rerun
    by show_timers() before the fragment renders again.
    """
    if not selection:
        return
    if selection=="View timesheet":
        request_dialog(i,"timesheet")
    elif selection=="Add comment":
        request_dialog(i,"comment")
    elif selection=="Edit subject":
        request_dialog(i,"edit")
    elif selection in ("Ⅱ Pause","▶ Resume"):
        toggle_pause(i)
    elif selection=="↑ Move up":
        move_subject(i,-1)
    elif selection=="↓ Move down":
        move_subject(i,1)
    elif selection.startswith("↶ Undo"):
        undo_last_stage_action(i)
    elif selection.startswith("⏭ Force"):
        force_advance(i)
    elif selection=="↻ Reset subject":
        request_dialog(i,"reset")
    elif selection=="■ End subject":
        request_end_dialog(i,False)

def render_overflow_control(i,now,reorder_peers=None):
    # Record-management actions are always available, including before the first
    # timer starts and after the subject has ended.
    options=["View timesheet","Add comment","Edit subject"]

    if reorder_peers is None:
        order_now=time.time()
        group=_reorder_group(i,order_now)
        peers=[
            j for j in ordered_subject_indices()
            if _reorder_group(j,order_now)==group
        ]
    else:
        peers=reorder_peers
    if i in peers:
        pos=peers.index(i)
        if pos>0:
            options.append("↑ Move up")
        if pos<len(peers)-1:
            options.append("↓ Move down")

    # Timer-changing actions remain limited to active subjects.
    undo=latest_undo_action(i)
    if undo and not is_ended(i):
        options.append(f"↶ Undo {_undo_label(undo)}")

    force=force_advance_label(i,now)
    if force:
        options.append(force)

    if (
        st.session_state.get(f"experiment_start_{i}") is not None
        and not is_ended(i)
    ):
        options += [
            "▶ Resume" if is_paused(i) else "Ⅱ Pause",
            "↻ Reset subject",
            "■ End subject",
        ]

    # Always use the popover/button path. It is reliable inside the 1-second
    # Streamlit fragment and works identically for active and ended rows.
    with st.container(key=f"mouse_action_menu_{i}"):
        with st.popover("⋮",use_container_width=True):
            for option in options:
                st.button(
                    option,
                    key=f"subject_menu_{i}_{option}",
                    use_container_width=True,
                    on_click=_process_menu,
                    args=(i,option),
                )

# ============================================================
# V40 CARD ROW
# ============================================================

def _v40_mouse_icon():
    return ('<span class="lab-mouse-icon" aria-hidden="true"><svg viewBox="0 0 32 32">'
            '<path d="M8.4 18.6c0-5.3 3.6-9.1 8.7-9.1 4.2 0 7.4 2.5 8.4 6.1 2.6.1 4.4 1.5 4.4 3.5 0 2.4-2.3 4-5.5 4h-1.2c-1.6 2.1-4.1 3.4-7.1 3.4-4.6 0-7.7-3-7.7-7.9Z"/>'
            '<path d="M11.1 10.8c-1.6-1.6-1.7-4.2-.1-5.7 1.6-1.5 4.4-.9 5.4 1.4"/>'
            '<path d="M18.9 9.7c.1-2.3 2.1-4.3 4.4-4.2 2.4.1 3.8 2.4 3.1 4.4"/><circle cx="21.2" cy="15.3" r=".8"/><path d="M8.6 21.7c-3.2.2-5.5 1.5-6.4 3.7"/></svg></span>')

def _v40_next_event_html(text,tone):
    raw=str(text)
    tone_class="" if tone=="normal" else f" {tone}"

    if " in " in raw:
        prefix,metric=raw.rsplit(" ",1)
        if prefix=="Anesthesia in":
            prefix="Anes. in"
        return (
            '<div class="lab-cell lab-next-event-cell">'
            '<div class="lab-mini-label">Next event</div>'
            '<div class="lab-next-inline">'
            f'<span class="lab-next-copy">{html.escape(prefix)}</span>'
            f'<span class="lab-next-metric{tone_class}">{html.escape(metric)}</span>'
            '</div>'
            '</div>'
        )

    # Keep all non-countdown states on the exact same second row.
    display=raw.replace("Anesthesia","Anes.")
    primary_class=f"lab-next-inline lab-primary-text {tone}" if tone!="normal" else "lab-next-inline lab-primary-text"
    return (
        '<div class="lab-cell lab-next-event-cell">'
        '<div class="lab-mini-label">Next event</div>'
        f'<div class="{primary_class}">{html.escape(display)}</div>'
        '</div>'
    )

def render_mouse_row(i, wall_now, finished=False, reorder_peers=None):
    """Render one subject row. Timer calculations use a single effective timestamp."""
    now = effective_now(i, wall_now)
    experiment_start = st.session_state.get(f"experiment_start_{i}")
    total = elapsed_from(experiment_start, now) if experiment_start is not None else 0.0

    with st.container(key=f"mouse_row_{i}"):
        st.markdown(
            f'<span class="v40-row-state" '
            f'data-v40-finished="{"true" if finished else "false"}"></span>',
            unsafe_allow_html=True,
        )
        cols = st.columns(
            RUNNING_ROW_COLUMNS,
            gap="small",
            vertical_alignment="center",
        )

        # Subject identity. The hidden MAP placeholder preserves layout before
        # the starting pressure is recorded.
        with cols[0]:
            tone = mouse_status_tone(i, now)
            paused_html = ""
            if is_paused(i):
                pause_started = st.session_state.get(f"pause_started_{i}")
                paused_html = (
                    f'<div class="lab-paused-label">'
                    f'Paused {format_timer(elapsed_from(pause_started, wall_now) if pause_started else 0)}'
                    f'</div>'
                )

            map_value = starting_map(i)
            starting_map_html = (
                f'<div class="lab-starting-map">Starting MAP {map_value:g} mmHg</div>'
                if map_value is not None
                else (
                    '<div class="lab-starting-map lab-starting-map-placeholder">'
                    'Starting MAP 000 mmHg</div>'
                )
            )

            st.markdown(
                f'<div class="lab-mouse-wrap">'
                f'<span class="lab-dot {tone}"></span>'
                f'<div class="lab-mouse-identity">'
                f'{_v40_mouse_icon()}'
                f'<div class="lab-subject-copy">'
                f'{paused_html}'
                f'<div class="lab-mouse-name">{html.escape(subject_name(i))}</div>'
                f'{starting_map_html}'
                f'</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with cols[1]:
            next_text, next_tone = get_next_event_display(i, now)
            st.markdown(
                _v40_next_event_html(next_text, next_tone),
                unsafe_allow_html=True,
            )

        with cols[2]:
            st.markdown(
                f'<div class="lab-cell lab-total-cell">'
                f'<div class="lab-mini-label">Total</div>'
                f'<div class="lab-total">{format_total_elapsed(total)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with cols[3]:
            st.markdown(workflow_html(i, now), unsafe_allow_html=True)

        with cols[4]:
            anesthesia_text, weight_text, anesthesia_tone = anesthesia_display(i, now)
            tone_class = "" if anesthesia_tone == "normal" else f" {anesthesia_tone}"
            st.markdown(
                f'<div class="lab-anesthesia-copy '
                f'anesthesia-tone-{html.escape(str(anesthesia_tone))}">'
                f'<div class="lab-mini-label">Anesthesia</div>'
                f'<div class="lab-anesthesia-status-row">'
                f'<div class="lab-primary-text{tone_class}">'
                f'{html.escape(str(anesthesia_text))}</div>'
                f'<div class="lab-anesthesia-weight-inline">'
                f'{html.escape(str(weight_text))}</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            render_anesthesia_controls(i)

        # cols[5] is deliberately empty to separate anesthesia from Actions.
        with cols[6]:
            actions = st.columns(RUNNING_ACTION_COLUMNS, gap="small")
            with actions[0]:
                render_primary_action(i, now)
            with actions[1]:
                render_overflow_control(i, now, reorder_peers)


@st.fragment(run_every=REFRESH_INTERVAL)
def show_timers():
    if st.session_state.get("_pending_dialog"):
        st.session_state["_needs_full_rerun"] = False
        _rerun_entire_app()
    if st.session_state.pop("_needs_full_rerun", False):
        _rerun_entire_app()

    wall_now = time.time()
    ordered = ordered_subject_indices()
    render_attention_snapshot(collect_attention_items(wall_now, ordered))

    active = []
    completed = []
    for i in ordered:
        target = completed if mouse_is_complete(i, effective_now(i, wall_now)) else active
        target.append(i)

    for i in active:
        render_mouse_row(i, wall_now, False, active)

    with st.container(key="add_mouse_card"):
        st.button(
            "⊕  + Add mouse",
            key="add_mouse_subject",
            use_container_width=True,
            on_click=request_add_mouse_dialog,
        )

    if completed:
        st.markdown(
            '<div class="lab-completed-section-title">Completed / Ended</div>',
            unsafe_allow_html=True,
        )
        for i in completed:
            render_mouse_row(i, wall_now, True, completed)

# ============================================================
# APP ORCHESTRATION / ENTRY POINT
# ============================================================

def render_active_experiment_header():
    """Render the fixed experiment toolbar without mutating timer state."""
    header = st.columns(HEADER_COLUMNS, vertical_alignment="center")

    with header[0]:
        if st.button(
            "← Experiments",
            key="back_to_experiments",
            use_container_width=True,
        ):
            return_to_experiment_home()

    with header[1]:
        exp_name = html.escape(
            str(st.session_state.get("_active_experiment_name", "Experiment"))
        )
        st.markdown(
            f'<div class="lab-header-title">{exp_name}</div>'
            f'<div class="lab-header-subtitle">'
            f'{mouse_count()} mice · persistent session</div>',
            unsafe_allow_html=True,
        )

    with header[2]:
        st.button(
            "⛶ Full screen",
            key="fullscreen_view",
            use_container_width=True,
        )

    with header[3]:
        available = global_undo_available()
        target = global_undo_label()
        help_text = f"Undo: {target}" if available else "No action available to undo"
        if st.button(
            "↶ Undo",
            key=f"global_undo_{global_undo_token()}",
            use_container_width=True,
            disabled=not available,
            help=help_text,
        ):
            global_undo_last_action()
            st.rerun()

    with header[4]:
        st.download_button(
            "⇩ Export timesheets",
            data=build_all_timesheets_text(),
            file_name=timesheet_export_filename(),
            mime="text/plain",
            key="export_timesheets",
            use_container_width=True,
        )

    with header[5]:
        if st.button(
            "■ End all subjects",
            key="end_all_subjects",
            use_container_width=True,
        ):
            end_all_subjects_dialog()

    with header[6]:
        if st.button(
            "⚙ Settings",
            key="open_settings",
            use_container_width=True,
        ):
            settings_dialog()


def render_active_experiment():
    """Render the active experiment shell around the 1-second timer fragment."""
    render_run_active_marker()
    retry_unsaved_subjects()

    if st.session_state.get("_pending_weight_warning"):
        weight_warning_dialog()
    else:
        render_pending_dialog()

    if st.session_state.get("_show_storage_exit_dialog"):
        storage_exit_dialog()

    render_pending_auto_download_marker()
    render_active_experiment_header()
    render_storage_failure_warning()
    st.markdown('<div class="lab-divider"></div>', unsafe_allow_html=True)
    show_timers()


def main():
    """Initialize shared resources, then render the home or active-run surface."""
    install_app_styles()
    initialize_database()
    initialize_state()

    # Browser helpers are installed on both the home/configuration screen and
    # the active experiment so preflight can inspect capabilities before launch.
    install_browser_helpers()

    if not st.session_state.get("_active_experiment_id"):
        render_experiment_home()
        st.stop()

    render_active_experiment()


if __name__ == "__main__":
    main()
