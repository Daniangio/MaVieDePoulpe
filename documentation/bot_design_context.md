# Ma Vie De Poulpe Bot Design Context

This document describes the current game rules and implementation details needed to reason about bot players for Ma Vie De Poulpe. It is intended as a prompt/reference file for an LLM that will propose bot and orchestration strategies.

## Goal For Bot Design

The game is cooperative. A bot design cannot simply maximize one private score. Each ability/player board sees its own hand and board state, can propose useful actions from that local perspective, and a coordinator must choose a shared plan.

The desired design question is:

- How should each ability bot evaluate possible plans using its own visible information?
- How should a central orchestrator, or a human player assisted by bots, compare those proposals?
- How should the system handle partial information, shared resources, action/time pressure, and cooperative sequencing?

## Current Runtime Summary

The implemented playable mode is the goldfish prototype.

Backend:

- FastAPI backend.
- Runtime game state is represented as an authoritative `GameState` per room.
- Game commands use a standard envelope with `command_id`, `room_id`, actor fields, `expected_version`, `type`, and `payload`.
- Accepted commands increment `version`.
- Rejected commands return structured rejections with a reason and message.
- Game state projections are broadcast over WebSocket.
- Redis-backed worker/runtime support exists in the project, but the bot design should treat the backend reducer in `backend/app/game_room_service.py` as the gameplay source of truth.

Frontend:

- React TypeScript game room UI in `frontend/src/pages/GameRoomPage.tsx`.
- Board rendering is in `frontend/src/components/BoardView.tsx`.
- Tile preview rendering is shared with admin console through `frontend/src/components/HexTilePreview.jsx`.

Admin-authored game content:

- Maps, levels, categories, interactions, events/animals, tiles, cards, player boards, tokens, surprise cards, surprise decks, action costs, and Poulpita panel layout are configured from the admin console.
- Most content is stored in JSON under backend data folders, with images stored separately.
- Admin content can be imported/exported as JSON; images are not exported.

## Core Entities

### Poulpita

Poulpita is the shared protagonist/state object.

Current shared attributes:

- `node_id`: current map node.
- `previous_node_id`: previous node, used by some failure effects.
- `energy`: shared energy.
- `neurons`: shared currency/resource.
- `seashells`: shells carried by Poulpita.
- `size_index`: current size step.
- `size_upgraded_today`: day-phase limit flag.

Poulpita shells are distinct from shells stored at shelters. Tile requirements that consume shells use only shells carried by Poulpita.

### Ability Boards / Players

There are exactly five ability boards:

- `agility`
- `camouflage`
- `force`
- `propulsion`
- `intelligence`

Each board has:

- A name.
- Events/animals it can initiate interactions with.
- A deck definition.
- A hand.
- A draw pile and discard pile.
- AP (`pa`).
- Control-take count for the current night.
- Actions taken during current control.
- Max actions per control.
- Max control takes per night.
- Current and default max hand size.
- Day-phase upgrades.

The current projection exposes all ability data to the frontend. Privacy is marked as not enforced in the projection (`privacy_enforced: false`). However, the intended future bot model should assume each ability bot sees only its own private hand and its public board state unless explicitly given omniscient mode.

### Cards And Interactions

Admin creates interaction types such as `Charge`, `Hide`, etc. Each interaction type generates a card identity for UI/catalog purposes.

Normal cards:

- Have one `interaction_id`.
- Can satisfy one matching required interaction when played into an interaction.

Upgraded/powerful cards:

- Can have `interaction_ids`, currently two options.
- Example: `Charge OR Hide`.
- Backend automatically chooses the interaction option that best satisfies the current interaction requirements when the card is played/confirmed.

Cards are used to satisfy tile requirements and surprise card optional costs.

### Map, Nodes, And Movement

Admin creates maps by uploading an image and placing nodes over it. Nodes have relative positions on the image and adjacency edges.

In game:

- Poulpita is on exactly one node.
- Movement requires target node adjacency validation.
- Move updates `previous_node_id`.
- The board renders the map image, nodes, Poulpita position, shelter tokens, and tile tokens.

### Levels

A level specifies:

- Name.
- Map.
- Starting node for Poulpita.
- Starting energy.
- Starting neurons.
- Night duration in 15-minute steps.
- Surprise deck, optional.
- Objectives.
- For each node: number of tile slots.
- Groups of nodes.
- Tile copies assigned to each group.
- Node tokens, currently shelter and octopus.

At game setup:

- Tiles assigned to each group are shuffled within that group.
- Tiles are distributed into the nodes of that group according to node tile counts.
- Shelter tokens become shelter runtime entries.
- Octopus tokens become face-up special tile instances.

### Tiles

A tile is built from:

- One event/animal.
- Priority number.
- Required interactions for normal success.
- Optional counter-attack required interactions.
- Required number of Poulpita-carried shells for normal success.
- Success effects.
- Counter-attack success effects.
- Failure effects.

Tiles can require no interactions. In that case, they can succeed automatically if other requirements, such as shell requirements, are met.

The tile preview is a hexagon:

- Center: event image.
- Top: required interactions and shell requirements.
- Counter-attack costs are visually distinguished.
- Left: success effects.
- Right: counter-attack effects.
- Bottom: failure effects.

### Categories And Compulsory Tiles

Events/animals belong to categories.

Admin can mark a category as compulsory when on Poulpita’s node.

Rule:

- If multiple compulsory tiles are revealed on Poulpita’s node, the highest priority compulsory tile(s) must be resolved before lower-priority compulsory tiles.
- If there are multiple compulsory tiles at the same highest priority, any of those can be chosen.
- A non-compulsory tile with priority greater than the highest compulsory tile can still be initiated first.
- A non-compulsory tile with priority less than or equal to the highest compulsory tile cannot bypass it.

Octopus token:

- Admin configures an octopus token image and rule data similar to a tile.
- At level setup, an octopus token placed on a node becomes a visible special tile.
- It behaves as a compulsory threat with priority and configured success/failure requirements.

## Tile Visibility

Tiles are initially face-down except explicit visible special tiles such as octopus tokens.

Visibility is updated from Poulpita’s position:

- Same node as Poulpita: all tiles are revealed.
- Adjacent nodes: up to 2 tiles are revealed.
- Distance-2 nodes: up to 1 tile is revealed.
- Revealed tiles remain revealed.

This matters for bots: planning should distinguish known visible tiles from unknown face-down tiles, and should reason about expected risk when moving.

## Night Phase

The game starts in night idle/action flow.

Night state:

- `phase` is `night_idle` or `night_action`.
- `night_time_spent` counts elapsed time in 15-minute chunks.
- `night_time_total` is configured per level.
- `night_shelter_available_at` is currently fixed at 16 chunks, representing 4 hours.

Control:

- A player/ability must take control before most night actions.
- Taking control sets `active_capability_id`.
- Taking control increments that ability’s control-take count.
- Each control has a configured max number of actions.
- Each ability has a configured max number of control takes per night.
- If night time has reached or exceeded `night_time_total`, each further take-control causes 1 energy damage.

Action costs:

Admin configures AP cost and time cost for:

- Gain AP.
- Move.
- Interact.
- Use special power.

Default costs:

- Gain AP: 0 AP, 0 time.
- Move: 1 AP, 1 time step.
- Interact: 1 AP, 2 time steps.
- Special power: 1 AP, 0 time.

Current implementation note:

- Draw action card uses the `special_power` configured cost until actual special powers are implemented.
- Time cost and AP cost are independent.

Overrun:

- When an action advances time past `night_time_total`, Poulpita takes 1 energy damage.
- After overrun, taking control also causes 1 energy damage.
- If Poulpita reaches 0 energy, the game is lost.

Lose condition:

- Poulpita energy reaches 0.
- Or no control takes remain and the current active player has 0 actions.

## Night Actions

### Take Control

Command: `take_control`

Requirements:

- Phase is night idle/action.
- Ability exists.
- Ability is not already active.
- Ability has remaining control takes.

Effects:

- Sets active and focused capability.
- Resets actions taken this control.
- May trigger late-control energy damage if night duration has already been reached.

### Gain AP

Command: `collect_action_points`

Requirements:

- Active capability.
- Action limit not reached.
- Enough AP for configured AP cost, usually 0.

Effects:

- Rolls a 1-6 die.
- Adds that many AP to the active ability.
- Spends configured AP/time/action count.

### Move

Command: `move_poulpita`

Requirements:

- Phase is `night_action`.
- Active capability.
- Action limit not reached.
- Enough AP for configured move cost.
- Target node exists and is adjacent.

Effects:

- Updates previous/current Poulpita node.
- Spends configured AP/time/action count.
- Re-applies tile visibility.

### Draw Action Card

Command: `draw_action_card`

Current rule:

- Uses the `special_power` action cost configuration.
- Requires active capability and action limit.
- If hand is at limit, the player must choose a card to discard before drawing.
- If deck is empty, discard is shuffled back into draw pile automatically.

Effects:

- Draws one card into hand.
- May discard one selected hand card first.
- Spends configured AP/time/action count.

### Interact

Interaction is a two-step flow.

1. Inspect/open tile panel in frontend.
2. `start_interaction` command consumes the interaction action and opens backend interaction state.
3. Players can select/play/withdraw cards.
4. `resolve_interaction` checks requirements.
5. If not ready, backend returns a confirmation event with `success: false` but does not fail the interaction.
6. `fail_interaction` applies failure effects.

Command: `start_interaction`

Requirements:

- Active capability.
- Enough AP for configured interact cost.
- No interaction already active.
- Tile is on Poulpita’s node.
- Tile is face-up.
- Compulsory/priority rules allow selecting it.
- Capability can initiate that event/animal, except octopus token is special and bypasses normal event initiation gating.

Effects:

- Creates `state.interaction`.
- Syncs any selected cards from active player.
- Spends configured AP/time/action count.

Command: `resolve_interaction`

Requirements for success:

- All normal required interactions are satisfied by played cards.
- Required Poulpita-carried shells are available.

Counter-attack:

- Counter-attack succeeds only if normal success succeeds and counter-attack requirements are also satisfied.

Effects on success:

- Required Poulpita-carried shells are consumed.
- Success effects apply.
- Counter-attack effects apply if counter succeeds.
- Tile instance is removed from node.
- Tile visibility is re-applied.
- Win conditions are checked.

Effects on incomplete confirm:

- If requirements are not met, interaction remains active.
- Backend appends an `interaction_cards_confirmed` event with `success: false`.

Command: `fail_interaction`

Effects:

- Applies configured failure effects.
- Re-applies visibility.
- May cause game loss if energy reaches 0.
- Cards already played are discarded after resolution/failure cleanup.

## Day Phase

Day starts by ending the night.

Command: `end_night`

Requirements:

- Phase is `night_action`.
- Active capability.
- Poulpita is on a shelter token.
- At least 16 night time steps have passed.

Effects:

- Phase becomes `day`.
- Night runtime is reset:
  - AP reset to 0.
  - Control counts reset to 0.
  - Actions taken reset to 0.
  - Active capability cleared.
  - Poulpita size-upgraded-today flag reset.

Day actions:

- Move shells between Poulpita and current shelter.
- Buy ability upgrades using shared neurons.
- Buy Poulpita size upgrade using shared energy.
- End day.

### Shelters And Shell Storage

Shelter state per node includes:

- `count`: shelter token count.
- `seashells`: shells stored at that shelter.
- `secure`: true if shelter has at least 3 shells.

During day:

- Clicking a Poulpita shell moves one shell from Poulpita to current shelter.
- Clicking a shelter shell moves one shell back to Poulpita.
- Shells stored in shelters remain on that specific shelter and are not consumed by tile requirements.
- A shelter becomes secure at 3 stored shells.

Secure shelter effect:

- If Poulpita is on a secure shelter, Poulpita size upgrade energy cost is reduced by 1.

### Ability Upgrades

Upgrades are bought during day and cost shared neurons.

Current upgrade types:

1. Hand-size upgrade:
   - Increases current hand size by configured bonus.
   - Can be bought once per listed upgrade.

2. Deck-exchange upgrade:
   - Removes configured counts of normal cards from the ability’s deck/hand/discard/draw pile.
   - Adds configured powerful cards.
   - Powerful cards have two interaction options.
   - Can be bought once per listed upgrade.

### Poulpita Size Upgrade

Admin configures Poulpita size steps in the Poulpita panel page.

Rules:

- Poulpita starts at smallest size.
- During day, Poulpita can grow at most once.
- Growth costs energy from shared Poulpita energy.
- Poulpita cannot spend energy down to 0.
- Secure shelter discount applies if current shelter is secure.
- Size increases can satisfy level objectives.

Command: `end_day`

Effects:

- Phase returns to `night_idle`.
- Day index increments.
- Night time spent resets to 0.
- Ability AP/control/action counters reset.

## Objectives And Win/Loss

Each level can define one or more objectives. All must be completed to win.

Current objective types:

- Increase size X times.
- Find a shelter.
- Secure a shelter.

Objective progress:

- `size_increases`: increments on successful Poulpita growth.
- `found_shelter`: set by shelter placement/finding and shell movement at shelters.
- `secured_shelter`: set when a shelter reaches 3 shells.

Win condition:

- All level objectives are complete.

Loss condition:

- Poulpita energy reaches 0.
- Or no control/action capacity remains under current rules.

## Surprise Cards

Admin can configure surprise cards and surprise decks.

Tiles can have success effect `draw_surprise_card`.

When a surprise card is drawn:

- It becomes `pending_surprise`.
- A panel opens in frontend.
- Player can accept/pay optional cost or skip.

Surprise costs:

- Play one or more cards matching required interactions.
- Pay AP, optionally from a specific ability.

Surprise effects:

- Gain AP on specific ability.
- Gain neurons.
- Advance night track.
- Gain or lose energy.
- Remove all tiles of a category from current node.
- Remove all tiles of a category from adjacent nodes.

If the surprise deck ends, drawing does nothing.

## Commands Relevant To Bots

Bots should propose or issue the same command envelope used by the frontend.

Important command types:

- `select_level`
- `start_goldfish_game`
- `take_control`
- `collect_action_points`
- `move_poulpita`
- `draw_action_card`
- `start_interaction`
- `play_interaction_card`
- `withdraw_interaction_card`
- `resolve_interaction`
- `fail_interaction`
- `move_seashell_to_shelter`
- `move_seashell_from_shelter`
- `buy_hand_size_upgrade`
- `buy_poulpita_size`
- `resolve_surprise_card`
- `end_night`
- `end_day`

Each mutating command must use the expected current `version`.

## State Projection Shape Relevant To Bots

The bot planner should expect to consume something close to `GameProjection`.

Key fields:

- `phase`
- `version`
- `day_index`
- `night_time_spent`
- `night_time_total`
- `night_shelter_available_at`
- `active_capability_id`
- `focused_capability_id`
- `capability_order`
- `capabilities`
- `player_boards`
- `map`
- `poulpita`
- `tiles`
- `shelters`
- `pending_surprise`
- `objectives`
- `objective_progress`
- `tile_catalog`
- `interaction`
- `events`

`tile_catalog` contains:

- Tiles.
- Events.
- Categories.
- Interactions.
- Generated cards.
- Surprise cards/decks.
- Tokens.
- Poulpita panel config.
- Action costs.

## Bot Planning Challenges

### Cooperative Control

Only one ability controls Poulpita at a time, but all abilities may have cards/resources relevant to a shared interaction. The orchestrator must choose:

- Who takes control.
- Whether to use the active control for AP, movement, drawing, interaction, or ending night.
- Whether to switch control to another ability during an interaction to contribute cards.

### Partial Information

Current frontend projection exposes all hands, but intended bot design should support local knowledge:

- Each ability bot knows its own hand, deck config, discard, AP, upgrades, and initiation capabilities.
- Other abilities’ hands may be hidden unless game rules expose them.
- Intelligence currently has always-visible cards in UI behavior, but privacy is not yet enforced server-side.

Potential architecture:

- Ability bots receive redacted projections.
- Orchestrator receives public state plus proposals from each bot, not necessarily raw private hands.
- Human+bot mode may expose bot proposals to the human as recommendations.

### Planning Under Time Pressure

Night time is a scarce resource:

- Movement and interaction can advance time.
- Level-specific night duration changes urgency.
- Ending night requires shelter and 16 time steps.
- Overrun causes energy damage.

Bots should score plans using:

- AP cost.
- Time cost.
- Remaining control actions.
- Remaining control takes.
- Risk of overrun energy damage.
- Need to reveal tiles through movement.
- Need to reach or secure shelters.

### Interaction Feasibility

To evaluate an interaction, a bot should consider:

- Whether active ability can initiate the event.
- Whether compulsory priority rules force another tile first.
- Required interaction IDs.
- Required Poulpita-carried shells.
- Counter-attack requirements and rewards.
- Cards in own hand and known partner contributions.
- Cost/time of initiating.
- Effects of success, counter success, and failure.

For dual cards:

- A bot should treat each powerful card as one card with multiple possible interaction contributions, not as multiple cards.
- Backend auto-selects the useful side, but planner should still avoid double-counting it.

### Resource Allocation

Shared resources:

- Energy.
- Neurons.
- Poulpita-carried shells.

Shelter-local resources:

- Shells stored at each shelter.

Ability-local resources:

- AP.
- Hand.
- Deck/discard.
- Control takes/actions.

Bots need to avoid locally good plans that spend shared resources needed for objectives or survival.

### Day/Night Strategy

Night is about:

- Revealing/resolving tiles.
- Moving.
- Gaining AP.
- Drawing cards.
- Finding/using shelters.
- Avoiding time/energy collapse.

Day is about:

- Storing/retrieving shells.
- Securing shelters.
- Buying ability upgrades.
- Growing Poulpita.
- Starting next night.

The orchestrator may need a multi-day strategy, not only a single-turn greedy policy.

## Suggested Bot Architecture Questions

The next LLM should propose answers to these questions:

1. What should an ability bot’s private input include?
2. What should an ability bot output: ranked atomic actions, short plans, resource bids, or conditional policies?
3. How should the orchestrator compare proposals when they consume shared resources?
4. Should orchestration be centralized, auction-based, deliberative, or tree-search based?
5. How should hidden hands be represented without leaking private cards?
6. How should bots value unknown face-down tiles?
7. How should bots estimate the value of drawing cards versus collecting AP?
8. How should bots decide when to end night versus continue risking overrun?
9. How should bots handle active interactions requiring cards from multiple abilities?
10. How should human players override or approve bot proposals?

## Implementation Integration Points For Bots

Likely backend integration points:

- Add a bot service/module that consumes `GameProjection` or redacted projections.
- Add command generation through the existing command envelope.
- Keep backend reducer authoritative; bots should propose commands, not mutate state.
- Add redaction helpers before giving state to ability bots.
- Add an orchestrator loop that can be invoked on demand or automatically after state changes.
- Log bot proposals and selected plans into `event_log` for explainability.

Likely frontend integration points:

- Show bot proposals in the game UI.
- Let human choose a proposed plan or ask bots to re-plan.
- In mixed human/bot games, show each bot’s public recommendation without exposing hidden hand contents.

Testing requirements for bot implementation:

- Deterministic reducer tests using seeded randomness.
- Snapshot tests for redacted projections.
- Planner unit tests for simple scenarios:
  - choose forced compulsory tile,
  - combine cards across two abilities,
  - preserve shells needed for objective,
  - end night before overrun,
  - buy upgrade during day,
  - decide whether counter-attack is worth extra cards.
- Integration tests ensuring bot-issued commands obey `expected_version` and handle command rejection.

## Current Known Gaps

- Privacy is not enforced server-side yet.
- Multiplayer privacy is conceptually desired but current projection exposes all hands.
- Special powers are not implemented yet; action-cost config reserves a slot for them.
- Bot-specific APIs do not exist yet.
- There is no formal planner state redaction layer.
- There is no policy for human override or proposal voting.
- There is no simulation/search utility around the reducer yet.
- Some implementation docs in `documentation/current_architecture.md` may describe older Astralia-derived distributed internals and should not be treated as complete gameplay documentation for this prototype.
