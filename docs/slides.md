---
marp: true
theme: taia-slides
paginate: true
size: 16:9
html: true
---

<!-- _class: cover -->
<!-- _paginate: false -->

<img class="mask" src="assets/majora-mask.png" alt="">
<div class="dots"><i></i><i></i><i></i><i></i><i></i><i></i></div>
<div class="cover-event">[EVENT NAME / DATE]</div>
<img class="cover-logo" src="title.png" alt="TaIA — Majora's Mask Multi-Agent Planner">
<div class="cover-sub">Subtitle explaining the topic in one line</div>
<div class="cover-author">[First Last] · [Role]</div>

---

<!-- _class: dark -->

<div class="wrap between">
<div class="section-number">01</div>
<div class="stack">
<div class="head"><h2 class="h section-title">Section title</h2></div>
<div class="rule"><span></span><img src="assets/separator-gold.svg" alt=""><span></span></div>
<div class="lead">One sentence introducing the topic that follows</div>
</div>
</div>
<div class="bar t1" style="--on:#1a1530;--off:#d99a2e"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Slide title</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="points">
<p>First point,<br>brief<br>and concrete</p>
<p>Second point,<br>one idea only</p>
<p>Third point with <strong>key word</strong> highlighted</p>
</div>
</div>
</div>
<div class="bar t2"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Three ideas compared</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="cards">
<div class="card"><div class="num">1</div><h3>First topic</h3><p>Description in at most two lines.</p></div>
<div class="card"><div class="num">2</div><h3>Second topic</h3><p>Description in at most two lines.</p></div>
<div class="card"><div class="num">3</div><h3>Third topic</h3><p>Description in at most two lines.</p></div>
</div>
</div>
</div>
<div class="bar t3"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: dark -->

<div class="wrap center">
<div class="quote">
<div class="big-number">9/9</div>
<div class="quote-text">The most important figure or quote, in one sentence</div>
<div class="quote-source">[Source or context]</div>
</div>
</div>
<img class="clock" src="assets/clock.svg" alt="">
<div class="bar t4" style="--on:#f0b24a;--off:#3a3160"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Text and image</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="split">
<div class="text">A short paragraph accompanying the image or screenshot on the right.</div>
<div class="media">[Image or screenshot]</div>
</div>
</div>
</div>
<div class="bar t5"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Notes and warnings</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="callouts">
<div class="callout info"><div class="label">INFO</div><p>An informative note, useful but not essential.</p></div>
<div class="callout success"><div class="label">SUCCESS</div><p>A result achieved or a good practice to follow.</p></div>
<div class="callout warning"><div class="label">WARNING</div><p>A warning about a risk or a limit to be aware of.</p></div>
</div>
</div>
</div>
<div class="bar t6"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Comparison table</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<table class="table">
<thead><tr><th>Scenario</th><th>RAG on</th><th>RAG off</th><th>Result</th></tr></thead>
<tbody>
<tr><td>anju-kafei</td><td>3 / 3</td><td>3 / 3</td><td class="tie">Tie</td></tr>
<tr><td>darmani-ghost</td><td>3 / 3</td><td>2 / 3</td><td class="improves">Improves</td></tr>
<tr><td>mikau-eggs</td><td>3 / 3</td><td>3 / 3</td><td class="tie">Tie</td></tr>
<tr><td>deed-chain</td><td>2 / 3</td><td>3 / 3</td><td class="worsens">Worsens</td></tr>
</tbody>
</table>
</div>
</div>
<div class="bar t7"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Code block</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="code">
<div class="code-title"><i class="r"></i><i class="y"></i><i class="g"></i><span>graph.py</span></div>
<pre><span class="ln">1</span># Builds the graph of the four agents
<span class="ln">2</span>graph = StateGraph(PlanningState)
<span class="ln">3</span>graph.add_node("state", state_agent.run)
<span class="ln">4</span>graph.add_node("knowledge", knowledge_agent.run)
<span class="ln">5</span>graph.add_node("planning", planning_agent.run)
<span class="ln">6</span>graph.add_node("critic", critic_agent.run)
<span class="ln">7</span>graph.add_edge("state", "knowledge")</pre>
</div>
</div>
</div>
<div class="bar t8"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: light -->

<div class="wrap">
<div class="stack">
<div class="head"><div class="eyebrow">SECTION 01</div><h2 class="h">Diagram</h2></div>
<div class="rule"><span></span><img src="assets/separator.svg" alt=""><span></span></div>
<div class="diagram"><img src="assets/diagram.svg" alt="Pipeline diagram: Game State, State Agent, Knowledge Agent, Planning Agent, Valid? decision, Plan, with an arrow back to the Planning Agent"></div>
</div>
</div>
<div class="bar t9"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>

---

<!-- _class: dark -->
<!-- _paginate: false -->

<img class="mask" src="assets/majora-mask.png" alt="">
<div class="dots"><i></i><i></i><i></i><i></i><i></i><i></i></div>
<div class="wrap end">
<div class="closing-title">Thank you</div>
<div class="rule gold"><span></span><img src="assets/separator-gold.svg" alt=""><span></span></div>
<div class="closing-sub">Questions and discussion</div>
<div class="contacts">
<span><img src="assets/email.svg" alt="Email">[name@domain.com]</span>
<span><img src="assets/github.svg" alt="GitHub">[github.com/user]</span>
</div>
</div>
