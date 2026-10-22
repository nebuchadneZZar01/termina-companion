"""Minimal i18n — two languages, one dict, one function."""

from __future__ import annotations

import re

import streamlit as st

_CODE_SPAN_RE = re.compile(r"(`[^`]+`)")

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
    "Earn the Bomber's Notebook from the Bombers' leader": (
        "Guadagna il Taccuino del Bomber dal leader dei Bombers"
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
    "The leader gives the notebook to a member he trusts.": (
        "Il leader consegna il taccuino a un membro di cui si fida."
    ),
    # objective titles — Darmani's Spirit
    "Obtain the Goron Mask from the Happy Mask Salesman": (
        "Ottieni la Maschera Goron dal Venditore di Maschere"
    ),
    "Listen to the Goron Elder's song": "Ascolta la canzone dell'Anziano Goron",
    "Obtain the Lens of Truth at the Curiosity Shop": (
        "Ottieni la Lente della Verità al Negozio di Curiosità"
    ),
    "Speak with Darmani's ghost at the Goron Shrine": (
        "Parla con il fantasma di Darmani al Santuario Goron"
    ),
    "Learn the Goron Lullaby from Darmani": "Impara la Ninna Nanna Goron da Darmani",
    # objective titles — Mikau's Memory
    "Recover the Zora Mask from the Great Bay Coast": (
        "Recupera la Maschera Zora sulla Costa della Grande Baia"
    ),
    "Ask Tael about Mikau at Zora Hall": "Chiedi a Tael di Mikau alla Sala Zora",
    "Retrieve Mikau's eggs from Pinnacle Rock": (
        "Recupera le uova di Mikau dalla Roccia Pinnacolo"
    ),
    "Learn the Song of Opening from Mikau": ("Impara la Canzone dell'Apertura da Mikau"),
    # objective titles — Pamela's Father
    "Buy the Gibdo Mask at the Curiosity Shop": (
        "Compra la Maschera Gibdo al Negozio di Curiosità"
    ),
    "Enter the Ancient Castle of Ikana at night": ("Entra nell'Antico Castello di Ikana di notte"),
    "Free Pamela's father from the Gibdo curse": (
        "Libera il padre di Pamela dalla maledizione dei Gibdo"
    ),
    "Reunite with Pamela after freeing her father": (
        "Riunisci Pamela e suo padre dopo averlo liberato"
    ),
    # objective titles — Deku Princess Rescue
    "Receive the Deku Mask from the Happy Mask Salesman": (
        "Ricevi la Maschera Deku dal Venditore di Maschere"
    ),
    "Plead with the Deku King for the princess": ("Implora il Re Deku per la principessa"),
    "Navigate the swamp to reach Woodfall": ("Attraversa la palude per raggiungere Woodfall"),
    "Free the Deku Princess from the monkey's cage": (
        "Libera la principessa Deku dalla gabbia della scimmia"
    ),
    # objective titles — Romani Ranch
    "Buy the Powder Keg for the alien defense": (
        "Compra la Botte di Polvere per la difesa dagli alieni"
    ),
    "Help Romani practice shooting aliens at the ranch": (
        "Aiuta Romani ad allenarsi a sparare agli alieni nella fattoria"
    ),
    "Defend the ranch from the alien invasion": ("Difendi la fattoria dall'invasione aliena"),
    "Ride with Cremia to deliver milk to Clock Town": (
        "Viaggia con Cremia per consegnare il latte a Clock Town"
    ),
    # objective titles — Land Title Deed Chain
    "Receive the Swamp Title Deed in the Southern Swamp": (
        "Ricevi la Carta di Proprietà della Palude nella Palude del Sud"
    ),
    "Deliver the Swamp Title Deed to the Goron Shrine": (
        "Consegna la Carta di Proprietà della Palude al Santuario Goron"
    ),
    "Deliver the Mountain Title Deed to Zora Hall": (
        "Consegna la Carta di Proprietà della Montagna alla Sala Zora"
    ),
    "Deliver the Ocean Title Deed to Ikana Canyon": (
        "Consegna la Carta di Proprietà dell'Oceano al Canyon di Ikana"
    ),
    "Deliver the Land Title Deed to Clock Town": (
        "Consegna la Carta di Proprietà della Terra a Clock Town"
    ),
    # objective descriptions — Darmani's Spirit
    "The Happy Mask Salesman trades the mask to a traveller he trusts.": (
        "Il Venditore di Maschere cede la maschera a un viaggiatore di cui si fida."
    ),
    "The Elder plays a melody that soothes Darmani's restless spirit.": (
        "L'Anziano suona una melodia che calma lo spirito inquieto di Darmani."
    ),
    "The Curiosity Shop sells the lens that sees the unseen.": (
        "Il Negozio di Curiosità vende la lente che vede l'invisibile."
    ),
    "Use the Lens of Truth to see Darmani's spirit.": (
        "Usa la Lente della Verità per vedere lo spirito di Darmani."
    ),
    "Darmani teaches you the lullaby that will put the baby to sleep.": (
        "Darmani ti insegna la ninna nanna che farà addormentare il bambino."
    ),
    # objective descriptions — Mikau's Memory
    "The Zora Mask lies buried in the tide-washed shore.": (
        "La Maschera Zora giace sepolta sulla riva lavata dalla marea."
    ),
    "Tael knows where Mikau's stolen eggs are hidden.": (
        "Tael sa dove sono nascoste le uova rubate di Mikau."
    ),
    "The Gerudo Pirates stole Mikau's eggs and hid them at Pinnacle Rock.": (
        "I Pirati Gerudo hanno rubato le uova di Mikau e le hanno nascoste alla Roccia Pinnacolo."
    ),
    "Mikau teaches you the song that opens the Great Bay Temple.": (
        "Mikau ti insegna la canzone che apre il Tempio della Grande Baia."
    ),
    # objective descriptions — Pamela's Father
    "The Curiosity Shop sells the mask before nightfall.": (
        "Il Negozio di Curiosità vende la maschera prima del calare della notte."
    ),
    "The castle is crawling with Gibdos during the night.": (
        "Il castello brulica di Gibdo durante la notte."
    ),
    "Wearing the Gibdo Mask, play the Song of Healing to free him.": (
        "Indossa la Maschera Gibdo e suona la Canzone della Guarigione per liberarlo."
    ),
    "Pamela is overjoyed to have her father back.": (
        "Pamela è felicissima di avere di nuovo suo padre."
    ),
    # objective descriptions — Deku Princess Rescue
    "The salesman loans the travelling hero the Deku Mask.": (
        "Il venditore presta la Maschera Deku all'eroe viaggiatore."
    ),
    "The Deku King believes you kidnapped his daughter.": (
        "Il Re Deku crede che tu abbia rapito sua figlia."
    ),
    "Follow the trail through the Southern Swamp to Woodfall.": (
        "Segui il sentiero attraverso la Palude del Sud fino a Woodfall."
    ),
    "The monkey locked the princess in a cage at Woodfall.": (
        "La scimmia ha rinchiuso la principessa in una gabbia a Woodfall."
    ),
    # objective descriptions — Romani Ranch
    "The keg shop sells the blast that drives the aliens away.": (
        "Il negozio di polvere vende l'esplosivo che scaccia gli alieni."
    ),
    "Romani needs your help defending the ranch from the Bremmmy Gyorgs tonight.": (
        "Romani ha bisogno del tuo aiuto per difendere la fattoria dai Bremmmy Gyorg stasera."
    ),
    "The aliens come at 2 AM. Use Cremia's wagon cannon to fight them off.": (
        "Gli alieni arrivano alle 2 di notte. Usa il cannone della carrozza di "
        "Cremia per respingerli."
    ),
    "Cremia needs an escort through the canyon on the Second Night.": (
        "Cremia ha bisogno di una scorta attraverso il canyon nella Seconda Notte."
    ),
    # objective descriptions — Land Title Deed Chain
    "The swamp owner hands over the deed to a worthy bearer.": (
        "Il proprietario della palude consegna la carta a un possessore degno."
    ),
    "Trade the Swamp Title Deed for the Mountain Title Deed.": (
        "Scambia la Carta di Proprietà della Palude con quella della Montagna."
    ),
    "Trade the Mountain Title Deed for the Ocean Title Deed.": (
        "Scambia la Carta di Proprietà della Montagna con quella dell'Oceano."
    ),
    "Trade the Ocean Title Deed for the Land Title Deed.": (
        "Scambia la Carta di Proprietà dell'Oceano con quella della Terra."
    ),
    "Complete the cycle by returning the Land Title Deed.": (
        "Completa il ciclo restituendo la Carta di Proprietà della Terra."
    ),
    # event names
    "Kafei's letter is delivered": ("La lettera di Kafei viene consegnata"),
    "Anju and Kafei reunite": "Anju e Kafei si riuniscono",
    "Bombers gather at the hideout": ("I Bombers si radunano al nascondiglio"),
    "Romani defends the ranch from aliens": ("Romani difende la fattoria dagli alieni"),
    "Cremia delivers milk to Clock Town": ("Cremia consegna il latte a Clock Town"),
    "Ghost plays the piano in Ikana Castle": ("Il fantasma suona il piano al Castello di Ikana"),
    "Blizzard rages near Snowhead": ("La bufera imperversa vicino a Snowhead"),
    # quest names
    "Bombers' Secret Society": "Società Segreta dei Bombers",
    "Darmani's Spirit": "Lo Spirito di Darmani",
    "Mikau's Memory": "La Memoria di Mikau",
    "Pamela's Father": "Il Padre di Pamela",
    "Deku Princess Rescue": "Il Salvataggio della Principessa Deku",
    "Romani Ranch": "Fattoria Romani",
    "Land Title Deed Chain": "Catena delle Carte di Proprietà",
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
    "Swamp Spider House": "Casa dei Ragni della Palude",
    "Deku Palace": "Palazzo Deku",
    "Woodfall": "Woodfall",
    "Goron Shrine": "Santuaro Goron",
    "Snowhead": "Snowhead",
    "Zora Hall": "Sala Zora",
    "Pinnacle Rock": "Roccia Pinnacolo",
    "Great Bay Coast": "Costa della Grande Baia",
    "Canyon Shrine": "Santuaro del Canyon",
    "Ancient Castle of Ikana": "Antico Castello di Ikana",
    "Ranch House": "Casa della Fattoria",
    "Termina Field": "Pianura di Termina",
    # masks / items
    "Deku Mask": "Maschera Deku",
    "Goron Mask": "Maschera Goron",
    "Zora Mask": "Maschera Zora",
    "Kafei's Mask": "Maschera di Kafei",
    "Gibdo Mask": "Maschera Gibdo",
    "All-Night Mask": "Maschera della Veglia",
    "Blast Mask": "Maschera della Scoppio",
    "Stone Mask": "Maschera di Pietra",
    "Great Fairy Mask": "Maschera della Grande Fata",
    "Postman's Hat": "Cappello del Postino",
    "Kafei's Letter": "Lettera di Kafei",
    "Swamp Title Deed": "Carta di Proprietà della Palude",
    "Mountain Title Deed": "Carta di Proprietà della Montagna",
    "Ocean Title Deed": "Carta di Proprietà dell'Oceano",
    "Land Title Deed": "Carta di Proprietà della Terra",
    "Lens of Truth": "Lente della Verità",
    "Powder Keg": "Barile di Polvere",
    # NPCs / quests (short names)
    "Anju and Kafei": "Anju e Kafei",
    "Postman": "Postino",
    "Goron Elder": "Anziano Goron",
    "Darmani": "Darmani",
    "Mikau": "Mikau",
    "Tael": "Tael",
    "Deku King": "Re Deku",
    "Pamela": "Pamela",
    "Romani": "Romani",
    "Cremia": "Cremia",
    "Shiro": "Shiro",
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
        "inventory_help": (
            "Select the items you carry. Selected = owned. Add any other item below."
        ),
        "inventory_add": "Add a custom item",
        "inventory_add_button": "Add",
        "quest_progress": "Quest Progress",
        "quest_progress_help": ("Select quests already completed \u2014 they\u2019ll be skipped."),
        "legend": "\u2713 Selected = owned / completed",
        "goal_placeholder": "What do you want to do?",
        "goal_example": "e.g. Reunite Anju and Kafei before the dawn of the Third Day",
        "generate_plan": "\u2728 Plan My Quest",
        "generate_plan_caption": "Builds the plan from your state and goal.",
        "stop_plan": "Stop",
        "stop_plan_help": "Stop after the current agent or LLM call finishes.",
        "info_edit_state": ("Set your state and goal, then press **Plan My Quest**."),
        "llm_settings": "LLM Settings",
        "save_load": "Save/Load",
        "save_button": "Save",
        "load_button": "Load",
        "save_ok": "Saved successfully",
        "load_none": "No save found",
        "llm_provider": "Provider",
        "llm_model": "Model",
        "llm_api_key": "API Key",
        "llm_model_required": "Model is required to plan.",
        "plan_model_caption": "Powered by {model}",
        "planning": "Planning...",
        "planning_error": "Planning failed: {error}",
        "planning_complete": "Planning complete",
        "planning_stopping": "Stopping planning...",
        "planning_stopped": "Planning stopped.",
        "planning_incomplete": "Planning stopped before a validated plan was produced.",
        "planning_gave_up": "Planning failed \u2014 attempt limit ({max}) reached",
        "step_attempt": "Attempt {n}/{max}",
        "replan_line": "{n} issue(s) \u2192 re-planning (attempt {max})",
        "knowledge_objectives": "{n} relevant objective(s):",
        "knowledge_empty_hint": (
            "No relevant objective matches this goal \u2014 try mentioning a "
            "character, an item or a place."
        ),
        "spinner_lines": (
            "Consulting the Triforce of Wisdom",
            "Contacting the Zonai servers",
            "Opening the Door of Time",
            "Playing the Song of Time",
            "Asking the Great Fairy for advice",
            "Paging through the Bomber's Notebook",
            "Following a mischievous fairy",
            "Warping with the Song of Storms",
        ),
        # live agent progress
        "prog_objectives": "{n} relevant objective(s)",
        "prog_mcp_data": "MCP data: {schedules} schedule(s), {events} event(s)",
        "prog_cache_search": "Searching the vector cache",
        "prog_cache_hit": "Cache: {n} passage(s)",
        "prog_revalidate": "Rechecking {n} cached page(s)",
        "prog_wiki_search": 'Searching the wiki: "*{query}*"',
        "prog_wiki_refs": "Wiki candidates: {n}",
        "prog_wiki_fetch": "Fetching: *{titles}*",
        "prog_wiki_indexed": "Indexed: *{pages}*",
        "prog_reretrieve": "Second vector retrieval",
        "prog_context": "Structured context: {n} objective(s)",
        "prog_retrieve": "Memory: {n} past episode(s)",
        "prog_store": "Memory stored (valid={valid})",
        "prog_llm": "Calling `{model}` (attempt {attempt})",
        "prog_llm_done": "{steps} step(s) in {seconds}s",
        "prog_running": "working...",
        # step sections
        "activity": "Activity",
        "result_state": "Detected state",
        "result_knowledge": "Retrieved knowledge",
        "result_memory": "Memory",
        "result_plan": "Proposed plan",
        "result_critic": "Validation outcome",
        "memory_episodes": "Past episodes reused",
        "memory_episodes_caption": "What memory recalled for this goal.",
        "memory_none": "No past episodes.",
        # output
        "your_plan": "Your Plan",
        "plan_valid": "\u2713 Plan valid",
        "plan_not_valid": "\u2717 Plan not valid \u2014 check the issues below",
        "agent_state": "State Agent",
        "agent_memory": "Memory Agent",
        "agent_knowledge": "Knowledge Agent",
        "agent_planning": "Planning Agent",
        "agent_critic": "Critic Agent",
        "no_plan": "No plan produced.",
        "window_label": "Window",
        "needs": "Needs",
        "depends_on": "Depends on step(s) {deps}",
        "step_n": "Step {n}",
        "plan": "plan",
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
        "kind_mask": "mask",
        "kind_objective": "objective",
        "kind_location": "location",
        "kind_prerequisite": "prerequisite",
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
        "source_masks": "Masks:",
        "source_after": "Comes after:",
        "no_sources": "No relevant sources found.",
        "rag_sources": "Wiki RAG sources",
        "rag_sources_caption": (
            "Zelda Wiki pages and passages processed through the persistent cache. "
            "They support the narrative explanation; structured MCP objectives "
            "remain authoritative."
        ),
        "rag_indexed_sources": "Indexed pages",
        "rag_indexed_sources_caption": "{n} page(s) indexed or represented for this request.",
        "rag_no_indexed_sources": "No indexed wiki page is available for this request.",
        "rag_evidence": "Retrieved evidence",
        "rag_engine": "Retrieval engine",
        "rag_status": "Retrieval status",
        "rag_score": "Score",
        "rag_source": "Source",
        "rag_page_id": "Page ID",
        "rag_revision": "Wiki revision",
        "rag_revision_url": "Revision URL",
        "rag_canonical_url": "Canonical URL",
        "rag_license": "License",
        "rag_license_link": "license terms",
        "rag_retrieved_at": "Retrieved at",
        "rag_warning": "Retrieval warning",
        "rag_wiki_unreachable": "Wiki unreachable \u2014 using structured MCP data only.",
        "rag_no_evidence": "No supplemental wiki passage matched this goal.",
        # tabs
        "tab_why": "Why this plan?",
        "tab_why_caption": (
            "Why the plan looks like this: for each step, its time window, "
            "the items it needs, and which earlier steps it depends on."
        ),
        "tab_sources": "Game sources",
        "tab_sources_caption": (
            "What the Knowledge Agent pulled from the structured game data and "
            "the Zelda Wiki RAG cache for your goal: objectives, NPCs, events, "
            "indexed pages and supplemental source passages. MCP data remains "
            "authoritative."
        ),
        "tab_trace": "How it was planned",
        "tab_trace_caption": (
            "The technical behind-the-scenes: what the system understood, "
            "how many planning attempts it made, and the validation results."
        ),
        # top-level tabs
        "tab_play": "Play",
        "tab_evaluation": "Evaluation",
        # evaluation tab
        "eval_title": "Plan evaluation",
        "eval_caption": (
            "Run the shipped scenarios against the live pipeline and check the "
            "plans it produces: goal reached, timing, prerequisites, tool usage."
        ),
        "eval_scenarios": "Scenarios",
        "eval_scenarios_help": "Pick the scenarios to run. Defaults to all of them.",
        "eval_rag": "Supplemental wiki retrieval",
        "eval_rag_help": (
            "Turn the wiki evidence off to compare plan quality with and without it."
        ),
        "eval_run": "Run evaluation",
        "eval_stop": "Stop evaluation",
        "eval_running": "Running the evaluation...",
        "eval_running_scenario": "Running {name}...",
        "eval_stopped": "The evaluation was stopped.",
        "eval_result": "Evaluation result",
        "eval_pass_rate": "Pass rate",
        "eval_passed": "Passed",
        "eval_failed": "Failed",
        "eval_failures_by_kind": "Failures by check",
        "eval_scenario": "Scenario",
        "eval_status": "Status",
        "eval_steps": "Steps",
        "eval_duration": "Duration",
        "eval_errors": "Errors",
        "eval_warnings": "Warnings",
        "eval_no_issues": "No issues: the plan satisfies every expectation.",
        "eval_no_results": "No scenario evaluated yet.",
        "eval_pass": "PASS",
        "eval_fail": "FAIL",
        "eval_run_error": "Run error",
        "eval_need_llm": "An LLM provider must be configured to run the evaluation.",
        "eval_load_last": "Load last report",
        "eval_no_saved_report": "No saved evaluation report yet.",
        "eval_saved_report": "Every sweep is saved to {path}.",
        "eval_report_meta": "Model: {model} · wiki retrieval: {rag} · repeats: {repeats}",
        "eval_rag_on": "on",
        "eval_rag_off": "off",
        "eval_rag_degraded": "degraded",
        "eval_rag_degraded_help": (
            "The wiki retrieval failed partway through the run (store locked or "
            "wiki unreachable). Compare sweeps on the per-scenario "
            "retrieval_status, not on this flag."
        ),
        "eval_unknown": "unknown",
        # sweep comparison (current sweep vs the newest stored one)
        "eval_compare_none": "No previous sweep to compare against yet.",
        "eval_compare_summary": "Previous sweep of {when}: {before} passed before, {after} now",
        "eval_compare_clean": (
            "No regressions against the previous sweep of {when}: "
            "{before} passed before, {after} now."
        ),
        "eval_compare_model": "Previous sweep: model {before} \u2192 {after}",
        "eval_compare_rag": "Previous sweep: wiki retrieval {before} \u2192 {after}",
        "eval_compare_repeats": "Previous sweep: repeats {before} \u2192 {after}",
        "eval_compare_scenario": "Scenario",
        "eval_compare_change": "Change",
        "eval_compare_detail": "Detail",
        "eval_compare_regressed": "regressed",
        "eval_compare_improved": "improved",
        "eval_compare_new": "new",
        "eval_compare_missing": "missing",
        "eval_compare_regressed_help": "passed in the previous sweep, fails now",
        "eval_compare_improved_help": "failed in the previous sweep, passes now",
        "eval_compare_new_help": "not in the previous sweep",
        "eval_compare_missing_help": "not in this sweep",
        "eval_compare_new_failure": "new failure: {kinds}",
        "llm_base_url_hint": (
            "The local OpenAI-compatible server needs the /v1 path "
            "(e.g. http://localhost:11434/v1)."
        ),
        # evaluation check kinds (reuse the validation legend labels)
        "kind_plan_shape": "plan shape",
        "kind_objective_achievement": "goal achievement",
        "kind_temporal_ordering": "temporal ordering",
        "kind_prerequisites": "prerequisites",
        "kind_tool_usage": "tool usage",
        "kind_critic": "critic",
        "kind_run_error": "run error",
        "kind_trajectory_order": "agent order",
        "kind_replan_bound": "re-plan bound",
        "kind_proposal_fidelity": "LLM proposal fidelity",
        "kind_proposal_fidelity_help": (
            "The final plan is correct: the deterministic rebuild added the missing steps."
        ),
        # trace sections
        "trace_understood": "What the system understood",
        "trace_understood_caption": (
            "The canonicalized reading of your state \u2014 this is what the planner worked from."
        ),
        "trace_validation_caption": ("Issues the critic found when checking feasibility."),
        # run audit
        "audit_header": (
            "Run `{run_id}` \u00b7 {seconds}s \u00b7 {attempts}/{max} attempt(s) \u00b7 {outcome}"
        ),
        "audit_valid": "\u2705 valid plan",
        "audit_invalid": "\u274c no valid plan",
        "audit_timeline": "Timeline",
        "audit_step": "Step",
        "audit_duration": "Duration",
        "audit_status": "Status",
        "audit_detail": "Details",
        "audit_errors": "Errors",
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
        "inventory_help": (
            "Seleziona gli oggetti che porti con te. Selezionato = lo possiedi. "
            "Aggiungi altri oggetti qui sotto."
        ),
        "inventory_add": "Aggiungi oggetto personalizzato",
        "inventory_add_button": "Aggiungi",
        "quest_progress": "Missioni completate",
        "quest_progress_help": (
            "Seleziona le missioni gi\u00e0 completate \u2014 verranno saltate."
        ),
        "legend": "\u2713 Selezionato = in possesso / completata",
        "goal_placeholder": "Cosa vuoi fare?",
        "goal_example": "Es. Ricongiungi Anju e Kafei prima dell'alba del Terzo Giorno",
        "generate_plan": "\u2728 Pianifica la mia missione",
        "generate_plan_caption": "Genera il piano dal tuo stato e obiettivo.",
        "stop_plan": "Stop",
        "stop_plan_help": (
            "Interrompe dopo il completamento dell'agente o della chiamata LLM in corso."
        ),
        "info_edit_state": ("Imposta stato e obiettivo, poi premi **Pianifica la mia missione**."),
        "llm_settings": "Impostazioni LLM",
        "save_load": "Partita",
        "save_button": "Salva",
        "load_button": "Carica",
        "save_ok": "Salvataggio riuscito",
        "load_none": "Nessun salvataggio trovato",
        "llm_provider": "Provider",
        "llm_model": "Modello",
        "llm_api_key": "Chiave API",
        "llm_model_required": "Il modello è obbligatorio per pianificare.",
        "plan_model_caption": "Generato con {model}",
        "planning": "Pianificazione...",
        "planning_error": "Pianificazione fallita: {error}",
        "planning_complete": "Pianificazione completata",
        "planning_stopping": "Interruzione della pianificazione...",
        "planning_stopped": "Pianificazione interrotta.",
        "planning_incomplete": "Pianificazione interrotta prima di produrre un piano validato.",
        "planning_gave_up": "Pianificazione fallita \u2014 limite tentativi ({max}) raggiunto",
        "step_attempt": "Tentativo {n}/{max}",
        "replan_line": "{n} problema/i \u2192 ripianificazione (tentativo {max})",
        "knowledge_objectives": "{n} objective rilevanti:",
        "knowledge_empty_hint": (
            "Nessun obiettivo pertinente per questo obiettivo \u2014 prova a citare "
            "un personaggio, un oggetto o un luogo."
        ),
        "spinner_lines": (
            "Interrogando la Triforza della Saggezza",
            "Contattando i server Zonai",
            "Aprendo la Porta del Tempo",
            "Suonando la Canzone del Tempo",
            "Chiedendo consiglio alla Grande Fata",
            "Cercando indizi nel Bomber's Notebook",
            "Seguendo una fata dispettosa",
            "Teleportando con la Canzone delle Tempeste",
        ),
        # live agent progress
        "prog_objectives": "{n} obiettivo/i rilevante/i",
        "prog_mcp_data": "Dati MCP: {schedules} schedule, {events} eventi",
        "prog_cache_search": "Cerco nella cache vettoriale",
        "prog_cache_hit": "Cache: {n} passaggi",
        "prog_revalidate": "Riverifico {n} pagine in cache",
        "prog_wiki_search": 'Cerco nella wiki: "*{query}*"',
        "prog_wiki_refs": "Candidati wiki: {n}",
        "prog_wiki_fetch": "Scarico: *{titles}*",
        "prog_wiki_indexed": "Indicizzato: *{pages}*",
        "prog_reretrieve": "Seconda ricerca vettoriale",
        "prog_context": "Contesto strutturato: {n} obiettivo/i",
        "prog_retrieve": "Memoria: {n} episodio/i",
        "prog_store": "Memoria salvata (valido={valid})",
        "prog_llm": "Chiamo `{model}` (tentativo {attempt})",
        "prog_llm_done": "{steps} passi in {seconds}s",
        "prog_running": "in corso...",
        # step sections
        "activity": "Attivit\u00e0",
        "result_state": "Stato rilevato",
        "result_knowledge": "Conoscenza recuperata",
        "result_memory": "Memoria",
        "result_plan": "Piano proposto",
        "result_critic": "Esito della validazione",
        "memory_episodes": "Episodi passati riusati",
        "memory_episodes_caption": "Cosa la memoria ha richiamato per questo obiettivo.",
        "memory_none": "Nessun episodio passato.",
        # output
        "your_plan": "Il Tuo Piano",
        "plan_valid": "\u2713 Piano valido",
        "plan_not_valid": ("\u2717 Piano non valido \u2014 controlla i problemi qui sotto"),
        "agent_state": "Agente di Stato",
        "agent_memory": "Agente Memoria",
        "agent_knowledge": "Agente della Conoscenza",
        "agent_planning": "Agente di Pianificazione",
        "agent_critic": "Agente Critico",
        "no_plan": "Nessun piano generato.",
        "window_label": "Finestra",
        "needs": "Necessita",
        "depends_on": "Dipende dai passi {deps}",
        "step_n": "Passo {n}",
        "plan": "piano",
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
        "kind_mask": "maschera",
        "kind_objective": "obiettivo",
        "kind_location": "posizione",
        "kind_prerequisite": "prerequisito",
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
        "source_masks": "Maschere:",
        "source_after": "Dopo:",
        "no_sources": "Nessuna fonte rilevante trovata.",
        "rag_sources": "Fonti RAG dalla Zelda Wiki",
        "rag_sources_caption": (
            "Pagine e passaggi della Zelda Wiki elaborati tramite cache persistente. "
            "Supportano la spiegazione narrativa; gli obiettivi MCP restano "
            "autoritativi."
        ),
        "rag_indexed_sources": "Pagine indicizzate",
        "rag_indexed_sources_caption": (
            "{n} pagina/e indicizzata/e o rappresentata/e per questa richiesta."
        ),
        "rag_no_indexed_sources": (
            "Nessuna pagina wiki indicizzata disponibile per questa richiesta."
        ),
        "rag_evidence": "Evidenze recuperate",
        "rag_engine": "Motore di recupero",
        "rag_status": "Stato del recupero",
        "rag_score": "Punteggio",
        "rag_source": "Fonte",
        "rag_page_id": "ID pagina",
        "rag_revision": "Revisione wiki",
        "rag_revision_url": "URL revisione",
        "rag_canonical_url": "URL canonico",
        "rag_license": "Licenza",
        "rag_license_link": "termini di licenza",
        "rag_retrieved_at": "Recuperata il",
        "rag_warning": "Avviso di recupero",
        "rag_wiki_unreachable": ("Wiki non raggiungibile \u2014 uso solo i dati MCP strutturati."),
        "rag_no_evidence": "Nessun passaggio wiki supplementare corrisponde all'obiettivo.",
        # tabs
        "tab_why": "Perch\u00e9 questo piano?",
        "tab_why_caption": (
            "Perch\u00e9 il piano \u00e8 fatto cos\u00ec: per ogni passo, "
            "la finestra temporale, gli oggetti necessari e i passi da cui dipende."
        ),
        "tab_sources": "Fonti di gioco",
        "tab_sources_caption": (
            "Cosa l'Agente della Conoscenza ha estratto dai dati strutturati "
            "e dalla cache RAG della Zelda Wiki per il tuo obiettivo: obiettivi, "
            "NPC, eventi, pagine indicizzate e passaggi supplementari. I dati "
            "MCP restano autoritativi."
        ),
        "tab_trace": "Come \u00e8 stato pianificato",
        "tab_trace_caption": (
            "Il dietro le quinte tecnico: cosa ha capito il sistema, "
            "quanti tentativi ha fatto e gli esiti della validazione."
        ),
        # top-level tabs
        "tab_play": "Gioca",
        "tab_evaluation": "Valutazione",
        # evaluation tab
        "eval_title": "Valutazione dei piani",
        "eval_caption": (
            "Esegui gli scenari forniti sul pipeline reale e verifica i piani che "
            "produce: obiettivo raggiunto, tempi, prerequisiti, uso degli strumenti."
        ),
        "eval_scenarios": "Scenari",
        "eval_scenarios_help": "Scegli gli scenari da eseguire. Per default sono tutti.",
        "eval_rag": "Retrieval wiki supplementare",
        "eval_rag_help": (
            "Disattiva le prove dal wiki per confrontare la qualità dei piani con e senza."
        ),
        "eval_run": "Esegui la valutazione",
        "eval_stop": "Interrompi la valutazione",
        "eval_running": "Valutazione in corso...",
        "eval_running_scenario": "In esecuzione {name}...",
        "eval_stopped": "Valutazione interrotta.",
        "eval_result": "Risultato della valutazione",
        "eval_pass_rate": "Tasso di successo",
        "eval_passed": "Superati",
        "eval_failed": "Falliti",
        "eval_failures_by_kind": "Fallimenti per controllo",
        "eval_scenario": "Scenario",
        "eval_status": "Esito",
        "eval_steps": "Passi",
        "eval_duration": "Durata",
        "eval_errors": "Errori",
        "eval_warnings": "Avvisi",
        "eval_no_issues": "Nessun problema: il piano soddisfa ogni aspettativa.",
        "eval_no_results": "Nessuno scenario valutato finora.",
        "eval_pass": "SUPERATO",
        "eval_fail": "FALLITO",
        "eval_run_error": "Errore di esecuzione",
        "eval_need_llm": "Serve un provider LLM configurato per eseguire la valutazione.",
        "eval_load_last": "Carica ultimo report",
        "eval_no_saved_report": "Nessun report di valutazione salvato.",
        "eval_saved_report": "Ogni sweep viene salvato in {path}.",
        "eval_report_meta": "Modello: {model} · retrieval wiki: {rag} · ripetizioni: {repeats}",
        "eval_rag_on": "attivo",
        "eval_rag_off": "disattivo",
        "eval_rag_degraded": "degradato",
        "eval_rag_degraded_help": (
            "Il retrieval wiki si è interrotto a metà run (store bloccato o wiki "
            "irraggiungibile). Confronta le sweep sul retrieval_status per "
            "scenario, non su questa etichetta."
        ),
        "eval_unknown": "sconosciuto",
        # sweep comparison (current sweep vs the newest stored one)
        "eval_compare_none": "Nessuno sweep precedente con cui confrontare.",
        "eval_compare_summary": (
            "Sweep precedente del {when}: prima {before} superati, ora {after}"
        ),
        "eval_compare_clean": (
            "Nessuna regressione rispetto allo sweep precedente del {when}: "
            "prima {before} superati, ora {after}."
        ),
        "eval_compare_model": "Sweep precedente: modello {before} \u2192 {after}",
        "eval_compare_rag": "Sweep precedente: retrieval wiki {before} \u2192 {after}",
        "eval_compare_repeats": "Sweep precedente: ripetizioni {before} \u2192 {after}",
        "eval_compare_scenario": "Scenario",
        "eval_compare_change": "Cambio",
        "eval_compare_detail": "Dettaglio",
        "eval_compare_regressed": "regressione",
        "eval_compare_improved": "migliorato",
        "eval_compare_new": "nuovo",
        "eval_compare_missing": "assente",
        "eval_compare_regressed_help": "passava nello sweep precedente, ora fallisce",
        "eval_compare_improved_help": "falliva nello sweep precedente, ora passa",
        "eval_compare_new_help": "non presente nello sweep precedente",
        "eval_compare_missing_help": "non presente in questo sweep",
        "eval_compare_new_failure": "nuovo fallimento: {kinds}",
        "llm_base_url_hint": (
            "Il server locale compatibile con OpenAI richiede il percorso /v1 "
            "(es. http://localhost:11434/v1)."
        ),
        # evaluation check kinds (reuse the validation legend labels)
        "kind_plan_shape": "forma del piano",
        "kind_objective_achievement": "raggiungimento obiettivo",
        "kind_temporal_ordering": "ordine temporale",
        "kind_prerequisites": "prerequisiti",
        "kind_tool_usage": "uso degli strumenti",
        "kind_critic": "critic",
        "kind_run_error": "errore di esecuzione",
        "kind_trajectory_order": "ordine degli agenti",
        "kind_replan_bound": "limite re-plan",
        "kind_proposal_fidelity": "fedeltà proposta LLM",
        "kind_proposal_fidelity_help": (
            "Il piano finale è corretto: la ricostruzione deterministica ha "
            "aggiunto i passi mancanti."
        ),
        # run audit
        "audit_header": (
            "Run `{run_id}` \u00b7 {seconds}s \u00b7 {attempts}/{max} tentativi \u00b7 {outcome}"
        ),
        "audit_valid": "\u2705 piano valido",
        "audit_invalid": "\u274c nessun piano valido",
        "audit_timeline": "Cronologia",
        "audit_step": "Fase",
        "audit_duration": "Durata",
        "audit_status": "Stato",
        "audit_detail": "Dettagli",
        "audit_errors": "Errori",
    },
}

DEFAULT_LANG = "en"


def t(key: str, **kwargs: object) -> str:
    """Return translated string for *key* in the current session language."""
    lang = st.session_state.get("lang", DEFAULT_LANG)
    template = _STRINGS.get(lang, _STRINGS[DEFAULT_LANG]).get(key, key)
    return template.format(**kwargs) if kwargs else template


def spinner_lines() -> tuple[str, ...]:
    """Zelda-themed phrases rotated in the planning spinner title."""
    lang = st.session_state.get("lang", DEFAULT_LANG)
    return _STRINGS.get(lang, _STRINGS[DEFAULT_LANG])["spinner_lines"]


def tr(s: str) -> str:
    """Translate game-entity display names inside *s*, leaving code spans intact."""
    if st.session_state.get("lang", DEFAULT_LANG) == "en":
        return s
    parts = _CODE_SPAN_RE.split(s)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(part)
            continue
        for en in _DISPLAY_KEYS_IT:
            part = part.replace(en, _DISPLAY_IT[en])
        out.append(part)
    return "".join(out)


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
    "Missing mask(s): ": "Maschere mancanti: ",
    "Missing prerequisite(s): ": "Prerequisiti mancanti: ",
    "Depends on a step that ends after this one starts.": (
        "Dipende da un passo che termina dopo l'inizio di questo."
    ),
    "The LLM proposal omitted expected objectives: ": (
        "La proposta LLM ha omesso obiettivi previsti: "
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
