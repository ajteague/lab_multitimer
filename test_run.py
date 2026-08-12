import base64
import html
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

# ============================================================
# APP SETTINGS
# ============================================================

# CHANGE ONLY THIS LINE:
# Use "seconds" for quick debugging and "minutes" for production.
TIME_UNIT = "seconds"  # "seconds" or "minutes"

# The display is rounded to the nearest second, so refreshing faster than
# once per second adds load without adding useful visual information.
REFRESH_INTERVAL = 1.0

# Default durations, expressed in whatever TIME_UNIT is selected above.
DEFAULT_ANESTHESIA = 30
DEFAULT_ANESTHESIA_DELAY = 5
DEFAULT_BOARD = 10
DEFAULT_SHOCK = 60
DEFAULT_RESUSCITATION = 20

# Code-only warning window. Change this value to control how long before
# a deadline the timer changes to orange. Set to 0 to disable warnings.
WARNING_UNITS = 1

# Clock timezone used for the absolute shock-start time shown after End.
APP_TIMEZONE = "America/New_York"

# Bump this value whenever you intentionally change the structure/defaults
# and want existing browser Session State cleared automatically.
STATE_VERSION = "lab_multitimer_v10"

# ============================================================
# DERIVED SETTINGS
# ============================================================

UNIT_SECONDS = 1.0 if TIME_UNIT == "seconds" else 60.0
UNIT_LABEL = "sec" if TIME_UNIT == "seconds" else "min"
LIVE_TIME_LABEL = "sec" if TIME_UNIT == "seconds" else "min:sec"

st.set_page_config(
    page_title="Lab Multi-Timer",
    layout="wide",
)

st.title("Lab Multi-Timer")


# ============================================================
# STATE MANAGEMENT
# ============================================================


def mouse_defaults(i):
    """Return all default Session State values for one mouse."""
    return {
        f"experiment_start_{i}": None,
        f"anesthesia_start_{i}": None,
        f"anesthesia_delay_offset_{i}": 0.0,
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
        f"board_duration_{i}": DEFAULT_BOARD,
        f"shock_duration_{i}": DEFAULT_SHOCK,
        f"resus_duration_{i}": DEFAULT_RESUSCITATION,
    }


def initialize_state():
    """
    Initialize all timer state.

    STATE_VERSION deliberately clears stale values from older versions
    of the app once, which makes changed defaults behave predictably
    during development.
    """
    if st.session_state.get("_state_version") != STATE_VERSION:
        st.session_state.clear()
        st.session_state["_state_version"] = STATE_VERSION

    for i in range(1, 9):
        for key, value in mouse_defaults(i).items():
            if key not in st.session_state:
                st.session_state[key] = value

    # Sticky attention state is deliberately separate from the live timer
    # calculation. Once an alert appears, it remains present until the
    # corresponding action resolves it (or the entire mouse is Ended/Reset).
    if "_sticky_alerts" not in st.session_state:
        st.session_state["_sticky_alerts"] = {}


def alert_key(i, event_name):
    return f"{i}:{event_name}"


def clear_alert(i, event_name):
    st.session_state.get("_sticky_alerts", {}).pop(
        alert_key(i, event_name), None
    )


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
    """Start the global experiment clock on the first event click."""
    key = f"experiment_start_{i}"
    if st.session_state[key] is None:
        st.session_state[key] = timestamp


def start_or_redose_anesthesia(i):
    if not mouse_is_running(i):
        return

    timestamp = time.monotonic()
    ensure_experiment_started(i, timestamp)
    st.session_state[f"anesthesia_start_{i}"] = timestamp

    # A real dose starts a fresh reminder interval and clears any prior delay.
    st.session_state[f"anesthesia_delay_offset_{i}"] = 0.0
    clear_alert(i, "Anesthesia redose")


def delay_anesthesia_reminder(i):
    """
    Push the anesthesia reminder later without recording another dose.

    If the reminder is already overdue, the requested delay starts from the
    moment the Delay button is clicked rather than from the old overdue time.
    """
    if not mouse_is_running(i):
        return

    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    if anesthesia_start is None:
        return

    now = time.monotonic()
    interval_seconds = duration_to_seconds(
        st.session_state[f"anesthesia_duration_{i}"]
    )
    delay_seconds = duration_to_seconds(
        st.session_state[f"anesthesia_delay_duration_{i}"]
    )
    current_offset = st.session_state[f"anesthesia_delay_offset_{i}"]
    current_due = anesthesia_start + interval_seconds + current_offset

    # If not yet due, extend the current deadline. If overdue, snooze from now.
    if current_due >= now:
        st.session_state[f"anesthesia_delay_offset_{i}"] = (
            current_offset + delay_seconds
        )
    else:
        overdue_seconds = now - current_due
        st.session_state[f"anesthesia_delay_offset_{i}"] = (
            current_offset + overdue_seconds + delay_seconds
        )

    clear_alert(i, "Anesthesia redose")


def start_board(i):
    # The ONLY anesthesia dependency in the procedural workflow: the initial
    # anesthesia dose must have been started before board acclimation begins.
    # After that first dose, anesthesia reminders are completely independent.
    if not mouse_is_running(i):
        return
    if st.session_state[f"anesthesia_start_{i}"] is None:
        return

    timestamp = time.monotonic()
    ensure_experiment_started(i, timestamp)

    if st.session_state[f"board_start_{i}"] is None:
        st.session_state[f"board_start_{i}"] = timestamp


def start_shock(i):
    # Procedural workflow is independent of anesthesia state/reminders.
    if not mouse_is_running(i):
        return

    timestamp = time.monotonic()
    ensure_experiment_started(i, timestamp)

    if st.session_state[f"shock_start_{i}"] is None:
        st.session_state[f"shock_start_{i}"] = timestamp
        st.session_state[f"shock_wallclock_{i}"] = datetime.now(
            ZoneInfo(APP_TIMEZONE)
        ).strftime("%H:%M")
        clear_alert(i, "Shock")


def start_resuscitation(i):
    # Procedural workflow is independent of anesthesia state/reminders.
    if not mouse_is_running(i):
        return

    timestamp = time.monotonic()
    ensure_experiment_started(i, timestamp)

    if st.session_state[f"resus_start_{i}"] is None:
        st.session_state[f"resus_start_{i}"] = timestamp
        clear_alert(i, "Resuscitation")


def toggle_pause(i):
    """Pause or resume every clock/deadline belonging to one mouse."""
    if is_ended(i) or st.session_state[f"experiment_start_{i}"] is None:
        return

    if not is_paused(i):
        st.session_state[f"paused_{i}"] = True
        st.session_state[f"pause_started_{i}"] = time.monotonic()
        return

    # Resume: shift every stored timestamp forward by the amount of time
    # spent paused. This freezes total time and all event countdowns.
    resume_time = time.monotonic()
    pause_started = st.session_state[f"pause_started_{i}"]
    pause_duration = max(0.0, resume_time - pause_started)

    timestamp_keys = [
        f"experiment_start_{i}",
        f"anesthesia_start_{i}",
        f"board_start_{i}",
        f"shock_start_{i}",
        f"resus_start_{i}",
    ]

    for key in timestamp_keys:
        if st.session_state[key] is not None:
            st.session_state[key] += pause_duration

    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None


def end_mouse(i):
    """Freeze one mouse and clear every active alert for that channel."""
    if is_ended(i) or st.session_state[f"experiment_start_{i}"] is None:
        return

    # If already paused, end at the moment the pause began so paused time
    # never gets added back into the experiment duration.
    if is_paused(i):
        end_time = st.session_state[f"pause_started_{i}"]
    else:
        end_time = time.monotonic()

    st.session_state[f"ended_{i}"] = True
    st.session_state[f"end_time_{i}"] = end_time
    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None
    clear_mouse_alerts(i)


def reset_mouse(i):
    """
    Reset one mouse while preserving the currently entered durations
    and anesthesia delay amount.
    """
    st.session_state[f"experiment_start_{i}"] = None
    st.session_state[f"anesthesia_start_{i}"] = None
    st.session_state[f"anesthesia_delay_offset_{i}"] = 0.0
    st.session_state[f"board_start_{i}"] = None
    st.session_state[f"shock_start_{i}"] = None
    st.session_state[f"shock_wallclock_{i}"] = None
    st.session_state[f"resus_start_{i}"] = None
    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None
    st.session_state[f"ended_{i}"] = False
    st.session_state[f"end_time_{i}"] = None
    clear_mouse_alerts(i)


initialize_state()

if TIME_UNIT == "minutes":
    st.caption(
        "Durations are entered in minutes. Live timers are displayed to "
        "the nearest second as min:sec."
    )
else:
    st.caption(
        "Durations are entered in seconds. Live timers are displayed to "
        "the nearest second."
    )


# ============================================================
# TIME / DISPLAY HELPERS
# ============================================================


def duration_to_seconds(duration_units):
    return float(duration_units) * UNIT_SECONDS


def warning_seconds():
    return duration_to_seconds(WARNING_UNITS)


def effective_now(i, wall_now):
    """Return the frozen or live clock value that should drive one mouse."""
    if is_ended(i):
        return st.session_state[f"end_time_{i}"]

    if is_paused(i):
        return st.session_state[f"pause_started_{i}"]

    return wall_now


def elapsed_from(start_time, now):
    if start_time is None:
        return 0.0
    return max(0.0, now - start_time)


def rounded_seconds(seconds):
    """Round a live value to the nearest whole second for display."""
    return int(round(seconds))


def format_live_value(seconds):
    """
    Format a displayed timer to the nearest second.

    Displayed timer values are NEVER negative. Countdown values are passed
    here only while they are positive; overdue timers pass elapsed-overdue
    seconds instead and therefore count upward from zero.
    """
    whole_seconds = max(0, rounded_seconds(seconds))

    if TIME_UNIT == "seconds":
        return f"{whole_seconds}"

    total_minutes, secs = divmod(whole_seconds, 60)
    return f"{total_minutes}:{secs:02d}"


def format_live_with_unit(seconds):
    return f"{format_live_value(seconds)} {LIVE_TIME_LABEL}"


def remaining_from_start(start_time, duration_units, now):
    if start_time is None:
        return None
    due = start_time + duration_to_seconds(duration_units)
    return due - now


def anesthesia_due_time(i):
    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    if anesthesia_start is None:
        return None

    return (
        anesthesia_start
        + duration_to_seconds(st.session_state[f"anesthesia_duration_{i}"])
        + st.session_state[f"anesthesia_delay_offset_{i}"]
    )


def anesthesia_remaining(i, now):
    due = anesthesia_due_time(i)
    if due is None:
        return None
    return due - now


def color_for_remaining(remaining):
    """Return normal, orange, or red based on a deadline's remaining time."""
    if remaining is None:
        return "normal"

    if remaining <= 0:
        return "red"

    current_warning_seconds = warning_seconds()
    if current_warning_seconds > 0 and remaining <= current_warning_seconds:
        return "orange"

    return "normal"


def status_box(label, text, color="normal"):
    """
    Render one event status line in a fixed-height box.

    The fixed height is intentional: changing from "Not started" to a longer
    running/overdue message must not make the whole mouse card jump vertically.
    """
    if color == "red":
        background = "rgba(255, 75, 75, 0.16)"
        border = "#ff4b4b"
    elif color == "orange":
        background = "rgba(245, 158, 11, 0.16)"
        border = "#f59e0b"
    else:
        background = "rgba(128, 128, 128, 0.08)"
        border = "rgba(128, 128, 128, 0.28)"

    st.html(
        f"""
        <div style="
            background:{background};
            border-left:4px solid {border};
            border-radius:5px;
            padding:6px 8px;
            margin-top:4px;
            margin-bottom:5px;
            height:72px;
            min-height:72px;
            max-height:72px;
            box-sizing:border-box;
            overflow:hidden;
        ">
            <div style="
                font-weight:600;
                line-height:1.15;
                margin-bottom:3px;
            ">{html.escape(label)}</div>
            <div style="
                font-size:0.84rem;
                line-height:1.18;
                min-height:2.36em;
                max-height:2.36em;
                overflow:hidden;
                display:-webkit-box;
                -webkit-line-clamp:2;
                -webkit-box-orient:vertical;
            ">{html.escape(text)}</div>
        </div>
        """
    )


def render_next_event(next_event, remaining, paused=False):
    """Render the large countdown/count-up at the top of a mouse card."""
    overdue = remaining <= 0

    # Once overdue, show elapsed time PAST the deadline as a positive
    # count-up value instead of a negative countdown.
    display_seconds = (-remaining) if overdue else remaining
    value = format_live_value(display_seconds)

    if paused and overdue:
        color = "#ff4b4b"
        footer = f"{LIVE_TIME_LABEL} • OVERDUE • PAUSED"
    elif paused:
        color = "#6b7280"
        footer = f"{LIVE_TIME_LABEL} • PAUSED"
    elif overdue:
        color = "#ff4b4b"
        footer = f"{LIVE_TIME_LABEL} • OVERDUE"
    elif warning_seconds() > 0 and remaining <= warning_seconds():
        color = "#f59e0b"
        footer = LIVE_TIME_LABEL
    else:
        color = "inherit"
        footer = LIVE_TIME_LABEL

    st.html(
        f"""
        <div style="
            text-align:center;
            padding:2px 0 7px 0;
            height:106px;
            min-height:106px;
            max-height:106px;
            box-sizing:border-box;
            overflow:hidden;
        ">
            <div style="
                font-size:0.78rem;
                opacity:0.72;
                margin-bottom:2px;
            ">
                NEXT: {html.escape(next_event.upper())}
            </div>

            <div style="
                font-size:3rem;
                font-weight:700;
                color:{color};
                line-height:1;
            ">
                {html.escape(value)}
            </div>

            <div style="
                font-size:0.75rem;
                opacity:0.68;
                margin-top:3px;
            ">
                {html.escape(footer)}
            </div>
        </div>
        """
    )


def render_ready(paused=False):
    label = "PAUSED" if paused else "READY"
    st.html(
        f"""
        <div style="
            text-align:center;
            padding:8px 0 12px 0;
            height:106px;
            min-height:106px;
            max-height:106px;
            box-sizing:border-box;
            overflow:hidden;
        ">
            <div style="
                font-size:0.78rem;
                opacity:0.72;
            ">
                NEXT EVENT
            </div>

            <div style="
                font-size:2.4rem;
                font-weight:700;
                line-height:1.2;
                margin-top:9px;
            ">
                {label}
            </div>
        </div>
        """
    )


def render_ended(shock_wallclock=None, shock_elapsed=None):
    """
    Render a fixed-height ended summary.

    If shock occurred, preserve both the absolute clock time of shock and the
    frozen elapsed time since shock. This occupies the same vertical space as
    the live next-event display so clicking End does not resize the card.
    """
    if shock_wallclock and shock_elapsed is not None:
        detail = (
            f"Shock started: <strong>{html.escape(shock_wallclock)}</strong>"
            f"<br>Time since shock: "
            f"<strong>{html.escape(format_live_with_unit(shock_elapsed))}</strong>"
        )
    elif shock_wallclock:
        detail = f"Shock started: <strong>{html.escape(shock_wallclock)}</strong>"
    else:
        detail = "&nbsp;<br>&nbsp;"

    st.html(
        f"""
        <div style="
            text-align:center;
            padding:4px 0 6px 0;
            height:106px;
            min-height:106px;
            max-height:106px;
            box-sizing:border-box;
            overflow:hidden;
        ">
            <div style="
                font-size:0.78rem;
                opacity:0.72;
            ">
                EXPERIMENT
            </div>

            <div style="
                font-size:2.0rem;
                font-weight:700;
                line-height:1.05;
                opacity:0.70;
                margin-top:2px;
            ">
                ENDED
            </div>

            <div style="
                font-size:0.82rem;
                line-height:1.25;
                margin-top:4px;
                opacity:0.82;
            ">
                {detail}
            </div>
        </div>
        """
    )


def render_total_time(experiment_elapsed, paused=False, ended=False):
    suffix = ""
    if ended:
        suffix = " • ended"
    elif paused:
        suffix = " • paused"

    st.html(
        f"""
        <div style="
            text-align:center;
            font-size:0.95rem;
            margin-bottom:5px;
            height:24px;
            min-height:24px;
            max-height:24px;
            box-sizing:border-box;
            overflow:hidden;
        ">
            Total time:
            <strong>{html.escape(format_live_with_unit(experiment_elapsed))}</strong>
            <span style="opacity:0.68;">{html.escape(suffix)}</span>
        </div>
        """
    )


def get_upcoming_events(i, now):
    """Return all active deadlines for one mouse."""
    if is_ended(i):
        return []

    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
    board_start = st.session_state[f"board_start_{i}"]
    shock_start = st.session_state[f"shock_start_{i}"]
    resus_start = st.session_state[f"resus_start_{i}"]

    upcoming = []

    if anesthesia_start is not None:
        upcoming.append(("Anesthesia redose", anesthesia_remaining(i, now)))

    if board_start is not None and shock_start is None:
        upcoming.append(
            (
                "Shock",
                remaining_from_start(
                    board_start,
                    st.session_state[f"board_duration_{i}"],
                    now,
                ),
            )
        )

    if shock_start is not None and resus_start is None:
        upcoming.append(
            (
                "Resuscitation",
                remaining_from_start(
                    shock_start,
                    st.session_state[f"shock_duration_{i}"],
                    now,
                ),
            )
        )

    # Once resuscitation starts, its completion remains an active deadline
    # until the user explicitly ends the mouse. This prevents a completed
    # timer from silently disappearing when it reaches zero.
    if resus_start is not None:
        upcoming.append(
            (
                "Resuscitation complete",
                remaining_from_start(
                    resus_start,
                    st.session_state[f"resus_duration_{i}"],
                    now,
                ),
            )
        )

    return upcoming


def action_targets_for_alert(i, event_name, remaining):
    """
    Return action targets ONLY when the resolving action is actually available.

    Procedural warning colors can appear before a stage is complete, but that
    does not visually highlight a disabled button. Anesthesia is different:
    Redose and Delay are both valid, enabled actions throughout its warning
    window, so both are highlighted when an anesthesia reminder needs attention.
    """
    if is_ended(i) or is_paused(i):
        return []

    if event_name == "Anesthesia redose":
        if st.session_state[f"anesthesia_start_{i}"] is None:
            return []
        return [
            {"key": f"anesthesia_primary_action_{i}", "style": "primary"},
            {"key": f"anesthesia_delay_action_{i}", "style": "delay"},
        ]

    # The procedural action is not available until the current timer reaches
    # zero. Orange early-warning status therefore NEVER highlights a disabled
    # next-stage button.
    if remaining > 0:
        return []

    if event_name == "Shock":
        if st.session_state[f"shock_start_{i}"] is None:
            return [{"key": f"shock_action_{i}", "style": "primary"}]

    if event_name == "Resuscitation":
        if st.session_state[f"resus_start_{i}"] is None:
            return [{"key": f"resus_action_{i}", "style": "primary"}]

    if event_name == "Resuscitation complete":
        return [{"key": f"end_action_{i}", "style": "primary"}]

    return []


def collect_attention_items(wall_now):
    """
    Maintain a sticky attention list and return it sorted by urgency.

    A newly orange/red deadline is latched into Session State. It remains in
    the Attention bar until its actual resolving action occurs. This prevents
    a transient fragment repaint, duration edit, pause, or DOM replacement
    from making the alert disappear for a second.
    """
    sticky = st.session_state["_sticky_alerts"]
    active_keys = set()

    for i in range(1, 9):
        if is_ended(i):
            clear_mouse_alerts(i)
            continue

        now = effective_now(i, wall_now)
        for event_name, remaining in get_upcoming_events(i, now):
            key = alert_key(i, event_name)
            active_keys.add(key)
            level = color_for_remaining(remaining)

            if level in ("orange", "red"):
                sticky[key] = {
                    "mouse": i,
                    "event": event_name,
                    "remaining": remaining,
                    "level": level,
                }
            elif key in sticky:
                # Keep the prior latched state until a resolving action occurs.
                pass

    # If an event is no longer an active deadline, its resolving action has
    # occurred (e.g. Start shock / Start resus). Remove its latched alert.
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
    """
    Encode a complete attention-state snapshot for the browser overlay.

    The visible attention bar is NOT a Streamlit element anymore. A tiny hidden
    snapshot inside the refreshing fragment is all Streamlit replaces. Browser
    JavaScript owns the visible bar and keeps the last valid state whenever the
    fragment is temporarily absent during a repaint, eliminating the old
    show/vanish/flicker behavior.
    """
    payload = []
    for item in items:
        payload.append(
            {
                "mouse": item["mouse"],
                "event": item["event"],
                "level": item["level"],
                "targets": item.get("targets", []),
            }
        )

    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def render_attention_snapshot(items):
    """Emit only a hidden, complete state snapshot for the browser overlay."""
    encoded = encode_attention_snapshot(items)
    st.html(
        f'<div data-lab-attention-snapshot="{encoded}" '
        'style="display:none !important;"></div>'
    )


def install_browser_attention_overlay():
    """
    Install one persistent browser-owned attention overlay.

    Streamlit only emits a hidden state snapshot from the one-second fragment.
    The visible overlay itself lives in the parent browser DOM and is updated
    in place, so it is never destroyed/recreated during timer refreshes.
    """
    components.html(
        r'''
        <script>
        (() => {
            const parentDoc = window.parent.document;
            const BAR_ID = "lab-attention-overlay-v10";
            const STYLE_ID = "lab-attention-overlay-style-v10";
            const PRIMARY_CLASS = "lab-next-action-primary-v10";
            const DELAY_CLASS = "lab-next-action-delay-v10";

            // Remove legacy overlays from earlier development versions if the
            // app hot-reloads in the same browser tab.
            [
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
                        border: 2px solid #0A84FF !important;
                        background: rgba(10, 132, 255, 0.12) !important;
                        box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.13) !important;
                        font-weight: 750 !important;
                        transition: none !important;
                        animation: none !important;
                    }
                    .${DELAY_CLASS} button {
                        border: 2px solid #BF5AF2 !important;
                        background: rgba(191, 90, 242, 0.11) !important;
                        box-shadow: 0 0 0 3px rgba(191, 90, 242, 0.11) !important;
                        font-weight: 750 !important;
                        transition: none !important;
                        animation: none !important;
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
                    right: "1rem",
                    bottom: "0.75rem",
                    zIndex: "999999",
                    boxSizing: "border-box",
                    height: "38px",
                    minHeight: "38px",
                    maxHeight: "38px",
                    maxWidth: "calc(100vw - 2rem)",
                    overflowX: "auto",
                    overflowY: "hidden",
                    display: "flex",
                    alignItems: "center",
                    padding: "4px 8px",
                    margin: "0",
                    background: "rgba(35,35,35,0.94)",
                    color: "white",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: "8px",
                    boxShadow: "0 1px 4px rgba(0,0,0,0.14)",
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

            const shortNames = {
                "Anesthesia redose": "Anes",
                "Shock": "Shock",
                "Resuscitation": "Resus",
                "Resuscitation complete": "End"
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

            function rebuildBar(items) {
                if (!items || items.length === 0) {
                    bar.innerHTML = '<span style="font-size:0.76rem;">Attention</span>';
                    bar.style.opacity = "0";
                    bar.style.visibility = "hidden";
                    return;
                }

                let body = '<span style="font-size:0.76rem;opacity:0.72;margin-right:4px;white-space:nowrap;">Attention</span>';

                for (const item of items) {
                    const red = item.level === "red";
                    const border = red ? "rgba(255,75,75,0.70)" : "rgba(245,158,11,0.72)";
                    const background = red ? "rgba(255,75,75,0.18)" : "rgba(245,158,11,0.16)";
                    const icon = red ? "🔴" : "🟠";
                    const shortEvent = shortNames[item.event] || item.event;

                    body += `
                        <span title="${escapeHtml(item.event)}" style="
                            display:inline-flex;
                            align-items:center;
                            border:1px solid ${border};
                            background:${background};
                            border-radius:999px;
                            padding:2px 8px;
                            margin:0 3px;
                            font-size:0.78rem;
                            font-weight:650;
                            white-space:nowrap;
                        ">${icon} Mouse ${item.mouse} · ${escapeHtml(shortEvent)}</span>
                    `;
                }

                bar.innerHTML = body;
                bar.style.visibility = "visible";
                bar.style.opacity = "1";
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

                // Remove a highlight only when that action is no longer desired.
                // Do not remove/re-add every polling cycle; that would create its
                // own visual flicker.
                parentDoc.querySelectorAll(
                    `.${PRIMARY_CLASS}, .${DELAY_CLASS}`
                ).forEach((node) => {
                    const keyClass = Array.from(node.classList).find((name) =>
                        name.startsWith("st-key-")
                    );
                    const key = keyClass ? keyClass.slice(7) : null;
                    const wantedClass = key ? desired.get(key) : null;

                    if (!wantedClass || !node.classList.contains(wantedClass)) {
                        node.classList.remove(PRIMARY_CLASS, DELAY_CLASS);
                    }
                });

                // Streamlit may replace an individual button DOM node during a
                // fragment refresh. Re-add the class only to a newly-created
                // enabled node that does not already have it.
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
                rebuildBar(items);
            }

            if (lastEncoded) {
                applyEncoded(lastEncoded);
            }

            function poll() {
                const snapshots = parentDoc.querySelectorAll("[data-lab-attention-snapshot]");
                if (!snapshots.length) {
                    reapplyHighlights();
                    return;
                }

                const snapshot = snapshots[snapshots.length - 1];
                const encoded = snapshot.getAttribute("data-lab-attention-snapshot");
                if (!encoded) {
                    reapplyHighlights();
                    return;
                }

                if (encoded !== lastEncoded) {
                    applyEncoded(encoded);
                }

                reapplyHighlights();
            }

            poll();
            window.setInterval(poll, 150);
        })();
        </script>
        ''',
        height=0,
        width=0,
    )


# ============================================================
# MAIN LIVE DASHBOARD
# ============================================================

install_browser_attention_overlay()


@st.fragment(run_every=REFRESH_INTERVAL)
def show_timers():
    wall_now = time.monotonic()

    # Only a hidden COMPLETE snapshot is replaced each second. The visible
    # attention bar is browser-owned and preserves its last valid state during
    # Streamlit's transient fragment repaint.
    attention_items = collect_attention_items(wall_now)
    render_attention_snapshot(attention_items)

    for row in range(2):
        cols = st.columns(4, gap="small")

        for col_index, col in enumerate(cols):
            i = row * 4 + col_index + 1
            now = effective_now(i, wall_now)
            paused = is_paused(i)
            ended = is_ended(i)

            with col:
                with st.container(border=True):
                    st.markdown(f"### Mouse {i}")

                    # ----------------------------------------------------
                    # Read timestamps and durations
                    # ----------------------------------------------------

                    experiment_start = st.session_state[f"experiment_start_{i}"]
                    anesthesia_start = st.session_state[f"anesthesia_start_{i}"]
                    board_start = st.session_state[f"board_start_{i}"]
                    shock_start = st.session_state[f"shock_start_{i}"]
                    shock_wallclock = st.session_state[f"shock_wallclock_{i}"]
                    resus_start = st.session_state[f"resus_start_{i}"]

                    anesthesia_duration = st.session_state[
                        f"anesthesia_duration_{i}"
                    ]
                    board_duration = st.session_state[f"board_duration_{i}"]
                    shock_duration = st.session_state[f"shock_duration_{i}"]
                    resus_duration = st.session_state[f"resus_duration_{i}"]

                    # ----------------------------------------------------
                    # Calculate elapsed times
                    # ----------------------------------------------------

                    experiment_elapsed = elapsed_from(experiment_start, now)
                    anesthesia_elapsed = elapsed_from(anesthesia_start, now)
                    board_elapsed = elapsed_from(board_start, now)
                    shock_elapsed = elapsed_from(shock_start, now)
                    resus_elapsed = elapsed_from(resus_start, now)

                    board_remaining = remaining_from_start(
                        board_start, board_duration, now
                    )
                    shock_remaining = remaining_from_start(
                        shock_start, shock_duration, now
                    )
                    resus_remaining = remaining_from_start(
                        resus_start, resus_duration, now
                    )
                    anesthesia_reminder_remaining = anesthesia_remaining(i, now)

                    # ----------------------------------------------------
                    # Stage completion / unlock logic
                    # ----------------------------------------------------

                    board_complete = (
                        board_start is not None
                        and board_remaining is not None
                        and board_remaining <= 0
                    )

                    shock_complete = (
                        shock_start is not None
                        and shock_remaining is not None
                        and shock_remaining <= 0
                    )

                    resus_complete = (
                        resus_start is not None
                        and resus_remaining is not None
                        and resus_remaining <= 0
                    )

                    # ----------------------------------------------------
                    # Next scheduled deadline
                    # ----------------------------------------------------

                    upcoming = get_upcoming_events(i, now)

                    if ended:
                        render_ended(shock_wallclock, shock_elapsed)
                    elif upcoming:
                        next_event, remaining = min(
                            upcoming,
                            key=lambda item: item[1],
                        )
                        render_next_event(
                            next_event,
                            remaining,
                            paused=paused,
                        )
                    else:
                        render_ready(paused=paused)

                    render_total_time(
                        experiment_elapsed,
                        paused=paused,
                        ended=ended,
                    )

                    # Global controls for this mouse/channel.
                    global_cols = st.columns(2, gap="small")

                    with global_cols[0]:
                        pause_label = "▶ Resume" if paused else "⏸ Pause"
                        st.button(
                            pause_label,
                            key=f"pause_button_{i}",
                            use_container_width=True,
                            disabled=(experiment_start is None or ended),
                            on_click=toggle_pause,
                            args=(i,),
                        )

                    with global_cols[1]:
                        with st.container(key=f"end_action_{i}"):
                            if resus_complete:
                                st.button(
                                    "■ End",
                                    key=f"end_button_{i}",
                                    use_container_width=True,
                                    disabled=(experiment_start is None or ended),
                                    on_click=end_mouse,
                                    args=(i,),
                                )
                            else:
                                with st.popover(
                                    "■ End",
                                    use_container_width=True,
                                    disabled=(experiment_start is None or ended),
                                ):
                                    st.warning(
                                        f"End Mouse {i}? This stops all timers "
                                        "and clears every active alert for this channel."
                                    )
                                    st.button(
                                        "Confirm End",
                                        key=f"confirm_end_button_{i}",
                                        use_container_width=True,
                                        on_click=end_mouse,
                                        args=(i,),
                                    )

                    # Reset is directly under Pause / End so all channel-wide
                    # controls stay together near the top of the card.
                    if resus_complete:
                        st.button(
                            "Reset mouse",
                            key=f"reset_mouse_button_{i}",
                            use_container_width=True,
                            on_click=reset_mouse,
                            args=(i,),
                        )
                    else:
                        with st.popover(
                            "Reset mouse",
                            use_container_width=True,
                        ):
                            st.warning(
                                f"Reset Mouse {i}? This clears all recorded "
                                "times and active alerts for this channel."
                            )
                            st.button(
                                "Confirm Reset",
                                key=f"confirm_reset_mouse_button_{i}",
                                use_container_width=True,
                                on_click=reset_mouse,
                                args=(i,),
                            )

                    st.divider()

                    # ====================================================
                    # 1. ANESTHESIA
                    # ====================================================

                    if anesthesia_start is None:
                        anesthesia_text = "Not started"
                        anesthesia_color = "normal"
                    else:
                        since_dose = format_live_with_unit(anesthesia_elapsed)
                        if anesthesia_reminder_remaining is None:
                            reminder_text = ""
                        elif anesthesia_reminder_remaining <= 0:
                            reminder_text = (
                                " • reminder overdue by "
                                + format_live_with_unit(
                                    abs(anesthesia_reminder_remaining)
                                )
                            )
                        else:
                            reminder_text = (
                                " • reminder in "
                                + format_live_with_unit(
                                    anesthesia_reminder_remaining
                                )
                            )

                        anesthesia_text = f"Since last dose: {since_dose}{reminder_text}"
                        anesthesia_color = color_for_remaining(
                            anesthesia_reminder_remaining
                        )

                    status_box(
                        "1. Anesthesia",
                        anesthesia_text,
                        anesthesia_color,
                    )

                    anesthesia_input_cols = st.columns(2, gap="small")

                    with anesthesia_input_cols[0]:
                        st.number_input(
                            f"Redose interval ({UNIT_LABEL})",
                            min_value=1,
                            step=1,
                            key=f"anesthesia_duration_{i}",
                        )

                    with anesthesia_input_cols[1]:
                        st.number_input(
                            f"Delay ({UNIT_LABEL})",
                            min_value=1,
                            step=1,
                            key=f"anesthesia_delay_duration_{i}",
                        )

                    anesthesia_button_cols = st.columns(2, gap="small")

                    with anesthesia_button_cols[0]:
                        anesthesia_button_label = (
                            "Start"
                            if anesthesia_start is None
                            else "💉 Redose"
                        )

                        with st.container(
                            key=f"anesthesia_primary_action_{i}"
                        ):
                            st.button(
                                anesthesia_button_label,
                                key=f"anesthesia_button_{i}",
                                use_container_width=True,
                                disabled=(paused or ended),
                                on_click=start_or_redose_anesthesia,
                                args=(i,),
                            )

                    with anesthesia_button_cols[1]:
                        with st.container(
                            key=f"anesthesia_delay_action_{i}"
                        ):
                            st.button(
                                "Delay reminder",
                                key=f"anesthesia_delay_button_{i}",
                                use_container_width=True,
                                disabled=(
                                    anesthesia_start is None
                                    or paused
                                    or ended
                                ),
                                on_click=delay_anesthesia_reminder,
                                args=(i,),
                            )

                    # ====================================================
                    # 2. BOARD ACCLIMATION
                    # ====================================================

                    if board_start is None:
                        board_text = "Not started"
                        board_color = "normal"
                    elif shock_start is not None:
                        board_text = (
                            "Completed at "
                            + format_live_with_unit(shock_start - board_start)
                        )
                        board_color = "normal"
                    else:
                        board_text = (
                            "On board: " + format_live_with_unit(board_elapsed)
                        )
                        board_color = color_for_remaining(board_remaining)

                    status_box(
                        "2. Board acclimation",
                        board_text,
                        board_color,
                    )

                    board_cols = st.columns(
                        [1.05, 0.95],
                        gap="small",
                        vertical_alignment="bottom",
                    )

                    with board_cols[0]:
                        st.number_input(
                            f"Duration ({UNIT_LABEL})",
                            min_value=1,
                            step=1,
                            key=f"board_duration_{i}",
                        )

                    with board_cols[1]:
                        st.button(
                            "Start board",
                            key=f"board_button_{i}",
                            use_container_width=True,
                            # Initial anesthesia must be started first. After
                            # that one prerequisite, anesthesia is fully independent
                            # and never blocks Shock or Resuscitation.
                            disabled=(
                                anesthesia_start is None
                                or board_start is not None
                                or paused
                                or ended
                            ),
                            on_click=start_board,
                            args=(i,),
                        )

                    # ====================================================
                    # 3. SHOCK
                    # ====================================================

                    if shock_start is None:
                        shock_color = "normal"
                        shock_text = (
                            "Ready"
                            if board_complete
                            else "Waiting for acclimation"
                        )
                    elif resus_start is not None:
                        shock_text = (
                            "Since shock: "
                            + format_live_with_unit(shock_elapsed)
                            + " • resus started after "
                            + format_live_with_unit(resus_start - shock_start)
                        )
                        shock_color = "normal"
                    else:
                        shock_text = (
                            "Since shock: " + format_live_with_unit(shock_elapsed)
                        )
                        shock_color = color_for_remaining(shock_remaining)

                    status_box(
                        "3. Shock",
                        shock_text,
                        shock_color,
                    )

                    shock_cols = st.columns(
                        [1.05, 0.95],
                        gap="small",
                        vertical_alignment="bottom",
                    )

                    with shock_cols[0]:
                        st.number_input(
                            f"Duration ({UNIT_LABEL})",
                            min_value=1,
                            step=1,
                            key=f"shock_duration_{i}",
                        )

                    with shock_cols[1]:
                        with st.container(key=f"shock_action_{i}"):
                            st.button(
                                "Start shock",
                                key=f"shock_button_{i}",
                                use_container_width=True,
                                # Shock depends ONLY on board timing plus global
                                # pause/end state; anesthesia cannot block it.
                                disabled=(
                                    not board_complete
                                    or shock_start is not None
                                    or paused
                                    or ended
                                ),
                                on_click=start_shock,
                                args=(i,),
                            )

                    # ====================================================
                    # 4. RESUSCITATION
                    # ====================================================

                    if resus_start is None:
                        resus_color = "normal"
                        resus_text = (
                            "Ready"
                            if shock_complete
                            else "Waiting for shock"
                        )
                    else:
                        resus_text = (
                            "Since resuscitation: "
                            + format_live_with_unit(resus_elapsed)
                        )
                        resus_color = color_for_remaining(resus_remaining)

                    status_box(
                        "4. Resuscitation",
                        resus_text,
                        resus_color,
                    )

                    resus_cols = st.columns(
                        [1.05, 0.95],
                        gap="small",
                        vertical_alignment="bottom",
                    )

                    with resus_cols[0]:
                        st.number_input(
                            f"Duration ({UNIT_LABEL})",
                            min_value=1,
                            step=1,
                            key=f"resus_duration_{i}",
                        )

                    with resus_cols[1]:
                        with st.container(key=f"resus_action_{i}"):
                            st.button(
                                "Start resus",
                                key=f"resus_button_{i}",
                                use_container_width=True,
                                # Resus depends ONLY on shock timing plus global
                                # pause/end state; anesthesia cannot block it.
                                disabled=(
                                    not shock_complete
                                    or resus_start is not None
                                    or paused
                                    or ended
                                ),
                                on_click=start_resuscitation,
                                args=(i,),
                            )

        # Modest separation between the two rows.
        st.write("")


show_timers()
