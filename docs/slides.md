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

- First point,\
  brief\
  and concrete
- Second point,\
  one idea only
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
| anju-kafei    | 3 / 3  | 3 / 3   | Tie      |
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
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Inter, Arial, sans-serif","fontSize":"26px","primaryColor":"#2b2352","primaryTextColor":"#f3ecdd","primaryBorderColor":"#8b7bd8","lineColor":"#f0b24a","tertiaryColor":"#3a3160","edgeLabelBackground":"#3a3160","mainBkg":"#2b2352","nodeBorder":"#8b7bd8","textColor":"#f3ecdd"},"flowchart":{"curve":"linear","htmlLabels":false,"nodeSpacing":50,"rankSpacing":80,"padding":10,"wrappingWidth":400},"themeCSS":".nodeLabel, .edgeLabel { font-family: Inter, Arial, sans-serif !important; }"}}%%
flowchart LR
  gs([Game State]) --> sa[State Agent] --> ka[Knowledge Agent] --> pa[Planning Agent] --> d{Valid?}
  d -->|Yes| plan([Plan])
  d -->|No| rp([re-plan])
  rp --> pa
  classDef start fill:#2b2352,stroke:#6fb7e8,stroke-width:2px,color:#f3ecdd;
  classDef agent fill:#2b2352,stroke:#8b7bd8,stroke-width:2px,color:#f3ecdd;
  classDef decision fill:#f0b24a,stroke:#f0b24a,color:#1a1530,font-weight:600;
  classDef plan fill:#2b2352,stroke:#5fd08a,stroke-width:2px,color:#f3ecdd;
  classDef label fill:#3a3160,stroke:#3a3160,color:#f3ecdd;
  class gs start;
  class sa,ka,pa agent;
  class d decision;
  class plan plan;
  class rp label;
  linkStyle default stroke:#f0b24a,stroke-width:3px;
  linkStyle 5,6 stroke:#b79ae8,stroke-width:3px;
```

---

<!-- _class: dark closing -->
<!-- _paginate: false -->

# Thank you

<hr>

Questions and discussion

[\[name@domain.com\]](mailto:name@domain.com) [\[github.com/user\]](https://github.com/user)
