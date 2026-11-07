---
marp: true
theme: taia-slides
paginate: true
size: 16:9
html: true
---

<!-- _class: cover -->
<!-- _paginate: false -->
<!-- _header: '[EVENT NAME / DATE]' -->

![TaIA — Majora's Mask Multi-Agent Planner](title.png)

Subtitle explaining the topic in one line

[First Last] · [Role]

---

<!-- _class: gold t1 -->

# 01

## Section title

<hr>

One sentence introducing the topic that follows

---

<!-- _class: light t2 -->

<!-- _header: 'SECTION 01' -->

## Slide title

<hr>

- First point, brief and concrete
- Second point, one idea only
- Third point with **key word** highlighted

---

<!-- _class: light t3 -->

<!-- _header: 'SECTION 01' -->

## Three ideas compared

<hr>

- ### First topic

  Description in at most two lines.

- ### Second topic

  Description in at most two lines.

- ### Third topic

  Description in at most two lines.

---

<!-- _class: dark t4 -->

## 9/9

The most important figure or quote, in one sentence

[Source or context]

---

<!-- _class: light t5 -->

<!-- _header: 'SECTION 01' -->

## Text and image

<hr>

> A short paragraph accompanying the image or screenshot on the right.
>
> [Image or screenshot]

---

<!-- _class: light t6 -->

<!-- _header: 'SECTION 01' -->

## Notes and warnings

<hr>

> **INFO**
>
> An informative note, useful but not essential.

> **SUCCESS**
>
> A result achieved or a good practice to follow.

> **WARNING**
>
> A warning about a risk or a limit to be aware of.

---

<!-- _class: light t7 -->

<!-- _header: 'SECTION 01' -->

## Comparison table

<hr>

| Scenario      | RAG on | RAG off | Result   |
| ------------- | ------ | ------- | -------- |
| `anju-kafei`    | 3 / 3  | 3 / 3   | Tie      |
| darmani-ghost | 3 / 3  | 2 / 3   | Improves |
| mikau-eggs    | 3 / 3  | 3 / 3   | Tie      |
| deed-chain    | 2 / 3  | 3 / 3   | Worsens  |

---

<!-- _class: light t8 -->

<!-- _header: 'SECTION 01' -->

## Code block

<hr>

```python title="graph.py"
# Builds the graph of the four agents
graph = StateGraph(PlanningState)
graph.add_node("state", state_agent.run)
graph.add_node("knowledge", knowledge_agent.run)
graph.add_node("planning", planning_agent.run)
graph.add_node("critic", critic_agent.run)
graph.add_edge("state", "knowledge")
```

---

<!-- _class: light t9 -->

<!-- _header: 'SECTION 01' -->

## Diagram

<hr>

```mermaid
flowchart LR
  gs([Game State]) --> sa[State Agent] --> ka[Knowledge Agent] --> pa[Planning Agent] --> d{Valid?}
  d -->|Yes| plan([Plan])
  d e_acc1@-->|No| rp([re-plan])
  rp e_acc2@--> pa
  class gs start;
  class sa,ka,pa agent;
  class d decision;
  class plan plan;
  class rp label;
```

---

<!-- _class: dark closing -->
<!-- _paginate: false -->

# Thank you

<hr>

Questions and discussion

[\[name@domain.com\]](mailto:name@domain.com) [\[github.com/user\]](https://github.com/user)
