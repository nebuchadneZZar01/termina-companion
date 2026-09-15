"""Minimal Streamlit UI for Termina Companion.

Entry points: ``uv run streamlit run main.py`` (preferred) or
``uv run streamlit run app/ui.py``.
"""

from __future__ import annotations

import streamlit as st

from app.data.mock_knowledge import MASKS, build_default_knowledge
from app.domain import ClockTime, GameState, Goal
from app.graph import MAX_PLANNING_ATTEMPTS, build_graph


@st.cache_resource
def _graph():
    return build_graph()


def render() -> None:
    st.set_page_config(page_title="Termina Companion", page_icon=":material/explore:")

    st.title("Termina Companion")
    st.caption("Multi-agent temporal planner for Majora's Mask (mock knowledge, no API keys).")

    kb = build_default_knowledge()

    with st.sidebar:
        st.header("Player state")
        day = st.selectbox("Day", [1, 2, 3], index=1)
        hour = st.slider("Hour", 0, 23, 8)
        minute = st.slider("Minute", 0, 59, 0, step=5)
        locations = sorted({loc.name for loc in kb.locations})
        location = st.selectbox("Location", locations or ["Termina Field"])
        item_options = sorted(
            {i for quest in kb.quests for o in quest.objectives for i in o.requires_items}
        )
        inventory = st.multiselect("Inventory", item_options or ["Kafei's Letter"])
        selected_masks = st.multiselect("Masks", list(MASKS))
        done_quests = st.multiselect("Completed quests", [q.id for q in kb.quests])

        st.header("Goal")
        goal_text = st.text_input(
            "What do you want to do?",
            value="Reunite Anju and Kafei before the dawn of the Third Day",
        )
        run = st.button("Generate plan", type="primary")

    st.header("Goal")
    st.write(goal_text)

    if not run:
        st.info("Edit the player state and a goal, then press **Generate plan**.")
        return

    game_state = GameState(
        time=ClockTime(day=day, hour=hour, minute=minute),
        location=location,
        inventory=list(inventory),
        masks=list(selected_masks),
        quest_progress={q: "done" for q in done_quests},
    )
    goal = Goal(description=goal_text)

    with st.spinner("Planning..."):
        result = _graph().invoke({"game_state": game_state, "goal": goal})

    st.header("State Agent")
    st.write(result["state_summary"])

    st.header("Knowledge Agent")
    st.write(result["retrieved_context"])

    st.header(f"Plan  (attempts: {result['replan_attempts']} / max {MAX_PLANNING_ATTEMPTS})")
    plan = result["plan"]
    if plan:
        for i, step in enumerate(plan["steps"], 1):
            window = step["window"]
            with st.expander(f"{i}. {step['title']}", expanded=True):
                when_start = window["start"]
                when_end = window["end"]
                start_s = (
                    f"Day {when_start['day']} {when_start['hour']:02d}:{when_start['minute']:02d}"
                )
                end_s = f"Day {when_end['day']} {when_end['hour']:02d}:{when_end['minute']:02d}"
                st.write(f"**When:** {start_s} \u2192 {end_s}")
                st.write(f"**Where:** {step['location']}")
                if step["requires_items"]:
                    st.write(f"**Needs:** {', '.join(step['requires_items'])}")
                for action in step["actions"]:
                    st.write(f"\u2022 {action}")
    else:
        st.write("No plan produced.")

    st.header("Validation")
    validation = result["validation"]
    if validation["valid"]:
        st.success("The plan is feasible.")
        return
    st.error("The plan is not feasible:")
    for issue in validation["issues"]:
        where = issue["step_idx"] + 1 if issue["step_idx"] is not None else ""
        prefix = f"Step {where}: " if where else ""
        st.write(f"- **[{issue['severity']} / {issue['kind']}]** {prefix}{issue['message']}")


if __name__ == "__main__":
    render()
