"""Shock Timer

Multi-subject experiment timer with persistent experiment state, audit-safe undo,
MAP capture, anesthesia tracking, exported timesheets, and a compact Streamlit UI.

This entry module is intentionally limited to Streamlit dialogs, rendering, and
browser helpers. Application state, workflow transitions, persistence, reports,
subject services, settings, and presentation CSS live in ``shock_timer/``.

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
"""

import base64
import html
import io
import json
import math
import re
import struct
import time
import uuid
import wave

import streamlit as st
import streamlit.components.v1 as components

from shock_timer.settings import (
    APP_TIMEZONE,
    CONFIGURATION_COLUMNS,
    DEFAULT_ANESTHESIA_DELAY,
    DEFAULT_INITIAL_ANESTHESIA,
    DEFAULT_NOTIFICATION_SOUND,
    DEFAULT_NOTIFICATION_SOUND_ENABLED,
    DEFAULT_SUBSEQUENT_ANESTHESIA,
    FIXED_BOARD_DURATION,
    FIXED_RESUSCITATION_DURATION,
    FIXED_SHOCK_DURATION,
    HEADER_COLUMNS,
    INITIAL_MOUSE_COUNT,
    NOTIFICATION_SOUND_OPTIONS,
    REFRESH_INTERVAL,
    RUNNING_ACTION_COLUMNS,
    RUNNING_ROW_COLUMNS,
    UNIT_LABEL,
    UNIT_SHORT,
    UNIT_WORD,
)
from shock_timer.state import (
    default_entry_weight as _default_entry_weight,
    duration_to_seconds,
    effective_now,
    elapsed_from,
    ending_map,
    fixed_duration_label,
    format_phase_timer,
    format_timer,
    format_total_elapsed,
    initialize_state,
    is_ended,
    is_paused,
    mouse_count,
    mouse_weight,
    ordered_subject_indices,
    remaining_from_start,
    resuscitation_volume,
    shock_volume,
    starting_map,
    subject_name,
    wall_datetime,
    warning_seconds,
    weight_label,
)

st.set_page_config(
    page_title="Shock Timer",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
from shock_timer.styles import install_app_styles

install_app_styles()

# ============================================================
# CORE SERVICES
# ============================================================
# The entry point renders Streamlit views; all timing, session schema,
# persistence, audit logging, exports, and workflow mutations live in the
# package below.  Existing flat session keys remain unchanged for saved data.

from shock_timer.persistence import (
    DATABASE_KIND,
    create_experiment_record,
    delete_experiment_record,
    end_experiment_record,
    initialize_database,
    list_experiment_records,
    load_experiment_into_session,
    persist_subject,
    persist_subjects,
    rename_experiment_record,
    retry_unsaved_subjects,
)
from shock_timer.reporting import (
    anesthesia_summary_rows,
    build_all_timesheets_text,
    is_backtime_editable_event,
    log_event,
    relative_time_map,
)
from shock_timer.workflow import (
    alert_key,
    anesthesia_dose_count,
    anesthesia_preparation_start,
    anesthesia_remaining,
    backtime_start_event,
    board_is_complete,
    clear_mouse_alerts,
    delay_anesthesia_reminder,
    end_all_subjects_current_experiment,
    end_mouse,
    global_undo_available,
    global_undo_label,
    global_undo_last_action,
    global_undo_token,
    latest_undo_action,
    record_global_undo,
    reset_mouse,
    resus_is_complete,
    shock_is_complete,
    start_board,
    start_or_redose_anesthesia,
    start_resuscitation,
    start_shock,
    toggle_pause,
    undo_label,
    undo_last_stage_action,
)

initialize_database()

# ============================================================
# SUBJECT SERVICES
# ============================================================

from shock_timer.subjects import (
    create_mouse_subject,
    mouse_is_complete,
    move_subject,
    queue_weight_warning,
    reorder_group,
    save_subject_profile,
    validate_mouse_name_weight,
    weight_requires_confirmation,
)

# ============================================================
# NEW EXPERIMENT CONFIGURATION / HOME
# ============================================================

def _clear_configuration():
    for key in list(st.session_state):
        if key.startswith("_cfg_name_") or key.startswith("_cfg_weight_"): st.session_state.pop(key,None)
    for key in ("_configuration_draft","_configuration_experiment_name","_show_configuration_dialog","_configuration_error"): st.session_state.pop(key,None)

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
                try:
                    exp_id=create_experiment_record(name,configured)
                    _clear_configuration()
                    load_experiment_into_session(exp_id)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not create experiment: {exc}")


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
                if load_experiment_into_session(exp_id):
                    st.rerun()
                st.error("Experiment could not be loaded.")

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
    elif st.session_state.get("_show_configuration_dialog"):
        configure_experiment_dialog()

def return_to_experiment_home(): retry_unsaved_subjects(); st.session_state.clear(); st.rerun()

# ============================================================
# ACTIVE EXPERIMENT DIALOGS
# ============================================================

@st.dialog("Timesheet",width="large",dismissible=False)
def timesheet_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} timesheet",unsafe_allow_html=True)

    start=starting_map(i)
    end=ending_map(i)
    bp_left,bp_right=st.columns(2)
    with bp_left:
        st.caption("Starting MAP")
        st.markdown(f"**{'—' if start is None else f'{start:g} mmHg'}**")
    with bp_right:
        st.caption("Ending MAP")
        st.markdown(f"**{'—' if end is None else f'{end:g} mmHg'}**")

    anesthesia_rows=anesthesia_summary_rows(i)
    if anesthesia_rows:
        st.markdown("**Anesthesia summary**")
        ah=st.columns([.55,.85,1.05,1.65,.80],gap="small")
        for c,label in zip(ah,["Dose","Type","Relative","Absolute time","Weight"]):
            with c:
                st.markdown(f'<div class="lab-table-header">{label}</div>',unsafe_allow_html=True)
        for row_data in anesthesia_rows:
            ar=st.columns([.55,.85,1.05,1.65,.80],gap="small")
            with ar[0]: st.caption(str(row_data["dose"]))
            with ar[1]: st.caption(row_data["type"])
            with ar[2]: st.caption(row_data["relative"])
            with ar[3]: st.caption(row_data["absolute"])
            with ar[4]: st.caption(row_data["weight"])

    st.divider()
    st.caption(f"{weight_label(i)} · {APP_TIMEZONE} · Start events can be back-timed when a button was clicked late.")
    log=list(st.session_state.get(f"event_log_{i}",[]))
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
            st.divider(); st.markdown("**Back-time selected event**"); amount=st.number_input(f"{UNIT_WORD.capitalize()} earlier",min_value=.1,step=.5,value=1.0,key=f"backtime_amount_{i}"); left,right=st.columns(2)
            with left:
                if st.button("Cancel adjustment",key=f"backtime_cancel_{i}",use_container_width=True): st.session_state.pop(f"_backtime_target_{i}",None); st.rerun()
            with right:
                if st.button("Apply back-time",key=f"backtime_apply_{i}",use_container_width=True,type="primary"):
                    ok,error=backtime_start_event(i,target,amount)
                    if ok: st.session_state.pop(f"_backtime_target_{i}",None); st.rerun()
                    st.warning(error)
    if st.button("Close",key=f"timesheet_close_{i}",use_container_width=True):
        close_active_dialog()
        st.rerun()

@st.dialog("Add comment",dismissible=False)
def comment_dialog(i):
    key=f"comment_text_{i}"; st.session_state.setdefault(key,""); st.markdown(f"**{html.escape(subject_name(i))}**",unsafe_allow_html=True); st.text_area("Comment",key=key,height=130); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"comment_cancel_{i}",use_container_width=True): close_active_dialog(); st.session_state.pop(key,None); st.rerun()
    with right:
        if st.button("Accept",key=f"comment_accept_{i}",use_container_width=True,type="primary"):
            text=str(st.session_state.get(key,"")).strip()
            if not text: st.warning("Enter a comment.")
            else: log_event(i,"Comment",text); persist_subject(i); close_active_dialog(); st.session_state.pop(key,None); st.rerun()

@st.dialog("Edit subject",dismissible=False)
def edit_subject_dialog(i):
    nk,wk=f"edit_name_{i}",f"edit_weight_{i}"; st.session_state.setdefault(nk,subject_name(i)); st.session_state.setdefault(wk,float(mouse_weight(i) or 0.0)); st.text_input("Subject name",key=nk); st.number_input("Weight (g)",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"edit_cancel_{i}",use_container_width=True): close_active_dialog(); st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
    with right:
        if st.button("Save",key=f"edit_save_{i}",use_container_width=True,type="primary"):
            name,weight,error=validate_mouse_name_weight(st.session_state.get(nk),st.session_state.get(wk),f"Mouse {i}")
            if error: st.warning(error)
            elif weight_requires_confirmation(weight): close_active_dialog(); queue_weight_warning("edit_subject",[{"name":name,"weight_g":weight}],mouse=i); st.rerun()
            else:
                ok,error=save_subject_profile(i,name,weight)
                if ok: close_active_dialog(); st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
                st.warning(error)

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
            record_global_undo("Update global settings",range(1,mouse_count()+1))
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

@st.dialog("Starting blood pressure",dismissible=False)
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
            persist_subject(i); close_active_dialog(); st.session_state.pop(key,None); st.toast(f"Starting MAP saved: {value:g} mmHg"); st.rerun()

@st.dialog("Start resuscitation",dismissible=False)
def shock_volume_dialog(i):
    st.markdown(f"### {html.escape(subject_name(i))} — shock volume",unsafe_allow_html=True)
    st.caption("Resuscitation has started. Record the total volume removed by the end of the shock phase.")
    key=f"shock_volume_entry_{i}"; existing=shock_volume(i)
    st.session_state.setdefault(key,"" if existing is None else f"{existing:g}")
    st.text_input("Shock volume removed (mL)",key=key,placeholder="e.g. 0.8")
    if st.button("Save shock volume",key=f"shock_volume_save_{i}",use_container_width=True,type="primary"):
        value,error=_parse_volume_ml(st.session_state.get(key),"Shock volume")
        if error: st.warning(error)
        else:
            st.session_state[f"shock_volume_ml_{i}"]=value
            event_time=st.session_state.get(f"resus_start_{i}") or time.time()
            log_event(i,"Shock volume",f"{value:g} mL removed",when_epoch=event_time)
            persist_subject(i); close_active_dialog(); st.session_state.pop(key,None); st.toast(f"Shock volume saved: {value:g} mL"); st.rerun()

@st.dialog("Ending blood pressure",dismissible=False)
def ending_map_dialog(i,forced=False):
    st.markdown(f"### {html.escape(subject_name(i))} — ending measurements",unsafe_allow_html=True)
    st.caption("Record the final MAP and total resuscitation volume before ending this subject.")
    map_key=f"ending_map_entry_{i}"; volume_key=f"resuscitation_volume_entry_{i}"; shock_key=f"ending_shock_volume_entry_{i}"
    existing_map=ending_map(i); existing_volume=resuscitation_volume(i); existing_shock=shock_volume(i)
    st.session_state.setdefault(map_key,"" if existing_map is None else f"{existing_map:g}")
    st.session_state.setdefault(volume_key,"" if existing_volume is None else f"{existing_volume:g}")
    if existing_shock is None: st.session_state.setdefault(shock_key,"")
    st.text_input("Ending MAP (mmHg)",key=map_key,placeholder="e.g. 75")
    if existing_shock is None: st.text_input("Shock volume removed (mL)",key=shock_key,placeholder="e.g. 0.8")
    st.text_input("Resuscitation volume given (mL)",key=volume_key,placeholder="e.g. 0.8")
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"ending_map_cancel_{i}",use_container_width=True):
            close_active_dialog()
            for key in (map_key,volume_key,shock_key): st.session_state.pop(key,None)
            st.rerun()
    with right:
        if st.button("Save & end",key=f"ending_map_save_{i}",use_container_width=True,type="primary"):
            map_value,map_error=_parse_map_value(st.session_state.get(map_key))
            volume_value,volume_error=_parse_volume_ml(st.session_state.get(volume_key),"Resuscitation volume")
            shock_value,shock_error=(existing_shock,None) if existing_shock is not None else _parse_volume_ml(st.session_state.get(shock_key),"Shock volume")
            errors=[error for error in (map_error,volume_error,shock_error) if error]
            if errors: st.warning(" ".join(errors))
            else:
                close_active_dialog()
                for key in (map_key,volume_key,shock_key): st.session_state.pop(key,None)
                end_mouse(i,bool(forced),ending_map_mmhg=map_value,resuscitation_volume_ml=volume_value,shock_volume_ml=shock_value if existing_shock is None else None)
                st.rerun()

@st.dialog("Confirm end",dismissible=False)
def end_confirmation_dialog(i):
    st.markdown(f"### End {html.escape(subject_name(i))}?",unsafe_allow_html=True); st.write("This freezes the subject timers and preserves the timesheet."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"end_cancel_{i}",use_container_width=True): close_active_dialog(); st.rerun()
    with right:
        if st.button("End subject",key=f"end_confirm_{i}",use_container_width=True,type="primary"): close_active_dialog(); end_mouse(i); st.rerun()

@st.dialog("Reset subject",dismissible=False)
def reset_confirmation_dialog(i):
    st.markdown(f"### Reset {html.escape(subject_name(i))}?",unsafe_allow_html=True); st.write("This clears timer events and timesheet entries for this subject."); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key=f"reset_cancel_{i}",use_container_width=True): close_active_dialog(); st.rerun()
    with right:
        if st.button("Reset",key=f"reset_confirm_{i}",use_container_width=True,type="primary"): close_active_dialog(); reset_mouse(i); st.rerun()

@st.dialog("End all subjects")
def end_all_subjects_dialog():
    remaining=[i for i in ordered_subject_indices() if not is_ended(i)]
    st.markdown("### End all subjects?")
    st.write(f"This ends {len(remaining)} remaining subject{'s' if len(remaining)!=1 else ''} and downloads the aggregate timesheet.")
    map_targets=[i for i in remaining if st.session_state.get(f"resus_start_{i}") is not None]
    if map_targets:
        st.caption("Enter an ending MAP for each subject that has begun resuscitation.")
        for i in map_targets:
            key=f"end_all_map_{i}"; existing=ending_map(i); st.session_state.setdefault(key,"" if existing is None else f"{existing:g}")
            st.text_input(f"{subject_name(i)} ending MAP (mmHg)",key=key,placeholder="e.g. 75")
    left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="end_all_cancel",use_container_width=True):
            for i in map_targets: st.session_state.pop(f"end_all_map_{i}",None)
            st.rerun()
    with right:
        if st.button("End all subjects",key="end_all_confirm",use_container_width=True,type="primary"):
            ending_maps={}; errors=[]
            for i in map_targets:
                value,error=_parse_map_value(st.session_state.get(f"end_all_map_{i}"))
                if error: errors.append(f"{subject_name(i)}: {error}")
                else: ending_maps[i]=value
            if errors: st.warning(" ".join(errors))
            elif end_all_subjects_current_experiment(ending_maps):
                for i in map_targets: st.session_state.pop(f"end_all_map_{i}",None)
                queue_timesheet_auto_download(); st.rerun()
            else: st.error("Subjects were ended locally, but persistent storage has not confirmed the save yet.")

@st.dialog("Add mouse",dismissible=False)
def add_mouse_dialog():
    new_i=mouse_count()+1; nk,wk="_add_mouse_name","_add_mouse_weight"; st.session_state.setdefault(nk,f"Mouse {new_i}"); st.session_state.setdefault(wk,_default_entry_weight()); st.caption("Enter the mouse name and weight before adding it to the running experiment."); st.text_input("Mouse name",key=nk); st.number_input("Weight (g)",min_value=0.0,max_value=100.0,step=.1,format="%.1f",key=wk); left,right=st.columns(2)
    with left:
        if st.button("Cancel",key="add_mouse_cancel",use_container_width=True): close_active_dialog(); st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
    with right:
        if st.button("Add mouse",key="add_mouse_confirm",use_container_width=True,type="primary"):
            name,weight,error=validate_mouse_name_weight(st.session_state.get(nk),st.session_state.get(wk),f"Mouse {new_i}")
            if error: st.warning(error)
            elif weight_requires_confirmation(weight): close_active_dialog(); queue_weight_warning("add_mouse",[{"name":name,"weight_g":weight}]); st.rerun()
            else:
                ok,error=create_mouse_subject(name,weight)
                if ok: close_active_dialog(); st.session_state.pop(nk,None); st.session_state.pop(wk,None); st.rerun()
                st.warning(error)

def request_add_mouse_dialog():
    st.session_state["_pending_dialog"]={"mouse":0,"kind":"add_mouse"}
    st.session_state["_needs_full_rerun"]=True

def close_active_dialog():
    """Dismiss the dialog opened through the fragment-to-app handoff."""
    st.session_state.pop("_active_dialog",None)
    st.session_state.pop("_pending_dialog",None)

def request_dialog(i,kind,**extra):
    st.session_state["_pending_dialog"]={"mouse":int(i),"kind":kind,**extra}
    st.session_state["_needs_full_rerun"]=True
def request_end_dialog(i,forced=False):
    if st.session_state.get(f"resus_start_{i}") is not None: request_dialog(i,"ending_map",forced=bool(forced))
    else: request_dialog(i,"end")
def _rerun_entire_app():
    """Force an app-level rerun even when invoked from inside a Streamlit fragment."""
    try:
        st.rerun(scope="app")
    except TypeError:
        # Compatibility fallback for Streamlit versions without the scope kwarg.
        st.rerun()

def render_pending_dialog():
    req=st.session_state.pop("_pending_dialog",None)
    if req:
        # A timer row lives in a fragment, but Streamlit dialogs must be
        # rendered by the full app. Retain the request until a dialog action
        # explicitly dismisses it, rather than losing it on the next refresh.
        st.session_state["_active_dialog"]=req
    req=st.session_state.get("_active_dialog")
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

def collect_attention_items(wall_now):
    """Return sticky warning/overdue alerts for the current timer frame."""
    sticky = st.session_state.setdefault("_sticky_alerts", {})
    active_keys = set()

    for i in ordered_subject_indices():
        if is_ended(i):
            clear_mouse_alerts(i)
            continue

        now = effective_now(i, wall_now)
        for event, remaining in get_upcoming_events(i, now):
            key = alert_key(i, event)
            active_keys.add(key)
            level = urgency_for_remaining(remaining)

            # Sticky alerts appear once they enter warning or overdue state and
            # remain present until the underlying task is resolved.
            if level in ("orange", "red"):
                sticky[key] = {
                    "mouse": i,
                    "name": subject_name(i),
                    "event": event,
                    "remaining": remaining,
                    "level": level,
                }

    # Drop alerts whose underlying task no longer exists.
    for key in tuple(sticky):
        if key not in active_keys:
            sticky.pop(key, None)

    items = []
    for alert in sticky.values():
        item = dict(alert)
        item["targets"] = action_targets_for_alert(
            item["mouse"], item["event"], item["remaining"]
        )
        items.append(item)

    # Overdue items sort before upcoming warnings, then by time remaining.
    return sorted(
        items,
        key=lambda item: (
            0 if item["level"] == "red" else 1,
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

def install_browser_helpers():
    components.html(r"""
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

      function poll(){
        const ss=doc.querySelectorAll('[data-lab-attention-snapshot]');
        if(ss.length){
          const e=ss[ss.length-1].dataset.labAttentionSnapshot;
          if(e&&e!==last) apply(e);
        }
        highlights();
        full();
        download();
      }

      /*
        This component is installed again after a full Streamlit rerun.  Keep
        exactly one parent-window poller so those reruns cannot leave behind
        a growing collection of 10 Hz DOM scans.  Pointing the singleton at
        the latest closure also keeps the current component's state active.

        The actual notification uses scheduleDue()'s absolute setTimeout, so
        this one-second poll rate does not reduce alert precision.
      */
      root.__shockTimerBrowserHelpersPoll=poll;
      poll();
      if(!root.__shockTimerBrowserHelpersPollInterval){
        root.__shockTimerBrowserHelpersPollInterval=root.setInterval(()=>{
          const current=root.__shockTimerBrowserHelpersPoll;
          if(typeof current==='function') current();
        },1000);
      }
    })();
    </script>
    """,width=1,height=1,tab_index=-1)
# ============================================================
# DISPLAY / WORKFLOW
# ============================================================


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
    anes,board,shock,resus=anesthesia_preparation_start(i),st.session_state.get(f"board_start_{i}"),st.session_state.get(f"shock_start_{i}"),st.session_state.get(f"resus_start_{i}"); end_time=st.session_state.get(f"end_time_{i}") if is_ended(i) else None; times=[("","gray") for _ in range(4)]
    # Anesthesia is an elapsed preparation duration, not a countdown. Once
    # board acclimation starts, freeze that recorded duration for the run.
    if anes is not None: times[0]=(format_phase_timer(elapsed_from(anes,board if board is not None else now)),"gray" if board is not None else "green")
    if board is not None:
        stop=shock if shock is not None else now; urgency=urgency_for_remaining(remaining_from_start(board,FIXED_BOARD_DURATION,now)); times[1]=(f"{format_phase_timer(elapsed_from(board,stop))} / {format_phase_timer(duration_to_seconds(FIXED_BOARD_DURATION))}","gray" if shock is not None else urgency if urgency!="normal" else "green")
    if shock is not None:
        stop=resus if resus is not None else now; urgency=urgency_for_remaining(remaining_from_start(shock,FIXED_SHOCK_DURATION,now)); times[2]=(f"{format_phase_timer(elapsed_from(shock,stop))} / {format_phase_timer(duration_to_seconds(FIXED_SHOCK_DURATION))}","gray" if resus is not None else urgency if urgency!="normal" else "green")
    if resus is not None:
        stop=end_time if end_time is not None else now; urgency=urgency_for_remaining(remaining_from_start(resus,FIXED_RESUSCITATION_DURATION,now)); times[3]=(f"{format_phase_timer(elapsed_from(resus,stop))} / {format_phase_timer(duration_to_seconds(FIXED_RESUSCITATION_DURATION))}","gray" if is_ended(i) else urgency if urgency!="normal" else "green")
    return times

def workflow_html(i,now):
    labels=["Anesthesia",f"Board {fixed_duration_label(FIXED_BOARD_DURATION)}",f"Shock {fixed_duration_label(FIXED_SHOCK_DURATION)}",f"Resus {fixed_duration_label(FIXED_RESUSCITATION_DURATION)}"]
    board=st.session_state.get(f"board_start_{i}"); shock=st.session_state.get(f"shock_start_{i}"); resus=st.session_state.get(f"resus_start_{i}")
    progress={}
    if board is not None and shock is None:
        progress[1]=min(100.0,max(0.0,100.0*elapsed_from(board,now)/duration_to_seconds(FIXED_BOARD_DURATION)))
    if shock is not None and resus is None:
        progress[2]=min(100.0,max(0.0,100.0*elapsed_from(shock,now)/duration_to_seconds(FIXED_SHOCK_DURATION)))
    statuses=workflow_statuses(i,now); times=workflow_step_times(i,now); parts=['<div class="lab-cell"><div class="lab-stepper">']
    for idx,(state,label) in enumerate(zip(statuses,labels)):
        timer,tone=times[idx]
        extra=""
        if idx in progress:
            extra=f' timed-progress" style="--lab-progress:{progress[idx]:.2f}%'
        th=f'<div class="lab-step-time {tone}">{html.escape(timer)}</div>' if timer else '<div class="lab-step-time">&nbsp;</div>'
        parts.append(f'<div class="lab-step {state}{extra}"><div class="lab-step-circle">{idx+1}</div><div class="lab-step-label">{html.escape(label)}</div>{th}</div>')
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
        with st.container(key=f"primary_action_{i}"): st.button("■ End",key=f"primary_end_{i}",use_container_width=True,on_click=request_end_dialog,args=(i,False)); return
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
    elif label=="⏭ Force end subject": request_end_dialog(i,True)

def _process_menu(i,selection):
    if not selection: return
    # Menu choices are rendered from the refresh fragment, whereas dialogs
    # must be opened during a full app rerun. Request the dialog, then rerun
    # the complete app explicitly instead of relying on a fragment rerun.
    if selection=="View timesheet": request_dialog(i,"timesheet"); _rerun_entire_app()
    elif selection=="Add comment": request_dialog(i,"comment"); _rerun_entire_app()
    elif selection=="Edit subject": request_dialog(i,"edit"); _rerun_entire_app()
    elif selection in ("Ⅱ Pause","▶ Resume"): toggle_pause(i); st.rerun()
    elif selection=="↑ Move up": move_subject(i,-1); st.rerun()
    elif selection=="↓ Move down": move_subject(i,1); st.rerun()
    elif selection.startswith("↶ Undo"): undo_last_stage_action(i); st.rerun()
    elif selection.startswith("⏭ Force"):
        force_advance(i)
        _rerun_entire_app()
    elif selection=="↻ Reset subject": request_dialog(i,"reset"); _rerun_entire_app()
    elif selection=="■ End subject": request_end_dialog(i,False); _rerun_entire_app()

def render_overflow_control(i,now):
    options=["View timesheet","Add comment","Edit subject"]; group=reorder_group(i,time.time()); peers=[j for j in ordered_subject_indices() if reorder_group(j,time.time())==group]
    if i in peers:
        pos=peers.index(i)
        if pos>0: options.append("↑ Move up")
        if pos<len(peers)-1: options.append("↓ Move down")
    undo=latest_undo_action(i)
    if undo and not is_ended(i): options.append(f"↶ Undo {undo_label(undo)}")
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

def render_mouse_row(i, wall_now, finished=False):
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
                render_overflow_control(i, now)


@st.fragment(run_every=REFRESH_INTERVAL)
def show_timers():
    if st.session_state.get("_pending_dialog"):
        st.session_state["_needs_full_rerun"]=False
        _rerun_entire_app()
    if st.session_state.pop("_needs_full_rerun",False):
        _rerun_entire_app()
    wall_now=time.time()
    attention_items=collect_attention_items(wall_now)
    render_attention_snapshot(attention_items)
    active=[]
    completed=[]
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

header = st.columns(HEADER_COLUMNS, vertical_alignment="center")
with header[0]:
    if st.button("← Experiments",key="back_to_experiments",use_container_width=True): return_to_experiment_home()
with header[1]:
    exp_name=html.escape(str(st.session_state.get("_active_experiment_name","Experiment")))
    st.markdown(f'<div class="lab-header-title">{exp_name}</div><div class="lab-header-subtitle">{mouse_count()} mice · persistent session</div>',unsafe_allow_html=True)
with header[2]: st.button("⛶ Full screen",key="fullscreen_view",use_container_width=True)
with header[3]:
    available=global_undo_available(); target=global_undo_label(); help_text=f"Undo: {target}" if available else "No action available to undo"
    if st.button("↶ Undo",key=f"global_undo_{global_undo_token()}",use_container_width=True,disabled=not available,help=help_text): global_undo_last_action(); st.rerun()
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
    if st.button("■ End all subjects",key="end_all_subjects",use_container_width=True): end_all_subjects_dialog()
with header[6]:
    if st.button("⚙ Settings",key="open_settings",use_container_width=True): settings_dialog()

if st.session_state.get("_storage_error"): st.error("SAVE WARNING: recent changes have not been confirmed by persistent storage. "+str(st.session_state["_storage_error"]))
st.markdown('<div class="lab-divider"></div>',unsafe_allow_html=True)
show_timers()
