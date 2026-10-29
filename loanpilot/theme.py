"""Shared visual elements for LoanPilot pages."""

from base64 import b64encode
from html import escape
from pathlib import Path

import streamlit as st

from loanpilot.badges import implementation_badge

_CSS = """
<style>
    html, body {
        width: 100% !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
    }
    [data-testid="stAppViewContainer"] {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
        overflow-x: hidden !important;
    }
    [data-testid="stMainBlockContainer"] {
        width: 100% !important;
        max-width: 1280px !important;
        min-width: 0 !important;
    }
    [data-testid="stMain"] {
        flex: 1 1 auto !important;
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    [data-testid="stHorizontalBlock"],
    [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    @media (max-width: 760px) {
        [data-testid="stHorizontalBlock"]:has([class*="st-key-overview_portfolio_monthly"]) {
            flex-direction: column !important;
            align-items: stretch !important;
        }
        [data-testid="stHorizontalBlock"]:has([class*="st-key-overview_portfolio_monthly"]) [data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
        [data-testid="stMain"]:has([class*="st-key-overview_portfolio_year"]) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
            flex-wrap: wrap !important;
            gap: .55rem !important;
        }
        [data-testid="stMain"]:has([class*="st-key-overview_portfolio_year"]) [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) [data-testid="stColumn"] {
            width: calc(50% - .3rem) !important;
            flex: 1 1 calc(50% - .3rem) !important;
        }
        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label,
        label[data-react-aria-pressable="true"] {
            box-sizing: border-box;
            min-height: 44px !important;
            height: auto !important;
            padding: 8px 12px 8px 4px !important;
            align-items: center;
            cursor: pointer;
            touch-action: manipulation;
        }
        [data-testid="stCheckbox"] input[type="checkbox"],
        [data-testid="stRadio"] input[type="radio"],
        label[data-react-aria-pressable="true"] input[type="checkbox"],
        label[data-react-aria-pressable="true"] input[type="radio"] {
            min-width: 20px !important;
            width: 20px !important;
            min-height: 20px !important;
            height: 20px !important;
        }
        [data-testid="stBaseButton-primary"],
        [data-testid="stBaseButton-secondary"] {
            min-height: 44px !important;
            touch-action: manipulation;
        }
    }
    [class*="st-key-hr-decided-"] {
        border-radius: 10px;
        background: rgba(243, 247, 248, .78);
        padding: .15rem .3rem;
    }
    [class*="st-key-hr-reason-"] {
        border: 2px solid #d59a36;
        background: #fffaf0;
        padding: .75rem;
        border-radius: 12px;
    }
    [class*="st-key-review-count-total"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border-color: #dfe5e8;
    }
    [class*="st-key-review-count-pending"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fffaf3;
        border-color: #f6d7b5;
    }
    [class*="st-key-review-count-approved"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #f6fff9;
        border-color: #cfead8;
    }
    [class*="st-key-review-count-rejected"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fff7f6;
        border-color: #efcfcb;
    }
    :root {
        --lp-ink: #24333a;
        --lp-muted: #68777d;
        --lp-teal: #138b83;
        --lp-line: #e1e7e9;
        --lp-canvas: #ffffff;
    }
    .stApp {
        background: var(--lp-canvas);
        color: var(--lp-ink);
    }
    [data-testid="stHeader"] {
        background: rgba(255, 255, 255, .92);
        backdrop-filter: blur(12px);
    }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e1e7e9;
    }
    [data-testid="stSidebar"] * { color: #24333a; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #68777d; }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a {
        border-radius: 10px;
        margin: 3px 0;
        border: 1px solid transparent;
        transition: background .18s ease, transform .18s ease;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
        background: #f4f7f8;
        border-color: #e1e7e9;
        transform: translateX(2px);
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
        background: #edf5f4;
        border-color: #c9e2df;
        box-shadow: inset 3px 0 #138b83;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
        background: transparent;
        border-color: #d7e0e3;
        color: #34454c;
    }
    .block-container {
        max-width: 1280px;
        padding-top: 4.3rem;
        padding-bottom: 3rem;
    }
    [data-testid="stVerticalBlock"] { gap: .8rem; }
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"],
    [data-testid="stText"],
    [data-testid="stAlert"] {
        font-size: 15px;
        line-height: 1.5;
    }
    h1, h2, h3, h4 {
        color: var(--lp-ink);
        letter-spacing: -.025em;
    }
    h1 {
        font-size: clamp(2rem, 3.2vw, 2.8rem) !important;
        line-height: 1.1 !important;
        font-weight: 760 !important;
        margin: .25rem 0 .45rem !important;
    }
    h2 { font-weight: 720 !important; }
    h3 { font-weight: 690 !important; }
    p { color: var(--lp-muted); }
    [data-testid="stCaptionContainer"] {
        color: #536c6d;
        font-size: 14px;
        line-height: 1.45;
    }
    [data-testid="stCaptionContainer"] p { font-size: 14px; }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #fff, #f8fbfb);
        border: 1px solid var(--lp-line);
        border-radius: 14px;
        padding: .9rem 1rem;
        box-shadow: 0 5px 16px rgba(20, 59, 60, .045);
    }
    [data-testid="stMetricLabel"] p {
        color: var(--lp-muted);
        font-size: .9rem;
        font-weight: 650;
        letter-spacing: .035em;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] { color: var(--lp-ink); font-weight: 760; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--lp-line);
        border-radius: 14px;
        background: rgba(255,255,255,.88);
        box-shadow: 0 4px 14px rgba(20, 59, 60, .04);
        padding: .9rem 1rem;
    }
    [data-testid="stExpander"] {
        background: rgba(255,255,255,.78);
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
    }
    [data-testid="stExpander"] summary { font-weight: 650; color: var(--lp-ink); }
    [data-testid="stTabs"] [role="tablist"] {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: .35rem;
        border-bottom: 1px solid var(--lp-line);
    }
    [data-testid="stTabs"] button[role="tab"] {
        min-height: 42px;
        max-width: 100%;
        border-radius: 10px 10px 0 0;
        padding: .6rem .9rem;
        color: var(--lp-muted);
        font-weight: 630;
        white-space: normal;
        line-height: 1.25;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        color: #11776f;
        background: #eef7f6;
    }
    [data-testid="stTabs"] [data-testid="stVerticalBlock"] { gap: .7rem; }
    [data-testid="stProgress"] > div > div > div { background: #138b83; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        font-size: 14px;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        font-size: 14px;
        color: #68777d;
    }
    .lp-sidebar-brand {
        position: relative;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        color: #155e59;
        font-size: 1.12rem;
        font-weight: 720;
        letter-spacing: -.01em;
        margin: .2rem 0 1.2rem;
        padding: .8rem .75rem .8rem .95rem;
        border: 1px solid #b6d8d4;
        border-radius: 14px;
        background: #e9f4f3;
        box-shadow: 0 5px 16px rgba(20, 59, 60, .08);
    }
    .lp-sidebar-brand:before {
        position: absolute;
        inset: 0 auto 0 0;
        width: 4px;
        background: linear-gradient(180deg, #168f87, #11766f);
        content: "";
    }
    .lp-sidebar-brand span {
        color: #456b69;
        font-size: .88rem;
        font-weight: 550;
        letter-spacing: 0;
    }
    .lp-sidebar-section {
        margin: .9rem .25rem .25rem;
        color: #45646a;
        font-size: .74rem;
        font-weight: 750;
        letter-spacing: .1em;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
        background: #eef7f6;
        border-color: #c9e2df;
        color: #255a56;
    }
    input, textarea, [data-baseweb="select"] > div {
        border-color: #cbd6da !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stExpander"],
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        border-color: #dbe3e6;
    }
    [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
        background: #138b83 !important;
        color: #fff !important;
        border-color: #0e756f !important;
    }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
        background: white;
    }
    .lp-table-wrap {
        width: 100%;
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
        background: #fff;
    }
    .lp-data-table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: .88rem;
    }
    .lp-data-table th,
    .lp-data-table td {
        padding: .5rem .55rem;
        border-bottom: 1px solid #e8eeee;
        text-align: left;
        vertical-align: middle;
        overflow-wrap: anywhere;
    }
    .lp-data-table th {
        background: #f4f8f7;
        color: #355a59;
        font-size: .78rem;
        font-weight: 700;
    }
    .lp-data-table tr:last-child td { border-bottom: 0; }
    .lp-demo-story {
        min-height: 1.35rem;
        overflow: hidden;
        color: #536c6d;
        font-size: .82rem;
        line-height: 1.35;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .lp-assessment-progress {
        display: grid;
        grid-template-columns: repeat(5, minmax(7.5rem, 1fr));
        gap: .55rem;
        width: 100%;
        margin: .55rem 0 1.25rem;
    }
    .lp-assessment-step {
        min-width: 0;
        min-height: 3rem;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: .35rem;
        padding: .5rem .55rem;
        border: 1px solid #dce8e7;
        border-radius: 8px;
        background: #fff;
        color: #536c6d;
        font-size: .8rem;
        font-weight: 650;
        line-height: 1.25;
        text-align: center;
        white-space: normal;
    }
    .lp-assessment-step.done { color: #155e49; background: #e8f4e9; }
    .lp-assessment-step.running { color: #075957; background: #e4f1ef; border-color: #0e7775; }
    .lp-assessment-step.waiting { color: #586867; background: #f3f5f5; }
    .lp-decision-title {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: .65rem;
        color: #173b39;
        font-size: clamp(1.7rem, 3vw, 2.45rem);
        font-weight: 780;
        line-height: 1.15;
    }
    .lp-decision-title.success { color: #176b3f; }
    .lp-decision-title.warning { color: #805400; }
    .lp-decision-title.danger { color: #9d2f2a; }
    .lp-decision-summary {
        display: -webkit-box;
        max-width: 70rem;
        margin: .55rem 0 .85rem;
        overflow: hidden;
        color: #465e5d;
        font-size: 1rem;
        line-height: 1.45;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
    }
    .lp-decision-fact {
        min-height: 3.8rem;
        padding: .65rem .7rem;
        border: 1px solid #dce8e7;
        border-radius: 10px;
        background: #f8fbfb;
    }
    .lp-decision-fact span {
        display: block;
        color: #536c6d;
        font-size: .78rem;
        font-weight: 650;
        line-height: 1.2;
    }
    .lp-decision-fact strong {
        display: block;
        margin-top: .35rem;
        color: #173b39;
        font-size: .96rem;
        overflow-wrap: anywhere;
    }
    .lp-decision-facts {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .55rem;
    }
    .lp-decision-facts.compact {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    @media (max-width: 760px) {
        .lp-decision-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .lp-assessment-progress { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .lp-assessment-step { min-height: 2.8rem; font-size: .75rem; }
        .lp-why-line { grid-template-columns: 1.1rem minmax(0, 1fr); }
        .lp-why-line .lp-status-chip { grid-column: 2; justify-self: start; }
    }
    @media (min-width: 761px) and (max-width: 1120px) {
        .lp-assessment-progress { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    .lp-why-line {
        display: grid;
        grid-template-columns: 1.2rem minmax(0, 1fr) auto;
        align-items: center;
        gap: .55rem;
        margin: .35rem 0;
        color: #294947;
        font-size: .94rem;
        line-height: 1.35;
    }
    .lp-why-line > span:first-child { font-weight: 800; }
    .lp-policy-table {
        width: 100%;
        table-layout: fixed;
        border-collapse: collapse;
        color: #173b39;
        font-size: .9rem;
    }
    .lp-policy-table th, .lp-policy-table td {
        padding: .55rem;
        border: 1px solid #dce8e7;
        text-align: left;
        vertical-align: top;
        overflow-wrap: anywhere;
        white-space: normal;
    }
    .lp-policy-table th { background: #f3f7f7; }
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #0d7774, #176b69);
        color: #fff !important;
        border: 0;
        border-radius: 11px;
        box-shadow: 0 5px 13px rgba(14,119,117,.18);
        font-weight: 680;
        transition: transform .18s ease, box-shadow .18s ease;
    }
    [data-testid="stBaseButton-primary"] *,
    button[kind="primary"] * {
        color: #fff !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg, #096865, #135c5a);
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(14,119,117,.24);
    }
    [data-testid="stBaseButton-secondary"] {
        border-radius: 11px;
        border-color: #c9d9d8;
        color: var(--lp-ink) !important;
        font-weight: 620;
    }
    [data-testid="stBaseButton-secondary"] * {
        color: var(--lp-ink) !important;
    }
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        border: 1px solid #9fb3ad !important;
        border-radius: 8px !important;
        background: #fff !important;
        color: #173b39 !important;
        box-shadow: none !important;
    }
    [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea,
    [data-baseweb="select"] input {
        color: #173b39 !important;
        background: #fff !important;
        caret-color: #0e7775;
    }
    [data-baseweb="input"] input::placeholder,
    [data-baseweb="textarea"] textarea::placeholder,
    [data-baseweb="select"] input::placeholder {
        color: #637777 !important;
        opacity: 1;
    }
    [data-baseweb="input"] > div:focus-within,
    [data-baseweb="textarea"] > div:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: #0e7775 !important;
        box-shadow: 0 0 0 3px rgba(14,119,117,.2) !important;
    }
    [data-testid="stDateInput"] input,
    [data-testid="stNumberInput"] input {
        color: #173b39 !important;
        background: #fff !important;
    }
    [data-testid="stDateInput"] input,
    [data-testid="stNumberInput"] > div > div,
    [data-testid="stTextInput"] > div > div {
        border: 1px solid #9fb3ad !important;
        border-radius: 8px !important;
    }
    [data-testid="stDateInput"] input:focus,
    [data-testid="stNumberInput"] input:focus,
    [data-testid="stTextInput"] input:focus {
        border-color: #0e7775 !important;
        box-shadow: 0 0 0 3px rgba(14,119,117,.2) !important;
    }
    .lp-badge-legend {
        display: grid;
        gap: .3rem;
        justify-items: start;
        max-width: 100%;
    }
    .lp-badge-legend span {
        max-width: 100%;
        white-space: normal;
        line-height: 1.25;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
        color: #24333a;
    }
    .lp-eyebrow {
        color: #167c76;
        font-size: .78rem;
        font-weight: 760;
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: .35rem;
    }
    .lp-subtitle {
        color: #627779;
        font-size: 1rem;
        max-width: 58rem;
        margin: .1rem 0 1rem;
    }
    .lp-pipeline-card {
        min-height: 5.25rem;
        padding: .65rem .6rem;
        border: 1px solid #dce8e7;
        border-radius: 15px;
        background: linear-gradient(145deg, #fff, #f8fbfb);
        box-shadow: 0 5px 15px rgba(20,59,60,.045);
        text-align: center;
    }
    .lp-pipeline-card.is-done {
        border-color: #a9d8cb;
        background: linear-gradient(145deg, #f0faf6, #e7f5ef);
    }
    .lp-pipeline-card.is-ready {
        border: 1.5px solid #67b9ad;
        box-shadow: 0 0 0 3px rgba(48,157,143,.1);
    }
    .lp-pipeline-state {
        color: #637b7b;
        font-size: .85rem;
        font-weight: 740;
        letter-spacing: .045em;
        text-transform: uppercase;
    }
    .lp-pipeline-card.is-done .lp-pipeline-state { color: #167b64; }
    .lp-pipeline-card.is-ready .lp-pipeline-state { color: #08736d; }
    .lp-pipeline-label {
        margin-top: .4rem;
        color: #183e3f;
        font-size: .9rem;
        font-weight: 660;
        line-height: 1.25;
    }
    .lp-stage-state {
        font-size: .82rem;
        font-weight: 650;
        color: #355a59;
        line-height: 1.2;
    }
    .lp-stage-label {
        margin-top: .25rem;
        font-size: .82rem;
        color: #536c6d;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }
    .loanpilot-banner {
        padding: 0.55rem 0.9rem;
        margin: 0 0 1.1rem 0;
        border-left: 4px solid #0f766e;
        border-radius: 0.35rem;
        background: #e8f4f2;
        color: #173b39;
        font-size: 0.92rem;
    }
    .loanpilot-kpi {
        padding: 1rem 1.1rem;
        border: 1px solid #dce8e7;
        border-radius: 1rem;
        background: linear-gradient(145deg, #ffffff, #f8fbfb);
        box-shadow: 0 5px 16px rgba(20, 59, 60, .045);
    }
    .loanpilot-kpi-label {
        color: #526563;
        font-size: 0.9rem;
    }
    .loanpilot-kpi-value {
        margin-top: 0.25rem;
        color: #173b39;
        font-size: 1.55rem;
        font-weight: 650;
    }
    button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(120deg, #168f87, #11766f) !important;
        border: 1px solid #0e756f !important;
        color: #fff !important;
        box-shadow: 0 4px 10px rgba(17, 118, 111, .14) !important;
    }
    button[data-testid="stBaseButton-primary"] *,
    button[data-testid="stBaseButton-primary"]:hover {
        color: #fff !important;
    }
    button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(120deg, #11766f, #0d625d) !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #34454c !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] * {
        color: #34454c !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-layout {
        display: flex;
        flex-direction: column;
        min-height: calc(100vh - 7rem);
    }
    [data-testid="stSidebarUserContent"] {
        padding-bottom: 1rem !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-nav {
        flex: 0 0 auto;
    }
    [data-testid="stSidebar"] .st-key-sidebar-layout > div:has(.st-key-sidebar-sign-out-area) {
        margin-top: auto;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area {
        padding: .65rem;
        border: 1px solid #b6d8d4;
        border-radius: 14px;
        background: #e9f4f3;
        box-shadow: 0 5px 16px rgba(20, 59, 60, .08);
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area [data-testid="stExpander"] {
        margin-bottom: .5rem;
        border-color: #c9e2df;
        border-radius: 10px;
        background: #ffffff;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area [data-testid="stExpander"] summary {
        color: #173b39;
        font-weight: 650;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button {
        width: 100%;
        border: 1px solid #0e756f !important;
        border-radius: 10px;
        background: linear-gradient(120deg, #168f87, #11766f) !important;
        color: #fff !important;
        font-weight: 700;
        box-shadow: 0 3px 8px rgba(17, 118, 111, .18);
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button * {
        color: #fff !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button:hover {
        border-color: #0d625d !important;
        background: linear-gradient(120deg, #11766f, #0d625d) !important;
    }
    .lp-eyebrow { color: #138b83 !important; }
    .lp-subtitle { color: #68777d !important; }
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        border-color: #cbd6da !important;
    }
    [data-baseweb="input"] > div:focus-within,
    [data-baseweb="textarea"] > div:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: #138b83 !important;
        box-shadow: 0 0 0 3px rgba(19, 139, 131, .16) !important;
    }
    :root {
        --lp-ink: #12304a;
        --lp-muted: #64748b;
        --lp-teal: #0f9488;
        --lp-line: #e2e9ed;
        --lp-canvas: #f5f8fa;
        --lp-surface: #ffffff;
        --lp-soft-teal: #eaf6f4;
    }
    .stApp {
        background: var(--lp-canvas);
        color: var(--lp-ink);
    }
    [data-testid="stMainBlockContainer"] {
        padding-top: 2.25rem !important;
        padding-bottom: 3rem !important;
    }
    [data-testid="stHeader"] {
        background: rgba(245, 248, 250, .96);
        backdrop-filter: blur(10px);
    }
    h1, h2, h3, h4 {
        color: var(--lp-ink) !important;
        letter-spacing: -.025em;
    }
    h1 {
        font-size: clamp(2rem, 3.1vw, 2.65rem) !important;
        font-weight: 740 !important;
    }
    h2 { font-weight: 700 !important; }
    h3 { font-weight: 680 !important; }
    p { color: var(--lp-muted); }
    .lp-eyebrow {
        color: #0b8178 !important;
        font-size: .73rem;
        letter-spacing: .13em;
    }
    .lp-subtitle {
        color: #64748b !important;
        margin-bottom: 1.25rem;
    }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid var(--lp-line);
    }
    [data-testid="stSidebar"] .st-key-sidebar-layout {
        min-height: calc(100dvh - 5.5rem);
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a {
        min-height: 2.7rem;
        padding: .55rem .7rem;
        border: 1px solid transparent;
        border-radius: 11px;
        color: #41576a;
        transition: background-color .15s ease, border-color .15s ease;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
        background: #f3f8f8;
        border-color: #e0eceb;
        transform: none;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
        background: var(--lp-soft-teal);
        border-color: #cde7e3;
        box-shadow: inset 3px 0 var(--lp-teal);
        color: #12645e;
        font-weight: 650;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] span,
    [data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] p {
        color: #12645e !important;
    }
    .lp-sidebar-brand {
        display: block;
        margin: .2rem 0 .8rem;
        padding: .35rem .45rem 1rem;
        overflow: visible;
        border: 0;
        border-bottom: 1px solid var(--lp-line);
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    }
    .lp-sidebar-brand:before { display: none; }
    .lp-sidebar-bank-row {
        display: flex;
        align-items: center;
        gap: .65rem;
        min-width: 0;
    }
    .lp-sidebar-bank-row img {
        display: block;
        flex: 0 0 42px;
        width: 42px;
        height: 42px;
    }
    .lp-sidebar-brand .lp-sidebar-bank-name {
        color: #12304a;
        font-size: 1.02rem;
        font-weight: 740;
        letter-spacing: -.02em;
        line-height: 1.25;
    }
    .lp-sidebar-product-name {
        margin: .5rem 0 0 3.1rem;
        color: #0f8178;
        font-size: .93rem;
        font-weight: 740;
        line-height: 1.25;
    }
    .lp-sidebar-tagline {
        margin: .13rem 0 0 3.1rem;
        color: #64748b;
        font-size: .72rem;
        line-height: 1.35;
    }
    .lp-update-summary {
        margin: .25rem 0 .1rem;
        color: #465d70;
        font-size: .96rem;
        line-height: 1.58;
        overflow-wrap: anywhere;
    }
    .lp-attention-issue {
        margin: .2rem 0 .5rem;
        color: #52677a;
        font-size: .9rem;
        overflow-wrap: anywhere;
    }
    .lp-attention-meta {
        display: flex;
        flex-wrap: wrap;
        gap: .35rem 1rem;
        color: #687b8b;
        font-size: .78rem;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area {
        padding: .7rem 0 0;
        border: 0;
        border-top: 1px solid var(--lp-line);
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area [data-testid="stExpander"] {
        margin-bottom: .65rem;
        border-color: transparent;
        background: transparent;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area [data-testid="stExpander"] summary {
        border-radius: 10px;
        color: #40576a;
        font-weight: 620;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button {
        min-height: 2.65rem;
        border-radius: 10px;
        background: #ffffff !important;
        border: 1px solid #d5e0e5 !important;
        box-shadow: none;
        color: #30485d !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button * {
        color: #30485d !important;
    }
    [data-testid="stSidebar"] .st-key-sidebar-sign-out-area button:hover {
        background: #f3f8f8 !important;
        border-color: #b7d8d3 !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--lp-line);
        border-radius: 15px;
        background: var(--lp-surface);
        box-shadow: 0 3px 12px rgba(18, 48, 74, .035);
    }
    [data-testid="stMetric"] {
        border-color: var(--lp-line);
        border-radius: 14px;
        background: linear-gradient(145deg, #fff, #f8fbfc);
        box-shadow: 0 3px 12px rgba(18, 48, 74, .035);
    }
    [data-testid="stMetricValue"] { color: var(--lp-ink); }
    [data-testid="stExpander"] {
        border-color: var(--lp-line);
        border-radius: 12px;
        background: #fff;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        background: var(--lp-soft-teal);
        color: #12645e;
    }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border-color: var(--lp-line);
        border-radius: 12px;
        background: #fff;
    }
    [data-testid="stDataFrame"] [role="columnheader"],
    [data-testid="stTable"] thead {
        background: #f1f6f7;
        color: #30485d;
    }
    [data-testid="stBaseButton-primary"] {
        border-radius: 10px;
        background: linear-gradient(120deg, #0f9488, #0b7e75) !important;
        border: 1px solid #0b7e75 !important;
        box-shadow: 0 3px 9px rgba(15, 148, 136, .16) !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(120deg, #0b8178, #086b64) !important;
        box-shadow: 0 5px 13px rgba(15, 148, 136, .22) !important;
    }
    [data-testid="stBaseButton-secondary"] {
        border-radius: 10px;
        border-color: #cbd9df;
        color: #23445a !important;
    }
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        border-color: #c9d6dd !important;
        border-radius: 10px !important;
    }
    [data-baseweb="input"] > div:focus-within,
    [data-baseweb="textarea"] > div:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--lp-teal) !important;
        box-shadow: 0 0 0 3px rgba(15, 148, 136, .17) !important;
    }
    [data-testid="stAlert"] {
        border-radius: 12px;
    }
    @media (max-width: 760px) {
        [data-testid="stMainBlockContainer"] {
            padding: 1.25rem 1rem 2rem !important;
        }
        .lp-sidebar-brand { margin-bottom: .5rem; }
        .lp-sidebar-bank-name { font-size: .98rem; }
    }
</style>
"""


def render_disclaimer() -> None:
    """Apply shared presentation styles without rendering a global banner."""
    st.markdown(_CSS, unsafe_allow_html=True)


def bank_logo_data_uri() -> str:
    """Return the bundled bank mark as a compact, transparent SVG data URI."""
    logo_path = Path(__file__).resolve().parent / "assets" / "aarambh-bank-logo.svg"
    encoded_logo = b64encode(logo_path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded_logo}"


def render_sidebar_brand(bank_name: str) -> None:
    """Render the shared bank mark and product wordmark in the sidebar."""
    st.markdown(
        '<div class="lp-sidebar-brand">'
        '<div class="lp-sidebar-bank-row">'
        f'<img src="{bank_logo_data_uri()}" alt="" aria-hidden="true">'
        f'<span class="lp-sidebar-bank-name">{escape(bank_name)}</span>'
        '</div><div class="lp-sidebar-product-name">LoanPilot</div>'
        '<div class="lp-sidebar-tagline">AI-Powered Lending Assistant</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_active_navigation_style(url_path: str) -> None:
    """Apply a stable teal active state to the current native page link."""
    selector = (
        '[data-testid="stSidebar"] '
        f'a[data-testid="stPageLink-NavLink"][href="{escape(url_path, quote=True)}"]'
    )
    st.markdown(
        f"""
        <style>
        {selector} {{
            background: #eaf6f4 !important;
            border-color: #cde7e3 !important;
            box-shadow: inset 3px 0 #0f9488 !important;
            color: #12645e !important;
            font-weight: 650 !important;
        }}
        {selector} span, {selector} p {{
            color: #12645e !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_login_styles() -> None:
    """Apply the focused, responsive LoanPilot sign-in theme."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"], [data-testid="stHeader"],
        [data-testid="stToolbar"], footer { display:none !important; }
        html, body, [data-testid="stAppViewContainer"] {
            min-width:0 !important;
            overflow-x:hidden !important;
        }
        [data-testid="stMain"] {
            align-items:center !important;
            justify-content:center !important;
        }
        [data-testid="stMainBlockContainer"] {
            width:100% !important;
            max-width:none !important;
            min-height:100vh !important;
            display:flex !important;
            align-items:center !important;
            justify-content:center !important;
            padding:32px 20px !important;
            box-sizing:border-box !important;
        }
        .stApp {
            color:#142d3b !important;
            background:
                radial-gradient(ellipse at 12% 8%, rgba(201,235,230,.38), transparent 40%),
                radial-gradient(ellipse at 92% 92%, rgba(221,240,237,.45), transparent 38%),
                linear-gradient(145deg,#f8fbfb 0%,#f2f8f7 52%,#fbfcfc 100%) !important;
        }
        .st-key-login-card {
            box-sizing:border-box;
            width:min(100%, 460px);
            margin:auto !important;
            padding:42px 42px 36px;
            border:1px solid #e1ecea;
            border-radius:20px;
            background:#fff;
            box-shadow:0 20px 52px rgba(22,57,65,.09), 0 2px 8px rgba(22,57,65,.035);
            gap:.55rem !important;
        }
        .lp-login-brand {
            display:flex;
            align-items:center;
            justify-content:center;
            gap:13px;
            margin-bottom:30px;
            color:#153447;
        }
        .lp-login-brand img {
            display:block;
            width:50px;
            height:50px;
        }
        .lp-login-brand-copy {
            display:flex;
            flex-direction:column;
            align-items:flex-start;
            gap:2px;
        }
        .lp-login-bank-name {
            color:#12304a;
            font-size:1.06rem;
            font-weight:740;
            line-height:1.2;
        }
        .lp-login-product-name {
            color:#0f8178;
            font-size:.91rem;
            font-weight:720;
            line-height:1.2;
        }
        .lp-login-tagline {
            color:#64748b;
            font-size:.73rem;
            line-height:1.25;
        }
        .lp-login-title {
            margin:0;
            color:#142d3b;
            text-align:center;
            font-size:2.05rem;
            font-weight:740;
            letter-spacing:-.045em;
        }
        .lp-login-subtitle {
            margin:5px 0 24px;
            color:#536b75;
            text-align:center;
            font-size:.97rem;
            line-height:1.5;
        }
        .st-key-login-card [data-testid="stForm"] {
            border:0 !important;
            padding:0 !important;
        }
        .st-key-login-card [data-testid="stTextInput"] label {
            color:#203b49 !important;
            font-weight:640;
        }
        .st-key-login-card [data-testid="stTextInput"] input {
            min-height:49px;
            padding-inline:14px;
            border:1px solid #cbd9dc !important;
            border-radius:11px !important;
            background:#fff !important;
            color:#142d3b !important;
            transition:border-color .15s ease, box-shadow .15s ease;
        }
        .st-key-login-card [data-testid="stTextInput"] input:focus {
            border-color:#16877f !important;
            outline:3px solid rgba(22,135,127,.17) !important;
            outline-offset:1px;
        }
        .st-key-login-card [data-testid="stBaseButton-primary"] {
            min-height:49px;
            border:1px solid #08766f !important;
            border-radius:11px !important;
            background:linear-gradient(115deg,#148e85,#08776f) !important;
            color:#fff !important;
            box-shadow:0 5px 12px rgba(8,119,111,.18) !important;
            font-weight:680;
            transition:filter .15s ease, box-shadow .15s ease;
        }
        .st-key-login-card [data-testid="stBaseButton-primary"] * {
            color:#fff !important;
        }
        .st-key-login-card [data-testid="stBaseButton-primary"]:hover {
            border-color:#075e59 !important;
            filter:brightness(.94);
            box-shadow:0 7px 16px rgba(8,119,111,.23) !important;
        }
        .st-key-login-card [data-testid="stBaseButton-secondary"] {
            min-height:46px;
            border:1px solid #b9d7d3 !important;
            border-radius:11px !important;
            background:#f6fbfa !important;
            color:#17645e !important;
            box-shadow:none !important;
            font-weight:620;
        }
        .st-key-login-card [data-testid="stBaseButton-secondary"] * {
            color:#17645e !important;
        }
        .st-key-login-card [data-testid="stBaseButton-secondary"]:hover {
            border-color:#83b9b2 !important;
            background:#edf7f5 !important;
        }
        .st-key-login-card [data-testid="stBaseButton-tertiary"] {
            min-height:32px !important;
            padding:0 !important;
            color:#17645e !important;
            font-weight:600;
        }
        .st-key-login-card button:focus-visible {
            outline:3px solid #347f79 !important;
            outline-offset:3px;
        }
        .lp-login-divider {
            display:flex;
            align-items:center;
            gap:12px;
            margin:7px 0 5px;
            color:#71858b;
            font-size:.85rem;
        }
        .lp-login-divider:before, .lp-login-divider:after {
            content:"";
            flex:1;
            height:1px;
            background:#e2ecea;
        }
        @media(max-width:600px) {
            [data-testid="stMainBlockContainer"] {
                min-height:100vh !important;
                padding:20px 14px !important;
            }
            .st-key-login-card {
                padding:32px 24px 27px;
                border-radius:17px;
            }
            .lp-login-brand { margin-bottom:25px; }
            .lp-login-title { font-size:1.85rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(
    title: str,
    purpose: str = "",
    eyebrow: str = "AARAMBH BANK  /  LOANPILOT",
) -> None:
    """Render a branded section label, page title, and one-line purpose."""
    st.markdown(f'<div class="lp-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    if purpose:
        st.markdown(f'<div class="lp-subtitle">{purpose}</div>', unsafe_allow_html=True)


def format_datetime(value: object) -> str:
    """Format ISO timestamps as a short local-style date and 12-hour time."""
    from datetime import datetime

    if value is None or str(value).strip().casefold() in {
        "",
        "nan",
        "nat",
        "none",
        "<na>",
    }:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%d %b %Y, %I:%M %p").replace(" 0", " ")


def render_kpi_card(label: str, value: str) -> None:
    """Render a compact KPI card; available for later phases."""
    st.markdown(
        '<div class="loanpilot-kpi">'
        f'<div class="loanpilot-kpi-label">{label}</div>'
        f'<div class="loanpilot-kpi-value">{value}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_placeholder(title: str, purpose: str, phase: int) -> None:
    """Render the shared shell for a not-yet-implemented page."""
    render_disclaimer()
    render_header(title, purpose)
    st.markdown(
        f"{implementation_badge('simulated')} "
        f"{implementation_badge('planned')}",
        unsafe_allow_html=True,
    )
    st.caption(f"Built in phase {phase}")
