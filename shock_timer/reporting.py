"""Audit events and text-timesheet reporting."""

import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from . import state
from .settings import ANESTHESIA_DOSE_VOLUME_ML_PER_G, APP_TIMEZONE


def log_event(i, event_name, details="", when_epoch=None):
    epoch = float(when_epoch if when_epoch is not None else time.time())
    key = f"event_log_{i}"
    log = list(st.session_state.get(key, []))
    entry = {
        "_id": uuid.uuid4().hex,
        "Event": str(event_name),
        "Absolute time": state.wall_datetime(epoch).strftime("%Y-%m-%d %H:%M:%S"),
        "Details": str(details or ""),
        "_epoch": epoch,
    }
    log.append(entry)
    st.session_state[key] = log
    return entry


def event_epoch(entry):
    try:
        if entry.get("_epoch") is not None:
            return float(entry["_epoch"])
    except (AttributeError, TypeError, ValueError):
        pass
    absolute = str(entry.get("Absolute time", "")).strip()
    if not absolute:
        return None
    try:
        return datetime.strptime(absolute, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo(APP_TIMEZONE)
        ).timestamp()
    except ValueError:
        return None


def format_relative(seconds):
    sign = "-" if seconds < 0 else "+"
    return sign + state.format_total_elapsed(abs(seconds))


def relative_time_map(i, log):
    base = st.session_state.get(f"experiment_start_{i}")
    epochs = [event_epoch(event) for event in log if event_epoch(event) is not None]
    if base is None and epochs:
        base = min(epochs)
    result = {}
    for order, event in enumerate(log):
        epoch = event_epoch(event)
        value = "—" if epoch is None or base is None else format_relative(epoch - float(base))
        key = event.get("_id") or f"__order_{order}"
        result[key] = value
    return result


def is_backtime_editable_event(entry):
    return entry.get("Event") in {
        "Anesthesia started",
        "Anesthesia redosed",
        "Board acclimation started",
        "Shock started",
        "Resuscitation started",
    }


def anesthesia_event_weight(i, event):
    """Use the historical event weight, then compatible fallbacks."""
    try:
        value = event.get("_weight_g")
        if value is not None:
            return float(value)
    except (AttributeError, TypeError, ValueError):
        pass
    details = str(event.get("Details", ""))
    if details.startswith("Weight ") and details.endswith(" g"):
        try:
            return float(details[len("Weight ") : -2].strip())
        except (TypeError, ValueError):
            pass
    return state.mouse_weight(i)


def anesthesia_summary_rows(i):
    log = list(st.session_state.get(f"event_log_{i}", []))
    relative = relative_time_map(i, log)
    rows = []
    dose_number = 0
    for order, event in enumerate(log):
        event_name = str(event.get("Event", ""))
        if event_name not in ("Anesthesia started", "Anesthesia redosed"):
            continue
        dose_number += 1
        weight = anesthesia_event_weight(i, event)
        dose_volume_ml = None if weight is None else float(weight) * ANESTHESIA_DOSE_VOLUME_ML_PER_G
        rows.append(
            {
                "dose": dose_number,
                "type": "Initial" if event_name == "Anesthesia started" else "Redose",
                "relative": relative.get(event.get("_id"), relative.get(f"__order_{order}", "—")),
                "absolute": str(event.get("Absolute time", "")),
                "weight": "—" if weight is None else f"{weight:.1f} g",
                "volume_ml": dose_volume_ml,
                "volume": "—" if dose_volume_ml is None else f"{dose_volume_ml:.3f} mL",
            }
        )
    return rows


def anesthesia_usage_totals(indices):
    totals = {
        "Initial": {"doses": 0, "volume_ml": 0.0, "missing": 0},
        "Redose": {"doses": 0, "volume_ml": 0.0, "missing": 0},
    }
    for i in indices:
        for row in anesthesia_summary_rows(i):
            statistics = totals[row["type"]]
            statistics["doses"] += 1
            if row["volume_ml"] is None:
                statistics["missing"] += 1
            else:
                statistics["volume_ml"] += float(row["volume_ml"])
    return totals


def build_all_timesheets_text():
    """Build the complete, consistently ordered text export."""
    indices = state.ordered_subject_indices()
    lines = [
        "Shock Timer - Aggregated Timesheets",
        f"Experiment: {st.session_state.get('_active_experiment_name', '')}",
        f"Timezone: {APP_TIMEZONE}",
        f"Exported: {state.wall_datetime().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "BLOOD PRESSURE SUMMARY",
        "-" * 96,
        "Subject | Weight | Starting MAP | Ending MAP",
    ]
    for i in indices:
        start, end = state.starting_map(i), state.ending_map(i)
        lines.append(
            f"{state.subject_name(i)} | {state.weight_label(i)} | "
            f"{'—' if start is None else f'{start:g} mmHg'} | "
            f"{'—' if end is None else f'{end:g} mmHg'}"
        )

    lines += [
        "",
        "ANESTHESIA SUMMARY",
        "-" * 96,
        "Subject | Dose | Type | Relative time | Absolute time | Weight | Dose volume",
    ]
    any_anesthesia = False
    for i in indices:
        for row in anesthesia_summary_rows(i):
            any_anesthesia = True
            lines.append(
                f"{state.subject_name(i)} | {row['dose']} | {row['type']} | "
                f"{row['relative']} | {row['absolute']} | {row['weight']} | {row['volume']}"
            )
    if not any_anesthesia:
        lines.append("No anesthesia administrations recorded.")
    else:
        usage = anesthesia_usage_totals(indices)
        total_doses = usage["Initial"]["doses"] + usage["Redose"]["doses"]
        total_volume = usage["Initial"]["volume_ml"] + usage["Redose"]["volume_ml"]
        lines += [
            "",
            "ANESTHESIA USE TOTALS (0.01 mL/g per administration)",
            f"Initial doses | {usage['Initial']['doses']} doses | {usage['Initial']['volume_ml']:.3f} mL total",
            f"Redoses | {usage['Redose']['doses']} doses | {usage['Redose']['volume_ml']:.3f} mL total",
            f"All administrations | {total_doses} doses | {total_volume:.3f} mL total",
        ]
        missing = usage["Initial"]["missing"] + usage["Redose"]["missing"]
        if missing:
            lines.append(
                f"{missing} dose(s) missing a recorded weight; its volume is excluded from totals."
            )

    lines += ["", "DETAILED SUBJECT TIMESHEETS", ""]
    for i in indices:
        lines += [
            "=" * 96,
            f"{state.subject_name(i)} (Mouse {i}; {state.weight_label(i)})",
            "=" * 96,
        ]
        map_summary = state.map_summary(i)
        if map_summary:
            lines.append(map_summary)
        volume_summary = state.volume_summary(i)
        if volume_summary:
            lines.append(volume_summary)

        log = list(st.session_state.get(f"event_log_{i}", []))
        relative = relative_time_map(i, log)
        if not log:
            lines.append("No events recorded.")
        else:
            lines += ["Relative time | Absolute time        | Event | Details", "-" * 96]
        for order, event in enumerate(log):
            relative_value = relative.get(
                event.get("_id"), relative.get(f"__order_{order}", "—")
            )
            line = f"{relative_value:>13} | {event.get('Absolute time', '')} | {event.get('Event', '')}"
            details = str(event.get("Details", "")).strip()
            lines.append(line + (f" | {details}" if details else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
