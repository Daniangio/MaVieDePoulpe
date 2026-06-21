# Bot Strategy Planning

## Overview

The search bot uses two layers:

- **Tactical search**: short-horizon simulation over legal decisions.
- **Strategic planning**: deck-plan evaluation derived from protagonist, persona deck, and selected card packages.

Strategic planning is intentionally separated from tactical search because full long-horizon rollout is expensive and not needed on every node.

## Strategic Profile

Card definitions may declare:

- `strategy_tags`
- `strategy_weights`

These are loaded into `CardDefinition` and used to build a per-player `StrategicProfile`.

Examples:

- `discard_engine`
- `omen_engine`
- `ritual_engine`
- `advent_graveyard_engine`
- `mecha_setup_engine`
- `long_plan`

The profile combines:

- protagonist tags
- persona-deck card tags
- explicit pair/package rules

This allows a protagonist and its persona deck to jointly define a long-term plan.

## Strategic Signature

Long-term planning is cached behind a `StrategicSignature`.

The signature is a compact milestone-oriented summary of the current strategic state, including:

- current protagonist id
- coarse turn stage
- milestone buckets for relevant strategic features
- package-specific progress markers, such as ritual counter thresholds

If the signature does not change, the cached long-term plan is reused.

Non-milestone noise such as small fragment drift or hand-size changes does not invalidate the cache.

## Strategic Plan Snapshot

The cached object is `StrategicPlanSnapshot`, which stores:

- `StrategicSignature`
- `StrategicProfile`
- current strategic score
- cached solo-rollout delta

`RoomManager` keeps one snapshot per active bot per live game and refreshes it only when that bot's signature changes.

## Solo Rollout

Solo rollout is restricted to setup-oriented progression:

- allowed:
  - draw / search / discard
  - graveyard / oblivion manipulation
  - persona setup
  - resource and counter progression
- excluded:
  - attack
  - block
  - retire
  - combat-only tactical lines

The opponent is treated as passive and only advances flow with no-op / forced actions.

Rollout is capped at **turn 10** and disabled after turn 10.

## Search Integration

Search does **not** rerun long-term rollout for every deep node.

Instead:

- tactical evaluation remains dynamic per node
- strategic feature scoring remains cheap per node
- the expensive rollout contribution comes from the cached `StrategicPlanSnapshot`

The cached rollout is bot-local. Missing opponent snapshots do not trigger fresh opponent rollouts during search.

This keeps long-term planning stable enough to matter, while keeping bot latency bounded.
