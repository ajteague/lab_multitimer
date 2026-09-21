"""Experiment workflow transitions, alerts, and undo operations."""

import time
import uuid

import streamlit as st

from . import persistence, reporting, state
from .settings import (
    DEFAULT_ANESTHESIA_DELAY,
    DEFAULT_INITIAL_ANESTHESIA,
    DEFAULT_NOTIFICATION_SOUND,
    DEFAULT_NOTIFICATION_SOUND_ENABLED,
    DEFAULT_SUBSEQUENT_ANESTHESIA,
    FIXED_BOARD_DURATION,
    FIXED_RESUSCITATION_DURATION,
    FIXED_SHOCK_DURATION,
    UNIT_SHORT,
    UNIT_WORD,
)


def alert_key(i, event):
    return f"{i}:{event}"


def clear_alert(i, event):
    st.session_state.get("_sticky_alerts", {}).pop(alert_key(i, event), None)


def clear_mouse_alerts(i):
    alerts = st.session_state.get("_sticky_alerts", {})
    prefix = f"{i}:"
    for key in list(alerts):
        if key.startswith(prefix):
            alerts.pop(key, None)


def mouse_is_running(i):
    return not state.is_paused(i) and not state.is_ended(i)


def ensure_experiment_started(i, timestamp):
    if st.session_state.get(f"experiment_start_{i}") is None:
        st.session_state[f"experiment_start_{i}"] = float(timestamp)


def anesthesia_dose_count(i):
    return int(st.session_state.get(f"anesthesia_dose_count_{i}", 0) or 0)


def anesthesia_preparation_start(i):
    """Return the initial anesthesia time, including legacy session recovery."""
    saved = st.session_state.get(f"anesthesia_initial_start_{i}")
    if saved is not None:
        return float(saved)
    for event in st.session_state.get(f"event_log_{i}", []):
        if event.get("Event") == "Anesthesia started":
            epoch = reporting.event_epoch(event)
            if epoch is not None:
                return epoch
    return st.session_state.get(f"anesthesia_start_{i}")


def current_anesthesia_interval(i):
    if anesthesia_dose_count(i) <= 1:
        return st.session_state.get(f"anesthesia_initial_duration_{i}", DEFAULT_INITIAL_ANESTHESIA)
    return st.session_state.get(f"anesthesia_duration_{i}", DEFAULT_SUBSEQUENT_ANESTHESIA)


def anesthesia_due_time(i):
    override = st.session_state.get(f"anesthesia_due_override_{i}")
    if override is not None:
        return float(override)
    start = st.session_state.get(f"anesthesia_start_{i}")
    if start is None:
        return None
    return float(start) + state.duration_to_seconds(current_anesthesia_interval(i))


def anesthesia_remaining(i, now):
    due = anesthesia_due_time(i)
    return None if due is None else due - float(now)


def board_is_complete(i, now):
    start = st.session_state.get(f"board_start_{i}")
    return start is not None and state.remaining_from_start(start, FIXED_BOARD_DURATION, now) <= 0


def shock_is_complete(i, now):
    start = st.session_state.get(f"shock_start_{i}")
    return start is not None and state.remaining_from_start(start, FIXED_SHOCK_DURATION, now) <= 0


def resus_is_complete(i, now):
    start = st.session_state.get(f"resus_start_{i}")
    return start is not None and state.remaining_from_start(start, FIXED_RESUSCITATION_DURATION, now) <= 0


def _record_global_undo(label, indices):
    unique = sorted({int(i) for i in indices if 1 <= int(i) <= state.mouse_count()})
    if not unique:
        return
    history = list(st.session_state.get("_global_undo_history", []))
    history.append(
        {
            "token": uuid.uuid4().hex,
            "label": str(label),
            "created_at": time.time(),
            "subjects": {str(i): persistence.subject_payload(i) for i in unique},
        }
    )
    st.session_state["_global_undo_history"] = history[-50:]
    st.session_state["_needs_full_rerun"] = True


def record_global_undo(label, indices):
    """Record an undo snapshot for a user-initiated multi-field change."""
    _record_global_undo(label, indices)


def global_undo_available():
    return bool(st.session_state.get("_global_undo_history", []))


def global_undo_label():
    history = st.session_state.get("_global_undo_history", [])
    return str(history[-1].get("label", "last action")) if history else None


def global_undo_token():
    history = st.session_state.get("_global_undo_history", [])
    if not history:
        return "empty"
    item = history[-1]
    return str(item.get("token") or item.get("created_at") or "legacy")


def _merge_audit_log_after_restore(current, restored):
    current = [dict(item) for item in (current or [])]
    restored = [dict(item) for item in (restored or [])]
    restored_by_id = {str(item.get("_id")): item for item in restored if item.get("_id")}
    merged, seen = [], set()
    for item in current:
        event_id = item.get("_id")
        if event_id and str(event_id) in restored_by_id:
            merged.append(dict(restored_by_id[str(event_id)]))
            seen.add(str(event_id))
        else:
            merged.append(dict(item))
            if event_id:
                seen.add(str(event_id))
    for item in restored:
        event_id = item.get("_id")
        if event_id and str(event_id) not in seen:
            merged.append(dict(item))
            seen.add(str(event_id))
    return merged


def _sync_experiment_completion_from_session():
    experiment_id = st.session_state.get("_active_experiment_id")
    if not experiment_id:
        return
    now = time.time()
    if all(state.is_ended(i) for i in range(1, state.mouse_count() + 1)):
        persistence.db_execute(
            "UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",
            (now, now, experiment_id),
        )
    else:
        persistence.db_execute(
            "UPDATE experiments SET completed_at=NULL,updated_at=? WHERE id=?",
            (now, experiment_id),
        )


def global_undo_last_action():
    history = list(st.session_state.get("_global_undo_history", []))
    if not history:
        return False
    item = history.pop()
    st.session_state["_global_undo_history"] = history
    restored = []
    label = str(item.get("label", "last action"))
    for key, payload in item.get("subjects", {}).items():
        try:
            i = int(key)
        except (TypeError, ValueError):
            continue
        if not 1 <= i <= state.mouse_count():
            continue
        current = list(st.session_state.get(f"event_log_{i}", []))
        previous = list(payload.get(f"event_log_{i}", [])) if isinstance(payload, dict) else []
        persistence.load_subject_payload(i, payload)
        st.session_state[f"event_log_{i}"] = _merge_audit_log_after_restore(current, previous)
        reporting.log_event(i, "Undo", f"Global undo: {label}")
        clear_mouse_alerts(i)
        restored.append(i)
    if not restored:
        return False
    persistence.persist_subjects(restored)
    _sync_experiment_completion_from_session()
    st.session_state["_needs_full_rerun"] = True
    st.toast(f"Undid: {label}")
    return True


def _push_undo(i, action, event_entry, snapshot=None):
    key = f"undo_history_{i}"
    history = list(st.session_state.get(key, []))
    item = {"action": action, "event_id": event_entry.get("_id"), "created_at": time.time()}
    if snapshot is not None:
        item["snapshot"] = snapshot
    history.append(item)
    st.session_state[key] = history[-20:]


def _undo_label(action):
    return {
        "anesthesia_redose": "Anesthesia redose",
        "start_board": "Start board",
        "start_shock": "Start shock",
        "start_resus": "Start resus",
    }.get(action, "last stage action")


def undo_label(action):
    """Readable label for a subject-level undo action."""
    return _undo_label(action)


def latest_undo_action(i):
    history = st.session_state.get(f"undo_history_{i}", [])
    return history[-1].get("action") if history else None


def undo_last_stage_action(i):
    if state.is_ended(i):
        return False
    key = f"undo_history_{i}"
    history = list(st.session_state.get(key, []))
    if not history:
        return False
    item = history[-1]
    action = item.get("action")
    if action == "start_shock" and st.session_state.get(f"resus_start_{i}") is not None:
        return False
    if action == "start_board" and st.session_state.get(f"shock_start_{i}") is not None:
        return False
    if action not in {"anesthesia_redose", "start_resus", "start_shock", "start_board"}:
        return False
    _record_global_undo(f"Undo {_undo_label(action)} — {state.subject_name(i)}", [i])
    history.pop()
    if action == "anesthesia_redose":
        snapshot = item.get("snapshot") or {}
        st.session_state[f"anesthesia_start_{i}"] = snapshot.get("anesthesia_start")
        st.session_state[f"anesthesia_due_override_{i}"] = snapshot.get("anesthesia_due_override")
        st.session_state[f"anesthesia_dose_count_{i}"] = int(snapshot.get("anesthesia_dose_count", 1))
    elif action == "start_resus":
        st.session_state[f"resus_start_{i}"] = None
    elif action == "start_shock":
        st.session_state[f"shock_start_{i}"] = None
        st.session_state[f"shock_wallclock_{i}"] = None
        st.session_state[f"starting_map_mmhg_{i}"] = None
    else:
        st.session_state[f"board_start_{i}"] = None
    st.session_state[key] = history
    clear_mouse_alerts(i)
    reporting.log_event(i, "Undo", f"Reverted {_undo_label(action)}")
    persistence.persist_subject(i)
    st.session_state["_needs_full_rerun"] = True
    return True


def start_or_redose_anesthesia(i):
    if not mouse_is_running(i):
        return
    now = time.time()
    previous = st.session_state.get(f"anesthesia_start_{i}")
    first = previous is None
    _record_global_undo(
        f"{'Start anesthesia' if first else 'Anesthesia redose'} — {state.subject_name(i)}", [i]
    )
    snapshot = None
    if not first:
        snapshot = {
            "anesthesia_start": previous,
            "anesthesia_due_override": st.session_state.get(f"anesthesia_due_override_{i}"),
            "anesthesia_dose_count": anesthesia_dose_count(i),
        }
    ensure_experiment_started(i, now)
    if first:
        st.session_state[f"anesthesia_initial_start_{i}"] = now
    st.session_state[f"anesthesia_start_{i}"] = now
    st.session_state[f"anesthesia_due_override_{i}"] = None
    st.session_state[f"anesthesia_dose_count_{i}"] = 1 if first else anesthesia_dose_count(i) + 1
    dose_weight = state.mouse_weight(i)
    weight_detail = "Weight —" if dose_weight is None else f"Weight {dose_weight:.1f} g"
    event = reporting.log_event(
        i,
        "Anesthesia started" if first else "Anesthesia redosed",
        weight_detail,
        when_epoch=now,
    )
    event["_weight_g"] = dose_weight
    if not first:
        _push_undo(i, "anesthesia_redose", event, snapshot=snapshot)
    clear_alert(i, "Anesthesia redose")
    persistence.persist_subject(i)


def delay_anesthesia_reminder(i):
    if not mouse_is_running(i) or st.session_state.get(f"anesthesia_start_{i}") is None:
        return
    now = time.time()
    delay = st.session_state[f"anesthesia_delay_duration_{i}"]
    _record_global_undo(f"Delay anesthesia reminder — {state.subject_name(i)}", [i])
    st.session_state[f"anesthesia_due_override_{i}"] = now + state.duration_to_seconds(delay)
    reporting.log_event(i, "Anesthesia reminder delayed", f"+{delay}{UNIT_SHORT} from button press", now)
    clear_alert(i, "Anesthesia redose")
    persistence.persist_subject(i)


def start_board(i):
    if (
        not mouse_is_running(i)
        or st.session_state.get(f"anesthesia_start_{i}") is None
        or st.session_state.get(f"board_start_{i}") is not None
    ):
        return
    now = time.time()
    _record_global_undo(f"Start board — {state.subject_name(i)}", [i])
    ensure_experiment_started(i, now)
    st.session_state[f"board_start_{i}"] = now
    event = reporting.log_event(i, "Board acclimation started", when_epoch=now)
    _push_undo(i, "start_board", event)
    persistence.persist_subject(i)


def _queue_dialog(i, kind, **extra):
    st.session_state["_pending_dialog"] = {"mouse": int(i), "kind": kind, **extra}
    st.session_state["_needs_full_rerun"] = True


def start_shock(i, force=False):
    if not mouse_is_running(i):
        return
    now = time.time()
    if (
        st.session_state.get(f"shock_start_{i}") is not None
        or st.session_state.get(f"board_start_{i}") is None
        or (not force and not board_is_complete(i, now))
    ):
        return
    _record_global_undo(
        f"{'Force start shock' if force else 'Start shock'} — {state.subject_name(i)}", [i]
    )
    ensure_experiment_started(i, now)
    st.session_state[f"shock_start_{i}"] = now
    st.session_state[f"shock_wallclock_{i}"] = state.wall_datetime(now).strftime("%H:%M:%S")
    event = reporting.log_event(
        i,
        "Shock started",
        "Forced advance before board acclimation completed" if force else "",
        when_epoch=now,
    )
    _push_undo(i, "start_shock", event)
    clear_alert(i, "Shock")
    persistence.persist_subject(i)
    _queue_dialog(i, "starting_map")


def start_resuscitation(i, force=False):
    if not mouse_is_running(i):
        return
    now = time.time()
    if state.starting_map(i) is None:
        _queue_dialog(i, "starting_map")
        return
    if (
        st.session_state.get(f"resus_start_{i}") is not None
        or st.session_state.get(f"shock_start_{i}") is None
        or (not force and not shock_is_complete(i, now))
    ):
        return
    _record_global_undo(
        f"{'Force start resus' if force else 'Start resus'} — {state.subject_name(i)}", [i]
    )
    st.session_state[f"resus_start_{i}"] = now
    st.session_state[f"shock_volume_ml_{i}"] = None
    event = reporting.log_event(
        i,
        "Resuscitation started",
        "Forced advance before shock completed" if force else "",
        when_epoch=now,
    )
    _push_undo(i, "start_resus", event)
    clear_alert(i, "Resuscitation")
    persistence.persist_subject(i)
    _queue_dialog(i, "shock_volume")


def toggle_pause(i):
    if state.is_ended(i):
        return
    now = time.time()
    _record_global_undo(
        f"{'Resume' if state.is_paused(i) else 'Pause'} — {state.subject_name(i)}", [i]
    )
    if not state.is_paused(i):
        st.session_state[f"paused_{i}"] = True
        st.session_state[f"pause_started_{i}"] = now
        reporting.log_event(i, "Paused", when_epoch=now)
    else:
        started = st.session_state.get(f"pause_started_{i}") or now
        delta = max(0, now - float(started))
        for field in (
            "experiment_start",
            "anesthesia_initial_start",
            "anesthesia_start",
            "board_start",
            "shock_start",
            "resus_start",
            "anesthesia_due_override",
        ):
            key = f"{field}_{i}"
            value = st.session_state.get(key)
            if value is not None:
                st.session_state[key] = float(value) + delta
        st.session_state[f"paused_{i}"] = False
        st.session_state[f"pause_started_{i}"] = None
        reporting.log_event(i, "Resumed", f"Paused {state.format_timer(delta)}", when_epoch=now)
    clear_mouse_alerts(i)
    persistence.persist_subject(i)


def end_mouse(i, forced=False, ending_map_mmhg=None, resuscitation_volume_ml=None, shock_volume_ml=None):
    if state.is_ended(i):
        return False
    if st.session_state.get(f"shock_start_{i}") is not None and state.starting_map(i) is None:
        return False
    if st.session_state.get(f"resus_start_{i}") is not None:
        final_shock_volume = state.shock_volume(i) if shock_volume_ml is None else float(shock_volume_ml)
        if final_shock_volume is None or ending_map_mmhg is None or resuscitation_volume_ml is None:
            return False
    now = time.time()
    _record_global_undo(
        f"{'Force end subject' if forced else 'End subject'} — {state.subject_name(i)}", [i]
    )
    end_at = st.session_state.get(f"pause_started_{i}") or now
    if shock_volume_ml is not None:
        st.session_state[f"shock_volume_ml_{i}"] = float(shock_volume_ml)
        reporting.log_event(i, "Shock volume", f"{float(shock_volume_ml):g} mL removed", when_epoch=now)
    if ending_map_mmhg is not None:
        st.session_state[f"ending_map_mmhg_{i}"] = float(ending_map_mmhg)
        reporting.log_event(i, "Ending MAP", f"{float(ending_map_mmhg):g} mmHg", when_epoch=now)
    if resuscitation_volume_ml is not None:
        st.session_state[f"resuscitation_volume_ml_{i}"] = float(resuscitation_volume_ml)
        reporting.log_event(
            i,
            "Resuscitation volume",
            f"{float(resuscitation_volume_ml):g} mL given",
            when_epoch=now,
        )
    st.session_state[f"ended_{i}"] = True
    st.session_state[f"end_time_{i}"] = end_at
    st.session_state[f"paused_{i}"] = False
    st.session_state[f"pause_started_{i}"] = None
    clear_mouse_alerts(i)
    reporting.log_event(
        i,
        "Experiment ended",
        "Forced advance before resuscitation completed" if forced else "",
        when_epoch=now,
    )
    persistence.persist_subject(i)
    persistence.maybe_mark_experiment_complete()
    return True


def reset_mouse(i):
    _record_global_undo(f"Reset subject — {state.subject_name(i)}", [i])
    name, weight = state.subject_name(i), state.mouse_weight(i)
    order = st.session_state.get(f"display_order_{i}", i)
    initial = st.session_state.get(f"anesthesia_initial_duration_{i}", DEFAULT_INITIAL_ANESTHESIA)
    subsequent = st.session_state.get(f"anesthesia_duration_{i}", DEFAULT_SUBSEQUENT_ANESTHESIA)
    delay = st.session_state.get(f"anesthesia_delay_duration_{i}", DEFAULT_ANESTHESIA_DELAY)
    sound = st.session_state.get(f"notification_sound_{i}", DEFAULT_NOTIFICATION_SOUND)
    sound_enabled = st.session_state.get(
        f"notification_sound_enabled_{i}", DEFAULT_NOTIFICATION_SOUND_ENABLED
    )
    for key, value in state.mouse_defaults(i).items():
        st.session_state[key] = state.copy_value(value)
    st.session_state.update(
        {
            f"subject_name_{i}": name,
            f"mouse_weight_g_{i}": weight,
            f"display_order_{i}": order,
            f"anesthesia_initial_duration_{i}": initial,
            f"anesthesia_duration_{i}": subsequent,
            f"anesthesia_delay_duration_{i}": delay,
            f"notification_sound_{i}": sound,
            f"notification_sound_enabled_{i}": sound_enabled,
        }
    )
    clear_mouse_alerts(i)
    persistence.persist_subject(i)
    _sync_experiment_completion_from_session()


def end_all_subjects_current_experiment(ending_maps=None):
    targets = [i for i in state.ordered_subject_indices() if not state.is_ended(i)]
    if not targets:
        return True
    ending_maps = {int(key): float(value) for key, value in (ending_maps or {}).items()}
    _record_global_undo("End all subjects", targets)
    now = time.time()
    for i in targets:
        if i in ending_maps:
            st.session_state[f"ending_map_mmhg_{i}"] = ending_maps[i]
            reporting.log_event(i, "Ending MAP", f"{ending_maps[i]:g} mmHg", when_epoch=now)
        st.session_state[f"ended_{i}"] = True
        st.session_state[f"end_time_{i}"] = st.session_state.get(f"pause_started_{i}") or now
        st.session_state[f"paused_{i}"] = False
        st.session_state[f"pause_started_{i}"] = None
        clear_mouse_alerts(i)
        reporting.log_event(i, "Experiment ended", "Ended with End all subjects", when_epoch=now)
    ok = persistence.persist_subjects(targets)
    if ok:
        experiment_id = st.session_state.get("_active_experiment_id")
        if experiment_id:
            persistence.db_execute(
                "UPDATE experiments SET completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",
                (now, now, experiment_id),
            )
    return ok


def backtime_start_event(i, event_id, amount):
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False, f"Enter a valid number of {UNIT_WORD}."
    if amount <= 0:
        return False, f"Back-time must be greater than 0 {UNIT_WORD}."
    key = f"event_log_{i}"
    log = list(st.session_state.get(key, []))
    index = next((n for n, event in enumerate(log) if event.get("_id") == event_id), None)
    if index is None:
        return False, "That event could not be found."
    entry = dict(log[index])
    if not reporting.is_backtime_editable_event(entry):
        return False, "That event is not a timer start and cannot be back-timed here."
    old = reporting.event_epoch(entry)
    if old is None:
        return False, "The saved event time could not be parsed."
    new = old - state.duration_to_seconds(amount)
    name = entry.get("Event")
    _record_global_undo(f"Back-time {name} — {state.subject_name(i)}", [i])
    entry["_epoch"] = new
    entry["Absolute time"] = state.wall_datetime(new).strftime("%Y-%m-%d %H:%M:%S")
    log[index] = entry
    st.session_state[key] = log
    if name == "Board acclimation started":
        st.session_state[f"board_start_{i}"] = new
    elif name == "Shock started":
        st.session_state[f"shock_start_{i}"] = new
        st.session_state[f"shock_wallclock_{i}"] = state.wall_datetime(new).strftime("%H:%M:%S")
    elif name == "Resuscitation started":
        st.session_state[f"resus_start_{i}"] = new
    elif name in ("Anesthesia started", "Anesthesia redosed"):
        anesthesia_events = [
            event
            for event in log
            if event.get("Event") in ("Anesthesia started", "Anesthesia redosed")
        ]
        if anesthesia_events and anesthesia_events[-1].get("_id") == event_id:
            st.session_state[f"anesthesia_start_{i}"] = new
        if name == "Anesthesia started":
            st.session_state[f"anesthesia_initial_start_{i}"] = new
            current = st.session_state.get(f"experiment_start_{i}")
            if current is None or new < float(current):
                st.session_state[f"experiment_start_{i}"] = new
    reporting.log_event(i, "Time correction", f"{name} moved {amount:g} {UNIT_WORD} earlier")
    persistence.persist_subject(i)
    clear_mouse_alerts(i)
    st.session_state["_needs_full_rerun"] = True
    return True, None
