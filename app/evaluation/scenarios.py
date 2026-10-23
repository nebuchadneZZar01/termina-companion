"""Evaluation scenarios for the plan-evaluation harness.

One scenario per quest: a player state, a goal phrased the way a player would
phrase it, and the objectives the plan is expected to contain. The set spans
every game area and covers the hard cases of the temporal slice: night-only
windows, masks handed over mid-chain, items that unlock the next step, and
chains that span the whole three-day cycle.

The goal text is also the retrieval query: the Knowledge Agent matches it
against the objective keywords, so every goal below is phrased to surface
exactly one quest.
"""

from __future__ import annotations

from app.domain import ClockTime, GameState
from app.evaluation.models import PlanScenario

EVALUATION_SCENARIOS: list[PlanScenario] = [
    PlanScenario(
        id="anju-kafei",
        name="Anju and Kafei",
        description=(
            "Nine-step chain over three days: the mask and room key unlock Anju, "
            "the letter reaches Kafei, and the couple reunites before dawn."
        ),
        goal="Reunite Anju and Kafei before the dawn of the Third Day",
        game_state=GameState(
            time=ClockTime(day=1, hour=6),
            location="South Clock Town",
            inventory=["Hookshot"],
            masks=["Garo's Mask"],
        ),
        required_objective_refs=[
            "ak_get_kafei_mask",
            "ak_get_room_key",
            "ak_talk_to_anju",
            "ak_meet_in_kitchen",
            "ak_post_letter",
            "ak_meet_kafei",
            "ak_deliver_pendant",
            "ak_sakon_hideout",
            "ak_reunite",
        ],
        terminal_objective_ref="ak_reunite",
        expected_order=[
            ("ak_get_kafei_mask", "ak_get_room_key"),
            ("ak_get_room_key", "ak_talk_to_anju"),
            ("ak_talk_to_anju", "ak_meet_in_kitchen"),
            ("ak_meet_in_kitchen", "ak_post_letter"),
            ("ak_post_letter", "ak_meet_kafei"),
            ("ak_meet_kafei", "ak_deliver_pendant"),
            ("ak_deliver_pendant", "ak_sakon_hideout"),
            ("ak_sakon_hideout", "ak_reunite"),
        ],
        min_steps=9,
        max_steps=9,
    ),
    PlanScenario(
        id="bombers-notebook",
        name="Bombers' Secret Society",
        description="A notebook earned from the leader unlocks the hidden hideout.",
        goal="Earn the Bombers' Notebook from their leader and join the Secret Society",
        game_state=GameState(
            time=ClockTime(day=1, hour=7),
            location="North Clock Town",
        ),
        required_objective_refs=["bm_talk_leader", "bm_get_notebook", "bm_find_hideout"],
        terminal_objective_ref="bm_find_hideout",
        expected_order=[("bm_get_notebook", "bm_find_hideout")],
        min_steps=3,
        max_steps=3,
    ),
    PlanScenario(
        id="darmani-ghost",
        name="Darmani's Spirit",
        description=(
            "Longest mask chain: the Goron Mask and the Lens of Truth unlock the "
            "night meeting, and the lullaby happens at 22:00."
        ),
        goal="See Darmani's ghost and learn the Goron Lullaby",
        game_state=GameState(
            time=ClockTime(day=1, hour=7),
            location="Termina Field",
        ),
        required_objective_refs=[
            "dg_get_goron_mask",
            "dg_talk_elder",
            "dg_get_lens",
            "dg_meet_darmani",
            "dg_learn_lullaby",
        ],
        terminal_objective_ref="dg_learn_lullaby",
        expected_order=[
            ("dg_get_goron_mask", "dg_talk_elder"),
            ("dg_get_lens", "dg_meet_darmani"),
            ("dg_meet_darmani", "dg_learn_lullaby"),
        ],
        min_steps=5,
        max_steps=5,
    ),
    PlanScenario(
        id="mikau-eggs",
        name="Mikau's Memory",
        description="The Zora Mask gates every later step, and the eggs need a daytime window.",
        goal="Retrieve Mikau's stolen eggs from Pinnacle Rock after finding Tael",
        game_state=GameState(
            time=ClockTime(day=1, hour=7),
            location="Great Bay Coast",
        ),
        required_objective_refs=[
            "mm_get_zora_mask",
            "mm_find_tael",
            "mm_recover_eggs",
            "mm_learn_song",
        ],
        terminal_objective_ref="mm_learn_song",
        expected_order=[
            ("mm_get_zora_mask", "mm_find_tael"),
            ("mm_find_tael", "mm_recover_eggs"),
            ("mm_recover_eggs", "mm_learn_song"),
        ],
        min_steps=4,
        max_steps=4,
    ),
    PlanScenario(
        id="mikau-with-zora-mask",
        name="Mikau's Memory (Zora Mask owned)",
        description=(
            "The Zora Mask is already owned, so the plan must skip the shore and "
            "go straight to Tael."
        ),
        goal="Retrieve Mikau's stolen eggs from Pinnacle Rock after finding Tael",
        game_state=GameState(
            time=ClockTime(day=1, hour=7),
            location="Great Bay Coast",
            masks=["Zora Mask"],
        ),
        required_objective_refs=[
            "mm_find_tael",
            "mm_recover_eggs",
            "mm_learn_song",
        ],
        terminal_objective_ref="mm_learn_song",
        forbidden_objective_refs=["mm_get_zora_mask"],
        expected_order=[
            ("mm_find_tael", "mm_recover_eggs"),
            ("mm_recover_eggs", "mm_learn_song"),
        ],
        min_steps=3,
        max_steps=3,
    ),
    PlanScenario(
        id="pamela-father",
        name="Pamela's Father",
        description="Night-only slot (00:00-04:00, after midnight) behind the Gibdo Mask.",
        goal="Break Pamela's father's Gibdo curse inside the castle",
        game_state=GameState(
            time=ClockTime(day=1, hour=9),
            location="Curiosity Shop",
        ),
        required_objective_refs=[
            "pf_get_gibdo_mask",
            "pf_sneak_castle",
            "pf_free_father",
            "pf_meet_pamela",
        ],
        terminal_objective_ref="pf_meet_pamela",
        expected_order=[
            ("pf_get_gibdo_mask", "pf_sneak_castle"),
            ("pf_free_father", "pf_meet_pamela"),
        ],
        min_steps=4,
        max_steps=4,
    ),
    PlanScenario(
        id="deku-princess",
        name="Deku Princess Rescue",
        description="Two-day chain through the Southern Swamp, gated by the Deku Mask.",
        goal="Rescue the Deku Princess from Woodfall",
        game_state=GameState(
            time=ClockTime(day=1, hour=7),
            location="Termina Field",
        ),
        required_objective_refs=[
            "dp_get_deku_mask",
            "dp_talk_king",
            "dp_enter_woodfall",
            "dp_free_princess",
        ],
        terminal_objective_ref="dp_free_princess",
        expected_order=[
            ("dp_get_deku_mask", "dp_talk_king"),
            ("dp_enter_woodfall", "dp_free_princess"),
        ],
        min_steps=4,
        max_steps=4,
    ),
    PlanScenario(
        id="romani-ranch",
        name="Romani Ranch",
        description=(
            "Morning Powder Keg purchase, then a 2 AM alien defence at the end "
            "of the First Day and the moonlit milk delivery."
        ),
        goal="Help Romani defend the ranch and escort Cremia",
        game_state=GameState(
            time=ClockTime(day=1, hour=6),
            location="Termina Field",
        ),
        required_objective_refs=[
            "rr_get_powder_keg",
            "rr_help_romani",
            "rr_defend_ranch",
            "rr_milk_delivery",
        ],
        terminal_objective_ref="rr_milk_delivery",
        expected_order=[
            ("rr_get_powder_keg", "rr_help_romani"),
            ("rr_help_romani", "rr_defend_ranch"),
            ("rr_defend_ranch", "rr_milk_delivery"),
        ],
        min_steps=4,
        max_steps=4,
    ),
    PlanScenario(
        id="deed-chain",
        name="Land Title Deed Chain",
        description="Five-step trade cycle across three areas and all three days.",
        goal="Complete the title deed trade cycle",
        game_state=GameState(
            time=ClockTime(day=1, hour=6),
            location="Swamp Spider House",
        ),
        required_objective_refs=[
            "dc_get_swamp_deed",
            "dc_swamp_to_mountain",
            "dc_mountain_to_bay",
            "dc_bay_to_ikana",
            "dc_land_to_ct",
        ],
        terminal_objective_ref="dc_land_to_ct",
        expected_order=[
            ("dc_get_swamp_deed", "dc_swamp_to_mountain"),
            ("dc_swamp_to_mountain", "dc_mountain_to_bay"),
            ("dc_mountain_to_bay", "dc_bay_to_ikana"),
            ("dc_bay_to_ikana", "dc_land_to_ct"),
        ],
        min_steps=5,
        max_steps=5,
    ),
]

SCENARIOS_BY_ID: dict[str, PlanScenario] = {s.id: s for s in EVALUATION_SCENARIOS}
