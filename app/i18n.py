"""Minimal i18n — two languages, one dict, one function."""

from __future__ import annotations

import streamlit as st

# -- Game-entity display names: English → Italian ---------------------------
# Covers locations, NPCs, masks, items, quests, objective titles/descriptions,
# and events from the mock knowledge vertical slice.

_DISPLAY_IT: dict[str, str] = {
    # objective titles (longest first helps readability, tr() sorts at load)
    "Talk to the Bombers' leader in North Clock Town": (
        "Parla con il leader dei Bombers a Nord Clock Town"
    ),
    "Locate the hidden hideout behind the clock tower": (
        "Trova il nascondiglio nascosto dietro la torre dell'orologio"
    ),
    "Retrieve Kafei's letter from the mailbox": (
        "Recupera la lettera di Kafei dalla cassetta postale"
    ),
    "Give the letter to Kafei at the Curiosity Shop": (
        "Consegna la lettera a Kafei al Negozio di Curiosità"
    ),
    "Reunite Anju and Kafei at the Stockpot Inn": ("Riunisci Anju e Kafei alla Locanda Stockpot"),
    "Talk to Anju at the Stockpot Inn": ("Parla con Anju alla Locanda Stockpot"),
    # objective descriptions
    "Learn about her missing fiancé Kafei.": ("Scopri sul suo fidanzato scomparso Kafei."),
    "Kafei left a letter for you behind the Post Office.": (
        "Kafei ha lasciato una lettera per te dall'Ufficio Postale."
    ),
    "Kafei is hiding out in the Curiosity Shop basement.": (
        "Kafei si nasconde nella cantina del Negozio di Curiosità."
    ),
    "Bring everyone together before the dawn of the Third Day.": (
        "Riunisci tutti prima dell'alba del Terzo Giorno."
    ),
    "The kid gang is suspicious of strangers.": (
        "La gang di ragazzini è sospettosa degli estranei."
    ),
    "The hideout entrance is marked by a odd drawing.": (
        "L'ingresso del nascondiglio è segnato da un disegno strano."
    ),
    # event names
    "Kafei's letter is delivered": ("La lettera di Kafei viene consegnata"),
    "Anju and Kafei reunite": "Anju e Kafei si riuniscono",
    "Bombers gather at the hideout": ("I Bombers si radunano al nascondiglio"),
    # quest names
    "Bombers' Secret Society": "Società Segreta dei Bombers",
    "Bombers' Leader": "Leader dei Bombers",
    "Bomber's Notebook": "Taccuino dei Bombers",
    # locations
    "South Clock Town": "Sud Clock Town",
    "North Clock Town": "Nord Clock Town",
    "West Clock Town": "Ovest Clock Town",
    "East Clock Town": "Est Clock Town",
    "Market District": "Distretto del Mercato",
    "Stockpot Inn": "Locanda Stockpot",
    "Curiosity Shop": "Negozio di Curiosità",
    "Post Office": "Ufficio Postale",
    # masks / items
    "Deku Mask": "Maschera Deku",
    "Goron Mask": "Maschera Goron",
    "Zora Mask": "Maschera Zora",
    "Kafei's Mask": "Maschera di Kafei",
    "Kafei's Letter": "Lettera di Kafei",
    # NPCs / quests (short names)
    "Anju and Kafei": "Anju e Kafei",
    "Postman": "Postino",
    # time label inside agent outputs and plan windows
    "Day": "Giorno",
}

_DISPLAY_KEYS_IT = sorted(_DISPLAY_IT, key=len, reverse=True)

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Termina Companion",
        "subtitle": "Temporal planning guide for Majora's Mask",
        "language": "Language",
        # input panels
        "game_state": "Game State",
        "game_state_caption": "Where, when and what you own right now.",
        "goal": "Goal",
        "goal_caption": "What you want to achieve, in one phrase.",
        "day": "Day (1-3)",
        "time": "In-game time",
        "location": "Location",
        "masks": "Masks you own",
        "masks_help": "Select the masks you carry. Selected = owned.",
        "inventory": "Inventory",
        "inventory_help": "Select the items you carry. Selected = you have it.",
        "quest_progress": "Quest Progress",
        "quest_progress_help": ("Select quests already completed \u2014 they\u2019ll be skipped."),
        "legend": "\u2713 Selected = owned / completed",
        "goal_placeholder": "What do you want to do?",
        "generate_plan": "\u2728 Plan My Quest",
        "generate_plan_caption": "Builds the plan from your state and goal.",
        "info_edit_state": ("Set your state and goal, then press **Plan My Quest**."),
        "planning": "Planning...",
        # output
        "your_plan": "Your Plan",
        "plan_valid": "\u2713 Plan valid",
        "plan_not_valid": "\u2717 Plan not valid \u2014 check the issues below",
        "agents_line": "\u2713 {count}/4 agents completed",
        "agents_detail": "Agent report",
        "agent_state": "State Agent",
        "agent_state_desc": "Canonicalizes your game state.",
        "agent_knowledge": "Knowledge Agent",
        "agent_knowledge_desc": "Retrieves the relevant game knowledge.",
        "agent_planning": "Planning Agent",
        "agent_planning_desc": "Builds the temporal plan.",
        "agent_critic": "Critic Agent",
        "agent_critic_desc": "Checks the plan's feasibility.",
        "agent_done": "done",
        "agent_failed": "failed",
        "no_plan": "No plan produced.",
        "window_label": "Window",
        "needs": "Needs",
        "depends_on": "Depends on step(s) {deps}",
        "step_n": "Step {n}",
        "attempts": "Attempts: {n} / max {max}",
        "replan_gave_up": "Reached the attempt limit ({max}) \u2014 showing the last attempt.",
        "no_replan": "First attempt \u2014 no replan needed.",
        # trace content
        "understood": "What the system understood",
        "understood_caption": (
            "The canonicalized reading of your state \u2014 what the planner worked from."
        ),
        "trace_attempts": "Planning attempts",
        "trace_attempts_caption": "How many times the planner had to re-run to get a valid plan.",
        "validation_caption": (
            "Issues found by the critic when checking the plan\u2019s feasibility."
        ),
        "sev_error": "error",
        "sev_warning": "warning",
        "sev_legend_error": "blocks the plan",
        "sev_legend_warning": "allowable but flagged",
        "kind_empty": "empty",
        "kind_sequence": "sequence",
        "kind_time": "time",
        "kind_npc": "npc",
        "kind_item": "item",
        "kind_objective": "objective",
        "kind_location": "location",
        "no_issues": "No issues.",
        "validation_details": "Validation details",
        "problems": "Problems",
        "legend_severity": "Legend",
        "trace_where": "Where:",
        "trace_when": "When:",
        "trace_items": "Items:",
        "trace_masks": "Masks:",
        "trace_none": "none",
        # source cards
        "source_when": "When:",
        "source_where": "Where:",
        "source_npc": "NPC:",
        "source_active": "active:",
        "source_event": "Event:",
        "source_needs": "Needs:",
        "source_after": "Comes after:",
        "no_sources": "No relevant sources found.",
        # tabs
        "tab_why": "Why this plan?",
        "tab_why_caption": (
            "Why the plan looks like this: for each step, its time window, "
            "the items it needs, and which earlier steps it depends on."
        ),
        "tab_sources": "Game sources",
        "tab_sources_caption": (
            "What the Knowledge Agent pulled from the game database for your goal: "
            "the objectives, NPCs and events used to build the plan. "
            "No RAG yet \u2014 retrieval is keyword matching; RAG slots into "
            "KnowledgeBase.retrieve() later."
        ),
        "tab_trace": "How it was planned",
        "tab_trace_caption": (
            "The technical behind-the-scenes: what the system understood, "
            "how many planning attempts it made, and the validation results."
        ),
        # trace sections
        "trace_understood": "What the system understood",
        "trace_understood_caption": (
            "The canonicalized reading of your state \u2014 this is what the planner worked from."
        ),
        "trace_validation_caption": ("Issues the critic found when checking feasibility."),
    },
    "it": {
        "title": "Termina Companion",
        "subtitle": "Guida alla pianificazione temporale per Majora\u2019s Mask",
        "language": "Lingua",
        # input panels
        "game_state": "Stato di Gioco",
        "game_state_caption": "Dove, quando e cosa possiedi in questo momento.",
        "goal": "Obiettivo",
        "goal_caption": "Cosa vuoi ottenere, in una frase.",
        "day": "Giorno (1-3)",
        "time": "Ora nel gioco",
        "location": "Posizione",
        "masks": "Maschere in tuo possesso",
        "masks_help": ("Seleziona le maschere che porti. Selezionato = in possesso."),
        "inventory": "Inventario",
        "inventory_help": ("Seleziona gli oggetti che porti con te. Selezionato = lo possiedi."),
        "quest_progress": "Missioni completate",
        "quest_progress_help": (
            "Seleziona le missioni gi\u00e0 completate \u2014 verranno saltate."
        ),
        "legend": "\u2713 Selezionato = in possesso / completata",
        "goal_placeholder": "Cosa vuoi fare?",
        "generate_plan": "\u2728 Pianifica la mia missione",
        "generate_plan_caption": "Genera il piano dal tuo stato e obiettivo.",
        "info_edit_state": ("Imposta stato e obiettivo, poi premi **Pianifica la mia missione**."),
        "planning": "Pianificazione...",
        # output
        "your_plan": "Il Tuo Piano",
        "plan_valid": "\u2713 Piano valido",
        "plan_not_valid": ("\u2717 Piano non valido \u2014 controlla i problemi qui sotto"),
        "agents_line": "\u2713 {count}/4 agenti completati",
        "agents_detail": "Report agenti",
        "agent_state": "Agente di Stato",
        "agent_state_desc": "Canonicalizza il tuo stato di gioco.",
        "agent_knowledge": "Agente della Conoscenza",
        "agent_knowledge_desc": "Recupera le conoscenze di gioco rilevanti.",
        "agent_planning": "Agente di Pianificazione",
        "agent_planning_desc": "Costruisce il piano temporale.",
        "agent_critic": "Agente Critico",
        "agent_critic_desc": "Verifica la fattibilit\u00e0 del piano.",
        "agent_done": "completato",
        "agent_failed": "fallito",
        "no_plan": "Nessun piano generato.",
        "window_label": "Finestra",
        "needs": "Necessita",
        "depends_on": "Dipende dai passi {deps}",
        "step_n": "Passo {n}",
        "attempts": "Tentativi: {n} / max {max}",
        "replan_gave_up": (
            "Raggiunto il limite di tentativi ({max}) \u2014 mostro l\u2019ultimo tentativo."
        ),
        "no_replan": "Primo tentativo \u2014 nessuna ripianificazione necessaria.",
        # trace content
        "understood": "Cosa ha capito il sistema",
        "understood_caption": (
            "La lettura canonica del tuo stato \u2014 da qui \u00e8 partito il pianificatore."
        ),
        "trace_attempts": "Tentativi di pianificazione",
        "trace_attempts_caption": (
            "Quante volte il pianificatore ha dovuto ripetere per un piano valido."
        ),
        "validation_caption": (
            "I problemi trovati dal critico quando verifica la fattibilit\u00e0 del piano."
        ),
        "sev_error": "errore",
        "sev_warning": "avviso",
        "sev_legend_error": "blocca il piano",
        "sev_legend_warning": "consentito ma segnalato",
        "kind_empty": "vuoto",
        "kind_sequence": "sequenza",
        "kind_time": "tempo",
        "kind_npc": "npc",
        "kind_item": "oggetto",
        "kind_objective": "obiettivo",
        "kind_location": "posizione",
        "no_issues": "Nessun problema.",
        "validation_details": "Dettagli validazione",
        "problems": "Problemi",
        "legend_severity": "Legenda",
        "trace_where": "Dove:",
        "trace_when": "Quando:",
        "trace_items": "Oggetti:",
        "trace_masks": "Maschere:",
        "trace_none": "nessuno",
        # source cards
        "source_when": "Quando:",
        "source_where": "Dove:",
        "source_npc": "NPC:",
        "source_active": "attivo:",
        "source_event": "Evento:",
        "source_needs": "Serve:",
        "source_after": "Dopo:",
        "no_sources": "Nessuna fonte rilevante trovata.",
        # tabs
        "tab_why": "Perch\u00e9 questo piano?",
        "tab_why_caption": (
            "Perch\u00e9 il piano \u00e8 fatto cos\u00ec: per ogni passo, "
            "la finestra temporale, gli oggetti necessari e i passi da cui dipende."
        ),
        "tab_sources": "Fonti di gioco",
        "tab_sources_caption": (
            "Cosa l'Agente della Conoscenza ha estratto dal database di gioco "
            "per il tuo obiettivo: obiettivi, NPC ed eventi usati per costruire il piano. "
            "Nessuna RAG \u2014 il recupero \u00e8 per parole chiave; la RAG "
            "si inserir\u00e0 in KnowledgeBase.retrieve() in seguito."
        ),
        "tab_trace": "Come \u00e8 stato pianificato",
        "tab_trace_caption": (
            "Il dietro le quinte tecnico: cosa ha capito il sistema, "
            "quanti tentativi ha fatto e gli esiti della validazione."
        ),
    },
}

DEFAULT_LANG = "en"


def t(key: str, **kwargs: object) -> str:
    """Return translated string for *key* in the current session language."""
    lang = st.session_state.get("lang", DEFAULT_LANG)
    template = _STRINGS.get(lang, _STRINGS[DEFAULT_LANG]).get(key, key)
    return template.format(**kwargs) if kwargs else template


def tr(s: str) -> str:
    """Translate game-entity display names inside *s* (longest-match first)."""
    if st.session_state.get("lang", DEFAULT_LANG) == "en":
        return s
    for en in _DISPLAY_KEYS_IT:
        s = s.replace(en, _DISPLAY_IT[en])
    return s


# -- Critic validation-message templates: English → Italian ---------------
# The Critic Agent emits messages in English with entity names embedded.
# tr_msg() first swaps the fixed templates, then tr() translates entities.

_MSGS_IT: dict[str, str] = {
    "Plan has no steps.": "Il piano non ha passi.",
    "Unknown objective reference.": "Riferimento obiettivo sconosciuto.",
    " is not where ": " non \u00e8 il luogo in cui ",
    " happens.": " si svolge.",
    " falls outside the objective's slot ": " non rientra nella finestra ",
    " is unavailable during ": " non \u00e8 disponibile durante ",
    "Missing item(s): ": "Oggetti mancanti: ",
    "Depends on a step that ends after this one starts.": (
        "Dipende da un passo che termina dopo l'inizio di questo."
    ),
}

_MSG_KEYS_IT = sorted(_MSGS_IT, key=len, reverse=True)


def tr_msg(s: str) -> str:
    """Translate a critic validation message: templates first, then entities."""
    if st.session_state.get("lang", DEFAULT_LANG) == "en":
        return s
    for en in _MSG_KEYS_IT:
        s = s.replace(en, _MSGS_IT[en])
    return tr(s)
