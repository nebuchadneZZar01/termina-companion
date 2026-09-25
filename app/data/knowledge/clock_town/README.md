# Clock Town knowledge corpus

This directory contains the first curated, web-researched corpus for the
Knowledge Agent. It is **not generated from `app/data/mock_knowledge.py`**.
The documents are original summaries written for this project after checking
multiple public game references.

## Scope

The first slice covers Clock Town and the information-rich part of the Anju &
Kafei quest. It also includes nearby services and the Bombers' Secret Society so
that small player goals can be tested against both structured and textual
knowledge.

Documents are evidence for the RAG layer only. Quest objective order, exact
structured windows, item requirements, NPC schedules, events and prerequisite
relationships remain authoritative in the MCP data/tools. A disagreement is a
signal for a later data audit, not permission for RAG to silently rewrite the
planner's structured knowledge.

## Research and reuse policy

- Facts were checked against the sources listed in each document and in the
  source inventory below.
- Prose in this directory is a fresh synthesis. No walkthrough paragraph,
  wiki article, dialogue transcript or image caption is copied.
- Source URLs and retrieval date are retained as metadata for auditability.
- Guides with unclear or restrictive reuse terms are used for fact-checking
  only. Their text is not redistributed.
- The corpus is intentionally version-aware. Original N64 instructions and
  Majora's Mask 3D changes are called out where they matter.
- A future wiki dump must be a separate corpus with attribution, snapshots,
  deduplication and a license review. It must not be mixed into this curated
  set by accident.

## Source inventory

Primary factual cross-checks:

- [Thonky — Clock Town walkthrough](https://www.thonky.com/zelda-majoras-mask/clock-town)
- [Thonky — Anju and Kafei Quest](https://www.thonky.com/zelda-majoras-mask/anju-kafei-quest)
- [Thonky — Bombers Notebook](https://www.thonky.com/zelda-majoras-mask/bombers-notebook)
- [Zelda Central — Anju and Kafei Quest](https://zeldacentral.com/games/majoras-mask/side-quests/anju-and-kafeis-quest/)
- [Zelda Central — Bombers' Notebook](https://zeldacentral.com/games/majoras-mask/bombers-notebook/)

Reference pages used for schedules, terminology and corroboration:

- [Zelda Wiki — Anju](https://zeldawiki.wiki/wiki/Anju)
- [Zelda Wiki — Kafei](https://zeldawiki.wiki/wiki/Kafei)
- [Zelda Wiki — Anju's Anguish](https://zeldawiki.wiki/wiki/Anju%27s_Anguish)
- [Zelda Wiki — Laundry Pool](https://zeldawiki.wiki/wiki/Laundry_Pool)
- [Zelda Wiki — Post Office](https://zeldawiki.wiki/wiki/Post_Office)
- [Zelda Wiki — Postman's Hat](https://zeldawiki.wiki/wiki/Postman%27s_Hat)
- [Zelda Wiki — Bombers' Hideout](https://zeldawiki.wiki/wiki/Bombers%27_Hideout)
- [Zelda Dungeon — Stock Pot Inn](https://www.zeldadungeon.net/wiki/Stock_Pot_Inn)
- [Zelda Dungeon — Postman](https://www.zeldadungeon.net/wiki/Postman)

The Zelda Wiki and Zelda Dungeon search results identify their text content as
GFDL, but this corpus does not copy their prose. License and attribution must
be reviewed again before importing a larger snapshot.

## Retrieval notes

Documents include English prose and Italian aliases/synonyms because player
goals may be entered in either language. Retrieval should return the source
document id, title, URL and the matching chunk. Structured MCP evidence must
remain visible next to RAG evidence in the final state.
