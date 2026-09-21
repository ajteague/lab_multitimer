"""Session-state schema and small timing/value helpers.

All session keys stay flat and backwards compatible because they are also the
JSON shape persisted for each subject.
"""

import random
import time
from datetime import datetime

import streamlit as st

from .settings import (
    APP_TZ,
    DEFAULT_ANESTHESIA_DELAY,
    DEFAULT_INITIAL_ANESTHESIA,
    DEFAULT_NOTIFICATION_SOUND,
    DEFAULT_NOTIFICATION_SOUND_ENABLED,
    DEFAULT_SUBSEQUENT_ANESTHESIA,
    INITIAL_MOUSE_COUNT,
    STATE_VERSION,
    TESTING_MODE,
    TEST_WEIGHT_MAX_G,
    TEST_WEIGHT_MIN_G,
    UNIT_SECONDS,
    UNIT_SHORT,
    WARNING_UNITS,
)


def duration_to_seconds(value):
    return float(value) * UNIT_SECONDS


def warning_seconds():
    return duration_to_seconds(WARNING_UNITS)


def rounded_seconds(seconds):
    return max(0, int(round(float(seconds))))


def format_timer(seconds):
    total = rounded_seconds(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_total_elapsed(seconds):
    total = rounded_seconds(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_phase_timer(seconds):
    total = rounded_seconds(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def fixed_duration_label(value):
    return f"{value}{UNIT_SHORT}"


def wall_datetime(epoch=None):
    """Return an application-local datetime for an epoch (or now)."""
    value = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(value, APP_TZ)


def elapsed_from(start, now):
    return 0.0 if start is None else max(0.0, float(now) - float(start))


def remaining_from_start(start, duration_units, now):
    if start is None:
        return None
    return float(start) + duration_to_seconds(duration_units) - float(now)


def mouse_defaults(i):
    return {
        f"experiment_start_{i}": None,
        f"anesthesia_initial_start_{i}": None,
        f"anesthesia_start_{i}": None,
        f"anesthesia_due_override_{i}": None,
        f"board_start_{i}": None,
        f"shock_start_{i}": None,
        f"shock_wallclock_{i}": None,
        f"resus_start_{i}": None,
        f"paused_{i}": False,
        f"pause_started_{i}": None,
        f"ended_{i}": False,
        f"end_time_{i}": None,
        f"anesthesia_initial_duration_{i}": DEFAULT_INITIAL_ANESTHESIA,
        f"anesthesia_duration_{i}": DEFAULT_SUBSEQUENT_ANESTHESIA,
        f"anesthesia_delay_duration_{i}": DEFAULT_ANESTHESIA_DELAY,
        f"anesthesia_dose_count_{i}": 0,
        f"notification_sound_enabled_{i}": DEFAULT_NOTIFICATION_SOUND_ENABLED,
        f"notification_sound_{i}": DEFAULT_NOTIFICATION_SOUND,
        f"event_log_{i}": [],
        f"subject_name_{i}": f"Mouse {i}",
        f"mouse_weight_g_{i}": None,
        f"starting_map_mmhg_{i}": None,
        f"ending_map_mmhg_{i}": None,
        f"shock_volume_ml_{i}": None,
        f"resuscitation_volume_ml_{i}": None,
        f"display_order_{i}": i,
        f"undo_history_{i}": [],
    }


def copy_value(value):
    if isinstance(value, list):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    if isinstance(value, dict):
        return dict(value)
    return value


def initialize_mouse_state(i):
    for key, value in mouse_defaults(i).items():
        st.session_state.setdefault(key, copy_value(value))


def initialize_state():
    st.session_state.setdefault("_state_version", STATE_VERSION)
    st.session_state.setdefault("_mouse_count", INITIAL_MOUSE_COUNT)
    st.session_state.setdefault("_sticky_alerts", {})
    st.session_state.setdefault("_pending_dialog", None)
    st.session_state.setdefault("_needs_full_rerun", False)
    st.session_state.setdefault("_unsaved_subjects", [])
    st.session_state.setdefault("_global_undo_history", [])
    for i in range(1, mouse_count() + 1):
        initialize_mouse_state(i)


def mouse_count():
    return int(st.session_state.get("_mouse_count", INITIAL_MOUSE_COUNT))


def subject_name(i):
    return str(st.session_state.get(f"subject_name_{i}", f"Mouse {i}")).strip() or f"Mouse {i}"


def mouse_weight(i):
    try:
        value = st.session_state.get(f"mouse_weight_g_{i}")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def weight_label(i):
    value = mouse_weight(i)
    return "Weight —" if value is None or value <= 0 else f"{value:.1f} g"


def random_test_weight():
    return round(random.uniform(TEST_WEIGHT_MIN_G, TEST_WEIGHT_MAX_G), 1)


def default_entry_weight():
    return random_test_weight() if TESTING_MODE else 0.0


def _optional_float(key):
    try:
        value = st.session_state.get(key)
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def starting_map(i):
    return _optional_float(f"starting_map_mmhg_{i}")


def ending_map(i):
    return _optional_float(f"ending_map_mmhg_{i}")


def shock_volume(i):
    return _optional_float(f"shock_volume_ml_{i}")


def resuscitation_volume(i):
    return _optional_float(f"resuscitation_volume_ml_{i}")


def map_summary(i):
    start, end = starting_map(i), ending_map(i)
    parts = []
    if start is not None:
        parts.append(f"Starting MAP {start:g} mmHg")
    if end is not None:
        parts.append(f"Ending MAP {end:g} mmHg")
    return " · ".join(parts)


def volume_summary(i):
    shock, resus = shock_volume(i), resuscitation_volume(i)
    parts = []
    if shock is not None:
        parts.append(f"Shock volume removed {shock:g} mL")
    if resus is not None:
        parts.append(f"Resuscitation volume given {resus:g} mL")
    return " · ".join(parts)


def ordered_subject_indices():
    return sorted(
        range(1, mouse_count() + 1),
        key=lambda i: (float(st.session_state.get(f"display_order_{i}", i)), i),
    )


def is_paused(i):
    return bool(st.session_state.get(f"paused_{i}", False))


def is_ended(i):
    return bool(st.session_state.get(f"ended_{i}", False))


def effective_now(i, wall_now):
    if is_ended(i):
        return st.session_state.get(f"end_time_{i}") or wall_now
    if is_paused(i):
        return st.session_state.get(f"pause_started_{i}") or wall_now
    return wall_now
