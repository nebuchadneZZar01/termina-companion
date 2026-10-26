"""The Majora's Mask theme CSS and injection."""

from __future__ import annotations

import streamlit as st

_THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=Inter:wght@400;500;600&display=swap');

:root {
  --tc-bg: #0e1126;
  --tc-surface: #141836;
  --tc-card: #1b2046;
  --tc-border: #2a2f5c;
  --tc-border-strong: #4a4f80;
  --tc-gold: #e0b252;
  --tc-teal: #5fd1c4;
  --tc-red: #e5684f;
  --tc-text: #e8e6f2;
  --tc-muted: #a9a6c4;
  --tc-item: #ffae6b;
  --tc-mask: #c9b6ff;
  --tc-place: #8ec5ff;
  --tc-place-line: #4a6a99;
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
  font-family: Inter, system-ui, sans-serif;
}
.stApp {
  background: radial-gradient(circle at 20% 0%, #171c3a 0%, #0e1126 45%, #0b0e1f 100%);
  color: var(--tc-text);
}
[data-testid="stMainBlockContainer"] {
  padding-top: 1.25rem !important;
}
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stExpandSidebarButton"] {
  visibility: visible !important;
  position: relative;
  top: 26px;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid var(--tc-border-strong);
  border-radius: 8px;
  background-color: transparent;
  color: var(--tc-muted);
}
[data-testid="stExpandSidebarButton"]:hover { color: var(--tc-gold); }

h1, h2, h3, h4, h5, h6 {
  font-family: Cinzel, serif !important;
  color: var(--tc-gold);
  letter-spacing: 0.02em;
}
[data-testid="stCaptionContainer"], .stCaption { color: var(--tc-muted); }

[data-testid="stSidebar"] {
  width: 360px !important;
  min-width: 360px !important;
  max-width: 360px !important;
  background: var(--tc-surface);
  border-right: 1px solid var(--tc-border);
}
[data-testid="stSidebar"][aria-expanded="false"] {
  width: 0 !important;
  min-width: 0 !important;
  max-width: 0 !important;
  transform: translateX(-360px) !important;
  overflow: hidden !important;
}
[data-testid="stSidebarContent"] {
  width: 360px !important;
  background: transparent;
}
[data-testid="stSidebarUserContent"] {
  padding: 1.25rem 1.1rem 2rem;
}
[data-testid="stSidebarHeader"] {
  display: flex;
  justify-content: flex-end;
  position: absolute;
  top: 26px;
  right: 12px;
  padding: 0;
  z-index: 3;
}
[data-testid="stSidebarCollapseButton"] {
  display: inline-flex !important;
  visibility: visible !important;
}
[data-testid="stSidebarCollapseButton"] button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  visibility: visible !important;
  border: 1px solid var(--tc-border-strong);
  border-radius: 8px;
  background-color: transparent;
  color: var(--tc-muted);
}
[data-testid="stSidebarCollapseButton"] button:hover,
[data-testid="stExpandSidebarButton"]:hover {
  border-color: var(--tc-gold);
}
[data-testid="stSidebarCollapseButton"] button:focus-visible,
[data-testid="stExpandSidebarButton"]:focus-visible {
  outline: 2px solid var(--tc-gold);
  outline-offset: 2px;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown p { color: var(--tc-muted); }

[data-testid="stButton"] button {
  border-radius: 10px;
  border: 1px solid var(--tc-border-strong);
  background: transparent;
  color: var(--tc-text);
  font-family: Inter, sans-serif;
  font-weight: 500;
}
[data-testid="stButton"] button:hover {
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}
[data-testid="stButton"] button[kind="primary"] {
  background: var(--tc-gold);
  border-color: var(--tc-gold);
  color: #1a1630;
  font-family: Cinzel, serif;
  font-weight: 700;
}
[data-testid="stButton"] button[kind="primary"]:hover {
  background: #efc46e;
  border-color: #efc46e;
  color: #1a1630;
}
.st-key-goal_row [data-testid="stButton"] button[kind="primary"],
.st-key-goal_row [data-testid="stButton"] button[kind="primary"] * {
  font-family: Cinzel, serif !important;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.st-key-goal_row [data-testid="stWidgetLabel"],
.st-key-goal_row [data-testid="stWidgetLabel"] p {
  color: var(--tc-muted);
  font-family: Inter, sans-serif;
  font-size: 13px;
  font-weight: 400;
}

[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stTimeInput"] input,
[data-testid="stDateInput"] input {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  color: var(--tc-text);
}
[data-testid="stTextArea"] textarea {
  background: var(--tc-surface);
  border-radius: 10px;
  padding: 14px 16px;
  font-size: 16px;
}
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] [role="combobox"] {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  color: var(--tc-text);
}
[data-testid="stMultiSelectTagsContainer"] {
  background: var(--tc-bg);
  border: 1px solid var(--tc-border);
  border-radius: 8px;
  padding: 4px 6px;
}
[data-testid="stMultiSelectTagsContainer"] [data-tag] {
  background: #2b2540;
  border: 1px solid var(--tc-gold);
  border-radius: 999px;
  color: var(--tc-gold);
  font-size: 13px;
}
[data-testid="stMultiSelect"] input { color: var(--tc-text); }

[data-testid="stTabs"] [role="tablist"] {
  gap: 26px;
  border-bottom: 1px solid var(--tc-border);
  background: transparent;
}
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tablist"] button,
[data-testid="stTabs"] [data-testid="stTab"] *,
[data-testid="stTabs"] [role="tab"] *,
[data-testid="stTabs"] [data-baseweb="tab"] *,
[data-testid="stTabs"] [role="tablist"] button * {
  font-family: Cinzel, serif !important;
  font-weight: 500;
  font-size: 14px;
  letter-spacing: 0.02em;
}
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [data-baseweb="tab"],
[data-testid="stTabs"] [role="tablist"] button {
  color: var(--tc-muted);
  background: transparent;
  padding: 8px 2px;
}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"],
[data-testid="stTabs"] [role="tab"][aria-selected="true"],
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"],
[data-testid="stTabs"] [role="tablist"] button[aria-selected="true"] {
  color: var(--tc-gold);
  border-bottom: 2px solid var(--tc-gold);
  font-weight: 700;
}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] *,
[data-testid="stTabs"] [role="tab"][aria-selected="true"] *,
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] *,
[data-testid="stTabs"] [role="tablist"] button[aria-selected="true"] * {
  color: var(--tc-gold);
  border-bottom: 0;
  font-weight: 700;
}

[data-testid="stButtonGroup"] [data-variant="pills"] {
  border-radius: 999px;
  border: 1px solid var(--tc-border-strong);
  background: transparent;
  color: var(--tc-muted);
  font-size: 13px;
  padding: 4px 12px;
}
[data-testid="stButtonGroup"] [data-variant="pills"]:hover {
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}
[data-testid="stButtonGroup"] [data-variant="pills"][data-selected],
[data-testid="stButtonGroup"] [data-variant="pills"][aria-selected="true"],
[data-testid="stButtonGroup"] [data-variant="pills"][aria-pressed="true"] {
  background: #2b2540;
  border-color: var(--tc-gold);
  color: var(--tc-gold);
}

[data-testid="stExpander"],
[data-testid="stExpander"] details {
  background: var(--tc-card);
  border: 1px solid var(--tc-border);
  border-radius: 12px;
}
[data-testid="stExpander"] summary {
  font-family: Cinzel, serif;
  color: var(--tc-text);
}
[data-testid="stMetric"] {
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  border-radius: 12px;
  padding: 16px 18px;
}
[data-testid="stMetricLabel"] { color: var(--tc-muted); font-size: 13px; }
[data-testid="stMetricValue"] {
  font-family: Cinzel, serif;
  font-weight: 700;
  font-size: 34px;
  line-height: 1.2;
  color: var(--tc-gold);
}
[data-testid="stTable"] table {
  border-collapse: collapse;
  background: var(--tc-card);
}
[data-testid="stTable"] thead th {
  padding: 12px 18px;
  border: 0;
  border-bottom: 1px solid var(--tc-border);
  color: var(--tc-muted);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.06em;
}
[data-testid="stTable"] tbody td {
  padding: 12px 18px;
  border-top: 1px solid var(--tc-border);
}
[data-testid="stMarkdownContainer"] code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: var(--tc-teal);
  background: var(--tc-bg);
  padding: 1px 6px;
  border-radius: 4px;
}
.st-key-eval_actions [data-testid="stButton"] button[kind="secondary"] {
  color: var(--tc-muted);
}
.st-key-evaluation_tab [data-testid="stMarkdownContainer"]:has(> [class^="tc-"]) {
  margin-bottom: 0 !important;
}
[data-testid="stAlert"] {
  border-radius: 12px;
  border: 1px solid var(--tc-border);
  background: var(--tc-card);
}
[data-testid="stAlertContainer"] {
  background: var(--tc-card) !important;
  border: 1px solid var(--tc-border) !important;
  border-radius: 12px;
}
[data-testid="stToast"] {
  background: var(--tc-card) !important;
  border: 1px solid var(--tc-border-strong) !important;
  border-radius: 12px !important;
  box-shadow: 0 18px 40px rgba(4, 6, 18, 0.55) !important;
  color: var(--tc-text);
  filter: none !important;
  padding: 14px 16px;
  font-family: Inter, sans-serif;
}
[data-testid="stToastText"] {
  color: var(--tc-text);
  font-size: 13px;
  line-height: 1.45;
}
[data-testid="stToastDynamicIcon"] {
  font-size: 18px;
  line-height: 1;
}
[data-testid="stToast"] button[aria-label="Close"] {
  color: var(--tc-muted);
}
[data-testid="stToast"] button[aria-label="Close"]:hover {
  color: var(--tc-gold);
}
[data-testid="stToastViewButton"] {
  color: var(--tc-teal);
  font-size: 12px;
}
[data-testid="stToastViewButton"]:hover {
  color: var(--tc-gold);
}

.tc-brand { padding-right: 44px; }
.tc-brand-name {
  font-family: Cinzel, serif;
  font-weight: 700;
  font-size: 22px;
  letter-spacing: 0.04em;
  color: var(--tc-gold);
}
.tc-brand-tag { color: var(--tc-muted); font-size: 13px; }

.tc-side-card {
  background: var(--tc-card);
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  padding: 14px 16px 6px;
}
.tc-side-card + .tc-side-card { margin-top: 20px; }
.tc-side-card-title {
  font-family: Cinzel, serif;
  font-size: 13px;
  letter-spacing: 0.1em;
  color: var(--tc-muted);
  text-transform: uppercase;
  margin-bottom: 8px;
}
.tc-side-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-top: 1px solid var(--tc-border);
}
.tc-side-row-label { font-size: 13px; color: var(--tc-muted); }
.tc-side-code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: var(--tc-teal);
  background: var(--tc-bg);
  border-radius: 4px;
  padding: 2px 8px;
}
.tc-side-code-prefix { color: #6f6c91; }
.tc-side-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--tc-teal);
  color: var(--tc-teal);
  font-size: 12px;
}
.tc-side-pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--tc-teal);
}
.tc-side-pill-off { border-color: var(--tc-muted); color: var(--tc-muted); }
.tc-side-pill-off .tc-side-pill-dot { background: var(--tc-muted); }
.tc-side-link { color: #6db3ff; font-size: 13px; text-decoration: none; }
.tc-side-row-stack { display: block; }
.tc-side-row-stack .tc-side-code { display: block; margin-top: 4px; overflow-wrap: anywhere; }

.tc-time-card {
  background: var(--tc-card);
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  padding: 12px 14px;
  margin: 4px 0 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tc-time-head { display: flex; justify-content: space-between; align-items: baseline; }
.tc-time-label {
  font-family: Cinzel, serif;
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--tc-muted);
}
.tc-time-value { font-family: Cinzel, serif; font-size: 26px; color: var(--tc-gold); }
.tc-time-value small { font-size: 13px; color: var(--tc-teal); }
.tc-daybar { display: flex; gap: 6px; }
.tc-daybar span { flex: 1; height: 8px; border-radius: 4px; background: var(--tc-border); }
.tc-daybar span.on { background: var(--tc-gold); }
.tc-daylabels {
  display: flex;
  justify-content: space-between;
  color: var(--tc-muted);
  font-size: 12px;
}
.tc-daylabels .on { color: var(--tc-gold); font-weight: 600; }
.tc-time-caption { color: var(--tc-muted); font-size: 12px; }

.tc-fairy { display: flex; gap: 10px; align-items: center; }
.tc-fairy-figure { position: relative; width: 96px; height: 72px; flex: none; }
.tc-fairy-wings { position: absolute; inset: 0; width: 96px; height: 72px; }
.tc-fairy-orb {
  position: absolute;
  left: 30px;
  top: 26px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, #ffffff 0%, #fff3a0 30%,
    #f5d142 62%, rgba(245, 209, 66, 0.15) 100%);
  box-shadow: 0 0 22px 8px rgba(245, 209, 66, 0.5);
}
.tc-fairy-bubble {
  flex: 1;
  padding: 14px 18px;
  border-radius: 4px 16px 16px 16px;
  background: #12302f;
  border: 1px solid var(--tc-teal);
}
.tc-fairy-name {
  font-family: Cinzel, serif;
  font-weight: 700;
  color: var(--tc-teal);
  font-size: 14px;
  letter-spacing: 0.08em;
}
.tc-fairy-text { color: var(--tc-text); }

.tc-panel {
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  padding: 14px 16px;
  margin: 6px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tc-panel-title {
  font-family: Cinzel, serif;
  font-size: 13px;
  letter-spacing: 0.1em;
  color: var(--tc-muted);
}
.tc-live-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0 12px;
  color: var(--tc-gold);
  font-family: Cinzel, serif;
  font-size: 15px;
}
.tc-live-dot {
  width: 9px;
  height: 9px;
  flex: none;
  border-radius: 50%;
  background: var(--tc-gold);
  animation: tc-pulse 1.6s ease-out infinite;
}
@keyframes tc-pulse {
  0% { box-shadow: 0 0 0 0 rgba(245, 209, 66, 0.5); }
  70% { box-shadow: 0 0 0 8px rgba(245, 209, 66, 0); }
  100% { box-shadow: 0 0 0 0 rgba(245, 209, 66, 0); }
}
.tc-registry-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.tc-registry-hint { font-size: 12px; color: var(--tc-muted); margin-top: -8px; }
.tc-registry { display: flex; flex-direction: column; gap: 8px; }
.tc-reg {
  border: 1px solid var(--tc-border);
  border-radius: 10px;
  background: var(--tc-card);
  overflow: hidden;
}
.tc-reg.bad { border-color: rgba(224, 90, 90, 0.55); }
.tc-reg.running { border-color: rgba(245, 209, 66, 0.55); }
.tc-reg > summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  list-style: none;
  cursor: pointer;
}
.tc-reg > summary::-webkit-details-marker { display: none; }
.tc-reg[open] > summary { border-bottom: 1px solid var(--tc-border); }
.tc-reg-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--tc-teal);
}
.tc-reg.bad .tc-reg-dot { background: var(--tc-red); }
.tc-reg.running .tc-reg-dot {
  background: var(--tc-gold);
  animation: tc-pulse 1.6s ease-out infinite;
}
.tc-reg-main { flex: 1; min-width: 0; }
.tc-reg-name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-weight: 600;
}
.tc-reg-sub { font-size: 12px; color: var(--tc-muted); }
.tc-reg-engine,
.tc-reg-attempt {
  padding: 1px 8px;
  border-radius: 5px;
  border: 1px solid var(--tc-border-strong);
  color: var(--tc-muted);
  font-size: 11px;
  font-weight: 500;
}
.tc-reg-attempt { border-color: var(--tc-gold); color: var(--tc-gold); }
.tc-reg-right { flex: none; max-width: 52%; text-align: right; }
.tc-reg-result {
  overflow: hidden;
  font-size: 12px;
  color: var(--tc-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tc-reg.running .tc-reg-result { color: var(--tc-gold); }
.tc-reg-time { font-size: 11px; color: var(--tc-muted); }
.tc-chev { color: var(--tc-muted); transition: transform 0.15s; }
.tc-reg[open] .tc-chev { transform: rotate(180deg); }
.tc-reg-body { padding: 12px 14px 14px; font-size: 13px; }
.tc-reg-body ul { margin: 0; padding-left: 18px; }
.tc-reg-body li { margin: 3px 0; }
.tc-reg-activity { color: var(--tc-muted); }
.tc-reg-activity ul {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}
.tc-reg-activity li { color: var(--tc-muted); }
.tc-reg-activity li.current { color: var(--tc-gold); }
.tc-reg-activity .tc-ev { display: inline-block; width: 16px; }
.tc-reg-kv {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--tc-muted);
}
.tc-reg-issues-box {
  padding: 12px 14px;
  border-radius: 10px;
  background: #2a1a24;
  border: 1px solid var(--tc-red);
}
.tc-reg-issue-head { color: #f0b5a8; margin-bottom: 6px; }
.tc-reg-stop { color: var(--tc-muted); }
.tc-problems-pill {
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--tc-red);
  background: rgba(224, 90, 90, 0.12);
  color: var(--tc-red);
  font-size: 12px;
  white-space: nowrap;
}

.tc-badges { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.tc-badges-label { font-size: 12px; color: var(--tc-muted); }
.tc-badge {
  padding: 2px 10px;
  border-radius: 6px;
  border: 1px solid var(--tc-teal);
  color: var(--tc-teal);
  font-size: 12px;
}
.tc-badge.gold { border-color: var(--tc-gold); color: var(--tc-gold); }
.tc-badge.red { border-color: var(--tc-red); color: var(--tc-red); }
.tc-badges span:last-child { font-size: 12px; color: var(--tc-muted); }

.tc-verdict {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 12px;
  background: #12302f;
  border: 1px solid var(--tc-teal);
}
.tc-verdict.fail { background: #2a1a24; border-color: var(--tc-red); }
.tc-verdict-icon { font-size: 22px; color: var(--tc-teal); }
.tc-verdict.fail .tc-verdict-icon { color: var(--tc-red); }
.tc-verdict-title {
  font-family: Cinzel, serif;
  font-weight: 700;
  color: var(--tc-teal);
  font-size: 17px;
}
.tc-verdict.fail .tc-verdict-title { color: var(--tc-red); }
.tc-verdict-body { font-size: 13px; color: #b9e5e0; }
.tc-verdict.fail .tc-verdict-body { color: #f0b5a8; }

.tc-issues-table { display: flex; flex-direction: column; }
.tc-issue-row {
  display: grid;
  grid-template-columns: 86px 108px 80px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid var(--tc-border);
  font-size: 13px;
}
.tc-issue-head {
  padding: 4px 0;
  border-top: 0;
  color: var(--tc-muted);
  font-size: 11px;
  letter-spacing: 0.06em;
}
.tc-sev-tag,
.tc-kind-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
}
.tc-sev-tag.error { background: #3a1c26; color: #f0757a; }
.tc-sev-tag.warning { background: #3a3320; color: var(--tc-gold); }
.tc-kind-tag { background: #14305a; color: #7ab8ff; }
.tc-issue-step { font-weight: 600; }
.tc-problems-panel {
  padding: 16px 20px;
  border-radius: 14px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
}
.tc-problems-panel .tc-issues-table { margin-top: 6px; }
.tc-missing-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tc-missing-chip {
  padding: 2px 10px;
  border-radius: 6px;
  border: 1px solid var(--tc-red);
  background: #1b2046;
  color: #f0b5a8;
  font-size: 12px;
}

.tc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 56px 24px;
  border-radius: 14px;
  border: 1px dashed var(--tc-border-strong);
  background: var(--tc-surface);
  text-align: center;
}
.tc-empty-icon { color: var(--tc-gold); }
.tc-empty-title {
  font-family: Cinzel, serif;
  font-weight: 700;
  font-size: 20px;
  color: var(--tc-gold);
}
.tc-empty-body { max-width: 460px; color: var(--tc-muted); }

.tc-timeline { display: flex; flex-direction: column; }
.tc-step { display: flex; gap: 18px; }
.tc-step-time { width: 92px; flex: none; text-align: right; padding-top: 14px; }
.tc-step-hour { font-family: Cinzel, serif; font-weight: 700; }
.tc-step-day { font-size: 12px; color: var(--tc-muted); }
.tc-step-rail {
  width: 14px;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.tc-dot {
  width: 12px;
  height: 12px;
  margin-top: 18px;
  border-radius: 50%;
  background: var(--tc-gold);
  flex: none;
}
.tc-line { flex: 1; width: 2px; background: var(--tc-border); min-height: 16px; }
.tc-step:last-child .tc-line { display: none; }
.tc-step-card {
  flex: 1;
  margin-bottom: 12px;
  padding: 14px 18px;
  border-radius: 12px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
}
.tc-step-title { font-weight: 600; }
.tc-step-meta { font-size: 13px; color: var(--tc-muted); }
.tc-step.last .tc-step-hour { color: var(--tc-red); }
.tc-step.last .tc-dot { background: var(--tc-red); }
.tc-step.last .tc-step-card { background: #2a1a24; border-color: var(--tc-red); }
.tc-step.last .tc-step-meta { color: #f0b5a8; }
.tc-step.last.ok .tc-step-hour { color: var(--tc-teal); }
.tc-step.last.ok .tc-dot { background: var(--tc-teal); }
.tc-step.last.ok .tc-step-card {
  background: #12302f;
  border-color: var(--tc-teal);
}
.tc-step.last.ok .tc-step-meta { color: #b9e5e0; }
.tc-step.bad .tc-step-hour { color: var(--tc-red); }
.tc-step.bad .tc-dot { background: var(--tc-red); }
.tc-step.bad .tc-step-card { background: #2a1a24; border-color: var(--tc-red); }
.tc-step.bad .tc-step-meta { color: #f0b5a8; }

.tc-subhead {
  font-family: Cinzel, serif;
  font-size: 18px;
  color: var(--tc-gold);
  margin: 6px 0 2px;
}
.tc-detail-list { display: flex; flex-direction: column; gap: 12px; }
.tc-detail-card {
  padding: 14px 18px;
  border-radius: 12px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tc-detail-title { font-weight: 600; }
.tc-detail-line { font-size: 14px; }
.tc-detail-muted { color: var(--tc-muted); font-size: 13px; }
.tc-code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: var(--tc-teal);
  background: var(--tc-bg);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}
.tc-item {
  font-family: Inter, sans-serif;
  font-weight: 600;
  color: var(--tc-item);
  white-space: nowrap;
}
.tc-item::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 3px;
  margin-right: 6px;
  vertical-align: 1px;
  background: currentColor;
  transform: rotate(45deg);
}
.tc-mask {
  font-family: Cinzel, serif;
  font-weight: 700;
  color: var(--tc-mask);
  letter-spacing: 0.02em;
}
.tc-place {
  font-family: Inter, sans-serif;
  font-weight: 600;
  font-variant: small-caps;
  letter-spacing: 0.03em;
  color: var(--tc-place);
  text-decoration: underline dotted var(--tc-place-line);
  text-underline-offset: 3px;
}
.tc-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--tc-border);
  border-radius: 14px;
  background: var(--tc-card);
}
.tc-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.tc-table th {
  padding: 12px 18px;
  text-align: left;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.06em;
  color: var(--tc-muted);
  white-space: nowrap;
}
.tc-table td { padding: 12px 18px; border-top: 1px solid var(--tc-border); }
.tc-table code { white-space: normal; overflow-wrap: anywhere; }
.tc-table th.num, .tc-table td.num { text-align: right; }
.tc-cell-pass { color: var(--tc-teal); font-weight: 600; }
.tc-cell-fail { color: var(--tc-red); font-weight: 600; }
.tc-cell-warn { color: var(--tc-gold); }
.tc-cell-muted { color: var(--tc-muted); }
.tc-eval-error { color: var(--tc-red); }
.tc-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 12px;
  background: #12302f;
  border: 1px solid var(--tc-teal);
  color: #b9e5e0;
  font-size: 14px;
}
.tc-banner-icon { color: var(--tc-teal); font-weight: 700; }
.tc-failure-panel {
  padding: 14px 18px;
  border-radius: 12px;
  background: var(--tc-surface);
  border: 1px solid var(--tc-border);
}
.tc-failure-label {
  margin-bottom: 8px;
  color: var(--tc-muted);
  font-size: 13px;
}
.tc-failure-list {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 16px;
}
.tc-failure-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  color: var(--tc-text);
  font-size: 13px;
}
.tc-failure-chip b {
  font-family: Cinzel, serif;
  font-size: 18px;
  line-height: 1;
  color: var(--tc-gold);
}
.tc-failure-empty {
  font-family: Cinzel, serif;
  font-size: 18px;
  color: var(--tc-gold);
}

@media (max-width: 700px) {
  .tc-step-time { width: 64px; }
}
"""


def _html_block(markup: str) -> None:
    """Draw trusted HTML markup into the page."""
    st.markdown(markup, unsafe_allow_html=True)


def _inject_styles() -> None:
    """Install the Majora's Mask theme once per script run."""
    _html_block(f"<style>{_THEME_CSS}</style>")
