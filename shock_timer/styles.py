"""Streamlit presentation styles for the Shock Timer interface."""

import streamlit as st

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
    /* Only Board and Shock have fixed endpoints, so only their connectors
       display a blue elapsed-time progress fill. */
    .lab-step.timed-progress:not(:last-child)::after{background:linear-gradient(90deg,rgba(22,140,255,.76) 0 var(--lab-progress),rgba(117,137,157,.34) var(--lab-progress) 100%)!important}
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

    /* =========================================================
       V40 COMPACT DENSITY PASS
       Same selected design; optimized to show more channels.
       ========================================================= */

    .stMainBlockContainer{
        padding:.62rem 1.20rem 4.75rem!important;
    }

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

    

    /* ---------------- Home header ---------------- */
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

    /* Compact warning only when cloud storage is unavailable. */
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

    /* ---------------- Major home cards ---------------- */
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

    /* ---------------- New experiment row ---------------- */
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

    /* ---------------- Experiment rows ---------------- */
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

    /* Smaller, quieter management actions. */
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

    /* Delete is the only consistently destructive control on the home list. */
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

    /* Empty states stay quiet inside the card. */
    .home-empty-state {
        color:#718090;
        font-size:.72rem;
        padding:.42rem .10rem .26rem;
    }

    /* Error messages from new-experiment validation remain compact. */
    div[class*="st-key-home_new_experiment"] [data-testid="stAlert"] {
        padding:.48rem .64rem!important;
        margin-top:.18rem!important;
    }

    @media(max-width:1180px) {
        .home-exp-meta { font-size:.63rem; }
    }
    

    /* ---------- Home screen text / button balance ---------- */
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

    /* ---------- Configure experiment dialog ---------- */
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
    

    /* Dialog intro block: prevent stacking/overlap and create clear hierarchy */
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

    /* Keep headers clearly separated from the first row */
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

    /* Row shell */
    div[class*="st-key-cfg_row_shell_"]{
        background:linear-gradient(180deg,rgba(13,24,36,.66),rgba(10,19,29,.66))!important;
        border:1px solid rgba(137,160,184,.15)!important;
        border-radius:10px!important;
        padding:.22rem .26rem!important;
        margin:.03rem 0!important;
    }

    /* Left index alignment */
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

    /* Add mouse and footer buttons */
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

    /* Ensure the dialog itself has enough top breathing room */
    [data-testid="stDialog"] [role="dialog"]{
        padding-top:.22rem!important;
    }
    

    /* Separate the anesthesia status/weight from the redose controls. */
    .lab-anesthesia-copy{
        min-height:2.28rem!important;
        margin:0 0 .24rem 0!important;
    }

    div[class*="st-key-anesthesia_redose_action_"] button,
    div[class*="st-key-anesthesia_delay_action_"] button{
        margin-top:.08rem!important;
    }

    /* Keep the two anesthesia buttons visually grouped, but not crowded. */
    div[class*="st-key-anesthesia_redose_action_"],
    div[class*="st-key-anesthesia_delay_action_"]{
        padding-top:.02rem!important;
        padding-bottom:.02rem!important;
    }
    

    /*
      The previous layout let the weight line visually intrude into the button
      row. Give the label, reminder, and weight three explicit rows and reserve
      real vertical space before the controls.
    */
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
    

    /* ---------- Subject identity / starting MAP ---------- */
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

    /* ---------- Anesthesia status ---------- */
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

    /* The old V48 weight row must not participate in layout if any
       stale markup survives a rerun during development. */
    .lab-anesthesia-weight{
        display:none!important;
    }

    /* Explicit breathing room between status line and buttons. */
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
    

    /* Make the weight visually equal to the redose timer text. */
    .lab-anesthesia-weight-inline{
        color:#eef2f5!important;
        font-size:.79rem!important;
        font-weight:680!important;
        line-height:1.10!important;
        white-space:nowrap!important;
        text-align:right!important;
    }

    /* Add real breathing room before the Redose / Delay controls. */
    .lab-anesthesia-copy{
        padding-bottom:.52rem!important;
    }

    div[class*="st-key-anesthesia_controls_"]{
        margin-top:.28rem!important;
        padding-top:.06rem!important;
    }
    

    /*
      Give the timer/weight row a clearly separate visual band from
      the Redose / Delay controls. The buttons are made slightly
      shorter so the added whitespace does not unnecessarily inflate
      the overall subject row.
    */
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
    

    /*
      The anesthesia/action side can make a subject card taller than the first
      three columns. Explicitly stretch those columns and center their contents.
    */
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
    

    /*
      Always reserve the Starting MAP line. Before a value exists the text is
      invisible, so Mouse N never jumps when the MAP is later recorded.
    */
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

    /*
      Reminder audio is rendered by Streamlit so it uses the same browser path
      as the working Settings sound preview. Hide only the player chrome.
    */
    div[class*="st-key-overdue_sound_"]{
        position:absolute!important;
        width:1px!important;
        height:1px!important;
        overflow:hidden!important;
        opacity:.001!important;
        pointer-events:none!important;
    }

    div[class*="st-key-overdue_sound_"] audio{
        width:1px!important;
        height:1px!important;
    }
    

    /*
      Mouse status dot, mouse icon, mouse name, Next Event value/timer,
      and Total value now share the same vertical center line.
    */
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

    /*
      MAP and Paused labels are annotations around the fixed subject-name
      anchor; they never change the Mouse N position.
    */
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

    /*
      Labels float above the centered value instead of pushing the timer
      downward. This is what aligns the actual timer/value with Mouse N.
    */
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
    

    /* ---------------------------------------------------------
       Subject identity
       Keep a permanent two-line subject block so adding Starting
       MAP never moves the mouse label, but center the NAME + MAP
       combination as a whole within the row.
       --------------------------------------------------------- */
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

    /* Keep pause as an annotation without disturbing the centered block. */
    .lab-paused-label{
        position:absolute!important;
        left:0!important;
        bottom:2.38rem!important;
        margin:0!important;
    }

    /* ---------------------------------------------------------
       Next event spacing
       Move the entire Next Event content slightly to the right so
       the subject identity and next-event groups do not crowd.
       --------------------------------------------------------- */
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

    /* ---------------------------------------------------------
       Redose state visibility
       Normal = quiet orange outline.
       Warning = stronger amber.
       Overdue = unmistakable red/pink status + red Redose button.
       Delay remains purple so the two actions stay visually distinct.
       --------------------------------------------------------- */
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
    

    /*
      Make the first three columns behave like consistent stacked blocks so
      their internal horizontal guides line up across every row.
    */

    /* ---------- Subject column ---------- */
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

    /* ---------- Next event column ---------- */
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

    /* ---------- Total column ---------- */
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

    /* Remove old centering behavior that could fight the grid alignment. */
    .lab-cell{
        margin-top:0!important;
        margin-bottom:0!important;
    }
    

    /* ---------------------------------------------------------
       SUBJECT
       Two permanent rows:
         Mouse N
         Starting MAP (invisible placeholder until available)

       Dot and mouse icon are anchored to the Mouse N row only.
       --------------------------------------------------------- */
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

    /* Center these against the Mouse N line, not the two-line subject block. */
    .lab-dot{
        flex:0 0 auto!important;
        margin-top:.27rem!important;
    }

    .lab-mouse-icon{
        flex:0 0 auto!important;
        margin-top:-.31rem!important;
    }

    /* ---------------------------------------------------------
       NEXT EVENT
       Exactly two permanent rows for every state:
         NEXT EVENT
         event/value

       This prevents the block from moving when a timer starts.
       --------------------------------------------------------- */
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

    /* Kill old absolute-position rules from earlier versions. */
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

    /* ---------------------------------------------------------
       TOTAL
       Same fixed two-row geometry as Next Event.
       --------------------------------------------------------- */
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

    /* Keep pause as an annotation, without changing the fixed subject grid. */
    .lab-paused-label{
        position:absolute!important;
        left:0!important;
        bottom:2.42rem!important;
        margin:0!important;
    }
    

    /*
      The second row under NEXT EVENT now has one fixed typography
      regardless of state: not started, countdown, warning, or overdue.
      It matches the Starting MAP line under the subject name.
    */
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

    /* Preserve only the state color; never change size/weight by state. */
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

    
"""


def install_app_styles():
    """Install the complete application stylesheet once per script rerun."""
    st.markdown("<style>" + APP_CSS + "</style>", unsafe_allow_html=True)

