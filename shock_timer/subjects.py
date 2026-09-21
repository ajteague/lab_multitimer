"""Subject profile validation, creation, and display ordering."""

import streamlit as st

from . import persistence, state, workflow
from .settings import (
    DEFAULT_ANESTHESIA_DELAY,
    DEFAULT_INITIAL_ANESTHESIA,
    DEFAULT_NOTIFICATION_SOUND,
    DEFAULT_NOTIFICATION_SOUND_ENABLED,
    DEFAULT_SUBSEQUENT_ANESTHESIA,
)


def weight_requires_confirmation(weight):
    try:
        value = float(weight)
    except (TypeError, ValueError):
        return False
    return not (20.0 < value < 40.0)


def validate_mouse_name_weight(name, weight, default_name="Mouse"):
    name = str(name or "").strip()
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return None, None, "Enter a valid mouse weight."
    if weight <= 0:
        return None, None, "Mouse weight must be greater than 0 g."
    return name or default_name, round(weight, 1), None


def queue_weight_warning(context, entries, **extra):
    st.session_state["_pending_weight_warning"] = {"context": context, "entries": entries, **extra}


def save_subject_profile(i, name, weight):
    name = (name or "").strip()
    if not name:
        return False, "Subject name cannot be blank."
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return False, "Enter a valid weight."
    if weight <= 0:
        return False, "Weight must be greater than 0 g."
    st.session_state[f"subject_name_{i}"] = name
    st.session_state[f"mouse_weight_g_{i}"] = round(weight, 1)
    persistence.persist_subject(i)
    return True, None


def create_mouse_subject(name, weight):
    if not st.session_state.get("_active_experiment_id"):
        return False, "No active experiment."
    name = (name or "").strip()
    try:
        weight = float(weight)
    except (TypeError, ValueError):
        return False, "Enter a valid mouse weight."
    if not name or weight <= 0:
        return False, "Enter a mouse name and weight greater than 0 g."

    new_i = state.mouse_count() + 1
    st.session_state["_mouse_count"] = new_i
    state.initialize_mouse_state(new_i)
    st.session_state[f"subject_name_{new_i}"] = name
    st.session_state[f"mouse_weight_g_{new_i}"] = round(weight, 1)
    if new_i > 1:
        source = state.ordered_subject_indices()[0]
        for field, default in (
            ("anesthesia_initial_duration", DEFAULT_INITIAL_ANESTHESIA),
            ("anesthesia_duration", DEFAULT_SUBSEQUENT_ANESTHESIA),
            ("anesthesia_delay_duration", DEFAULT_ANESTHESIA_DELAY),
            ("notification_sound_enabled", DEFAULT_NOTIFICATION_SOUND_ENABLED),
            ("notification_sound", DEFAULT_NOTIFICATION_SOUND),
        ):
            st.session_state[f"{field}_{new_i}"] = st.session_state.get(f"{field}_{source}", default)
    existing = [float(st.session_state.get(f"display_order_{j}", j)) for j in range(1, new_i)]
    st.session_state[f"display_order_{new_i}"] = max(existing) + 1 if existing else 1
    ok, error = persistence.add_subject_to_experiment(new_i)
    if not ok:
        return False, error
    st.session_state["_needs_full_rerun"] = True
    return True, None


def mouse_is_complete(i, now):
    """A subject is complete only after an explicit end action."""
    return state.is_ended(i)


def _reorder_group(i, now):
    return "completed" if mouse_is_complete(i, state.effective_now(i, now)) else "active"


def reorder_group(i, now):
    """Return the display group used by the reorder controls."""
    return _reorder_group(i, now)


def move_subject(i, direction):
    import time

    now = time.time()
    group = _reorder_group(i, now)
    peers = [
        subject for subject in state.ordered_subject_indices()
        if _reorder_group(subject, now) == group
    ]
    if i not in peers:
        return False
    target = peers.index(i) + int(direction)
    if target < 0 or target >= len(peers):
        return False
    other = peers[target]
    workflow.record_global_undo(f"Reorder subjects — {state.subject_name(i)}", [i, other])
    current_order = float(st.session_state.get(f"display_order_{i}", i))
    other_order = float(st.session_state.get(f"display_order_{other}", other))
    st.session_state[f"display_order_{i}"] = other_order
    st.session_state[f"display_order_{other}"] = current_order
    persistence.persist_subjects([i, other])
    st.session_state["_needs_full_rerun"] = True
    return True
