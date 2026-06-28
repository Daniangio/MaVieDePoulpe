# Poulpita Web Game Backend Architecture Specification

## 1. Purpose

Build a web version of *Ma vie de poulpe* as an authoritative, testable, event-driven game engine with a React-style client. The first implementation must not attempt to implement the full board game. It must first prove the hardest architectural property: a shared board with multiple capability boards, a focused capability panel, deterministic state transitions, and a movement-only goldfishing mode.

The backend must treat the game as a deterministic reducer:

```text
next_state, emitted_events = reduce(current_state, command)
```

The client must never mutate game state directly. It sends commands. The server validates permissions, validates phase legality, applies exactly one command at a time per room, increments the state version, and broadcasts a projected state to each connected client.

## 2. Rulebook Constraints That Shape the Architecture

The game is cooperative but not turn-ordered. Each player controls one or more capability boards. A capability can take control of Poulpita when legal, but the number of control takes per night is limited, and the same capability cannot take control twice in a row.

Poulpita is a shared pawn on a 16-node board. Nodes are grouped into tiers. Movement is between adjacent nodes. Moving reveals hidden marine-life tiles according to distance from the new position.

Each capability board has its own cards, action counter, control-take counter, action options, interaction permissions, and upgrade state. Cards in hand are private information except for collective or explicitly public hands such as Intelligence, depending on the final rule implementation.

Interactions are multi-player transactions. One capability initiates an interaction, then other capabilities may contribute cards. The interaction succeeds only when all required cards are satisfied. Threats can create mandatory resolution blocks that prevent ordinary movement or optional interactions.

Communication restrictions change by level. The architecture must therefore support ephemeral suggestions independently from state-changing commands.

## 3. Critical Design Decisions

### 3.1 Do not implement a traditional game loop

There must be no blocking server loop waiting for the next player. The server exposes commands. Any legal client may submit a command at any time. The room queue serializes these commands.

### 3.2 Do not model tiles and cards through inheritance

Avoid class hierarchies such as `CrabTile`, `MouetteTile`, or `AnalyzeCard`. These will become brittle. Use configuration records for content and a small number of processors for rule categories.

### 3.3 Do not implement a full ECS in the first version

A full ECS would be premature. Use a typed state model and registries for content. Keep the engine modular enough that content can later become more data-driven.

### 3.4 Do not expose raw state directly to clients

The server maintains the authoritative state. Clients receive view projections. In goldfishing mode, the projection may expose all hands and allow active control swapping. In multiplayer mode, each client sees only its own private hand and public summaries of other capability boards.

### 3.5 Treat turnless play as a control lease

Only one capability can be active for state-changing actions at a time. The game feels turnless because anyone can claim control when the phase allows it, but the backend still serializes commands.

## 4. Recommended Stack

Backend:

```text
Python 3.12+
FastAPI
Pydantic v2
pytest
uvicorn
SQLite for early persistence
PostgreSQL for deployment persistence
Redis only when scaling beyond one process
```

Frontend:

```text
React
TypeScript
Vite
Zustand or Redux Toolkit
CSS grid or canvas/SVG board renderer
WebSocket client with HTTP fallback
```

Do not add NetworkX to the runtime engine. The board has 16 nodes. A hand-written adjacency map and bounded BFS are simpler, easier to serialize, and easier to test. NetworkX may be used in development tooling if a map editor is later created.

## 5. Repository Shape

```text
poulpita-web/
  backend/
    app/
      main.py
      api/
        http_routes.py
        websocket_routes.py
      domain/
        ids.py
        enums.py
        state.py
        commands.py
        events.py
        projections.py
      engine/
        reducer.py
        validators.py
        movement.py
        visibility.py
        interaction.py
        day_night.py
        randomness.py
      content/
        abilities.yaml
        levels.yaml
        map.yaml
        tiles.yaml
        cards.yaml
      rooms/
        manager.py
        queue.py
        repository.py
      tests/
        test_movement.py
        test_visibility.py
        test_control.py
        test_projection_privacy.py
        test_interaction_minimal.py
  frontend/
    src/
      app/
      api/
      components/
        BoardView.tsx
        FocusedCapabilityPanel.tsx
        OtherCapabilityStrip.tsx
        HandView.tsx
        CommandLog.tsx
      state/
        gameStore.ts
        selectors.ts
      types/
        game.ts
```

## 6. Runtime Architecture

### 6.1 Room Manager

Each game room owns one authoritative state object, one command queue, one event log, and a set of client sessions.

The room manager receives commands from HTTP or WebSocket, attaches metadata, validates the state version, appends the command to the room queue, waits for reduction, and returns either a success result or a structured rejection.

### 6.2 Per-Room Command Queue

The queue must be single-writer per room. It guarantees that two simultaneous commands cannot mutate the same state in parallel.

For the first implementation, use an in-memory `asyncio.Queue` per room. For later deployment across multiple workers, move the queue to Redis or route all traffic for a room to the same worker.

### 6.3 Reducer

The reducer is the only code allowed to mutate game state. All commands flow through it.

Reducer responsibilities:

```text
validate command schema
validate actor permission
validate phase legality
validate active capability legality
validate resource cost
apply deterministic mutation
consume random outcomes from the random source
increment state version
append domain events
produce new client projections
```

### 6.4 Projection Layer

The projection layer converts the authoritative state into client-specific views.

Projection types:

```text
GoldfishProjection
PlayerProjection
SpectatorProjection
DebugProjection
```

Goldfish projection exposes all capability hands and allows focus swapping. Multiplayer projection exposes the current player's hand, public board state, public capability summaries, and hidden-card counts for other capabilities.

### 6.5 Ephemeral Event Channel

Suggestions, pings, cursor highlights, and communication-limited UI gestures are not state mutations. They are broadcast as ephemeral events and are not stored in the authoritative event log unless telemetry is explicitly enabled.

## 7. Game Modes

### 7.1 Goldfishing Mode

Goldfishing mode is the first playable version. One user controls all capability boards. The user can click any capability board to focus it in the bottom panel. The focused board shows its hand and legal movement command. The user can actively swap the focused capability and move Poulpita.

Goldfishing mode is not multiplayer with relaxed permissions. It is a separate permission mode.

Goldfishing permissions:

```text
can_view_all_hands = true
can_focus_any_capability = true
can_submit_for_focused_capability = true
can_debug_swap_active_capability = true
```

### 7.2 Multiplayer Mode

In multiplayer mode, users are assigned seats. A seat may own one or more capability boards. A user can click another capability board to inspect its public summary, but cannot see its cards and cannot submit commands for it.

Multiplayer permissions:

```text
can_view_own_hands = true
can_view_other_public_boards = true
can_submit_for_owned_capabilities = true
can_submit_for_unowned_capabilities = false
can_debug_swap_active_capability = false
```

### 7.3 Debug Mode

Debug mode is for development only. It may expose all state, seeded randomness, command replay, and forced movement. It must be disabled in normal rooms.

## 8. Core Domain Model

### 8.1 Identifiers

Use stable string IDs everywhere.

```text
room_id
seat_id
user_id
capability_id
node_id
tile_instance_id
tile_config_id
card_instance_id
card_config_id
command_id
event_id
```

Do not use array indexes as identity.

### 8.2 GameState

```text
GameState
  room_id
  mode
  version
  phase
  level_id
  day_index
  night_time_spent
  active_capability_id
  last_active_capability_id
  pending_blocker
  map
  poulpita
  capabilities
  decks
  active_transaction
  objective_state
  rng_state
  event_log_cursor
```

### 8.3 MapState

```text
MapState
  nodes: Record<NodeId, NodeState>
  adjacency: Record<NodeId, NodeId[]>
```

### 8.4 NodeState

```text
NodeState
  id
  tier
  hidden_tile_instance_ids
  revealed_tile_instance_ids
  shelter
  shell_count
  octopus_token_count
```

### 8.5 PoulpitaState

```text
PoulpitaState
  node_id
  previous_node_id
  energy
  size_step
  carried_shells
  learning_points
```

### 8.6 CapabilityState

```text
CapabilityState
  id
  owner_seat_id
  pa
  max_hand_size
  control_takes_this_night
  actions_taken_this_control
  special_unlocked
  special_primed
  hand_card_instance_ids
  deck_card_instance_ids
  discard_card_instance_ids
```

### 8.7 TileInstance

```text
TileInstance
  instance_id
  config_id
  status
```

Allowed status values:

```text
hidden
revealed
removed
resolved
```

### 8.8 InteractionTransaction

```text
InteractionTransaction
  transaction_id
  tile_instance_id
  node_id
  initiator_capability_id
  required_card_tags
  counter_required_card_tags
  played_card_instance_ids_by_capability
  stage
  can_counter_attack
```

Allowed stage values:

```text
main_interaction
counter_attack
resolved_success
resolved_failure
cancelled
```

## 9. Content Configuration

### 9.1 Map Configuration

```yaml
nodes:
  1A:
    tier: 1
    adjacent: [1B, 1C]
  1B:
    tier: 1
    adjacent: [1A, 2A]
```

The map file must be validated on load:

```text
all adjacency is symmetric
all node IDs are unique
all tiers are valid
all adjacent node IDs exist
starting nodes used by levels exist
```

### 9.2 Tile Configuration

```yaml
tiles:
  plancton_1:
    name: Plancton 1
    category: prey
    threat_family: none
    placement_tiers_by_level:
      0: [1, 2]
    initiating_capabilities: [intelligence]
    required_card_tags: [analyze, charge]
    rewards:
      energy: 1
      learning_points: 0
      shells: 0
    failure:
      energy_loss: 0
      pa_loss_mode: none
      learning_loss: 0
      shell_loss: 0
      tile_outcome: remove
      poulpita_outcome: none
```

Avoid `Dict[int, ...]` assumptions in JSON. YAML and JSON loaders often parse keys differently. Normalize level keys during content loading.

### 9.3 Card Configuration

```yaml
cards:
  analyze:
    name: Analyser
    tag: analyze
    public: false
  charge:
    name: Charger
    tag: charge
    public: false
```

Do not encode tile-specific logic inside card classes. Cards satisfy required tags. Tile processors decide what happens.

### 9.4 Ability Configuration

```yaml
abilities:
  intelligence:
    name: Intelligence
    collective: true
    default_max_hand_size: 3
    visible_hand: true
    initiates_categories: [exploration]
    special_action: reveal_adjacent_hidden_tile
  agility:
    name: Agilité
    collective: false
    default_max_hand_size: 3
    visible_hand: false
    special_action: let_another_capability_draw
```

The final `initiates_categories` and tile permissions must come from the rulebook's capability sheets and tile definitions. During MVP, movement does not need these permissions.

## 10. State Phases

Use explicit phases. Do not rely on null fields to imply phase.

```text
setup
night_idle
night_action
mandatory_threat
interaction_open
day
game_over
```

### 10.1 setup

The room exists but the level has not started.

Legal commands:

```text
start_goldfish_game
start_multiplayer_game
join_room
assign_capability
```

### 10.2 night_idle

No capability currently controls Poulpita.

Legal commands:

```text
claim_control
suggest
focus_capability
```

### 10.3 night_action

One capability controls Poulpita and may perform actions until it releases control or reaches the action limit.

Legal commands:

```text
move_poulpita
collect_pa
draw_card
initiate_interaction
release_control
suggest
focus_capability
```

### 10.4 mandatory_threat

A revealed threat blocks movement and optional interactions.

Legal commands:

```text
initiate_interaction_with_blocking_threat
collect_pa
draw_card
release_control
claim_control
suggest
focus_capability
```

The exact legality of releasing and claiming control in this phase must enforce that the next active capability is allowed to address the threat or that the game can apply automatic failure when no capability can address it.

### 10.5 interaction_open

A transaction is waiting for cards.

Legal commands:

```text
play_interaction_card
pass_interaction_response
resolve_interaction_when_ready
suggest
focus_capability
```

### 10.6 day

Poulpita is in day phase.

Legal commands:

```text
deposit_shells
upgrade_capability
increase_size
end_day
suggest
focus_capability
```

### 10.7 game_over

The game has ended.

Legal commands:

```text
restart_level
create_next_level_from_checkpoint
export_campaign_sheet
```

## 11. Command Envelope

Every client command must use the same envelope.

```json
{
  "command_id": "cmd_...",
  "room_id": "room_...",
  "actor_user_id": "user_...",
  "actor_seat_id": "seat_...",
  "expected_version": 12,
  "type": "move_poulpita",
  "payload": {
    "capability_id": "agility",
    "target_node_id": "1C"
  }
}
```

If `expected_version` does not match, the server rejects with `state_version_conflict` and returns the current projected state.

## 12. Core Commands

### 12.1 start_goldfish_game

Creates a room state for one user controlling all capability boards.

Validation:

```text
state.phase is setup
actor is room owner
level exists
map config validates
```

Effects:

```text
initialize map
initialize Poulpita
initialize capability boards
initialize decks
place hidden tiles if content is enabled
set phase to night_idle
set version to 1
```

### 12.2 focus_capability

Client-side focus should normally be local UI state. The backend only needs this command if the focused capability should be synchronized across devices or used in debug replay.

For MVP, implement focus locally on the client.

### 12.3 debug_swap_active_capability

Goldfishing-only convenience command.

Validation:

```text
mode is goldfish
phase is night_idle or night_action
capability exists
```

Effects:

```text
set active_capability_id to selected capability
set phase to night_action
```

This command must not exist in multiplayer rooms.

### 12.4 claim_control

Validation:

```text
phase is night_idle
capability exists
actor can control capability
capability is not last_active_capability_id
capability.control_takes_this_night < 3
```

Effects:

```text
active_capability_id = capability_id
phase = night_action
capability.control_takes_this_night += 1
capability.actions_taken_this_control = 0
```

### 12.5 release_control

Validation:

```text
phase is night_action or mandatory_threat
active_capability_id is not null
actor can control active capability
active capability has taken at least 1 action unless debug mode is enabled
```

Effects:

```text
last_active_capability_id = active_capability_id
active_capability_id = null
phase = night_idle unless a mandatory blocker remains
```

### 12.6 move_poulpita

Validation:

```text
phase is night_action
actor can control active capability
payload.capability_id equals active_capability_id
capability has at least 1 PA
capability.actions_taken_this_control < 3
target node is adjacent to current Poulpita node
no mandatory threat is unresolved on the current node
```

Effects:

```text
capability.pa -= movement_cost
capability.actions_taken_this_control += 1
night_time_spent += movement_cost_time_units
poulpita.previous_node_id = current node
poulpita.node_id = target node
reveal tiles from target node visibility rule
resolve automatic surprise triggers if enabled
set mandatory_threat if revealed threats require resolution
emit movement and reveal events
```

For Phase 1 and Phase 2, omit PA, night time, surprise triggers, and mandatory threats. Movement only changes the current node and records the previous node.

### 12.7 draw_card

Validation:

```text
phase is night_action or mandatory_threat
actor can control active capability
capability has at least 1 PA
capability.actions_taken_this_control < 3
hand is not full or payload.discard_card_instance_id is provided
```

Effects:

```text
pay PA
increment action count
move top deck card to hand
shuffle discard into deck if deck is empty
```

### 12.8 initiate_interaction

Validation:

```text
phase is night_action or mandatory_threat
actor can control active capability
tile is revealed on Poulpita node
tile can be initiated by active capability
capability has at least 1 PA
capability has at least one playable required card unless special effects override it
```

Effects:

```text
pay PA
increment action count
create active_transaction
move played initiator card into transaction
set phase to interaction_open
```

### 12.9 play_interaction_card

Validation:

```text
phase is interaction_open
actor can control submitting capability
card is in submitting capability hand
card tag satisfies an unsatisfied requirement in the active transaction
```

Effects:

```text
move card from hand to transaction
if transaction complete, resolve interaction
```

## 13. Movement and Visibility MVP

The first real gameplay loop should implement only this subset:

```text
start_goldfish_game
select focused capability locally
move_poulpita
undo_last_command in debug mode
```

Initial map state:

```text
16 nodes
Poulpita starts on configured node
all nodes visible as board spaces
no tiles required in Phase 1
```

Phase 2 map state:

```text
each node may contain hidden placeholder tile IDs
movement reveals tiles on destination and nearby nodes
revealed tile IDs are displayed but have no effects
```

Visibility processor:

```text
compute shortest path distance from Poulpita node up to depth 2
at distance 0 reveal up to 2 hidden tiles
at distance 1 reveal up to 1 hidden tile
at distance 2 or greater reveal 0 for movement visibility
```

For setup placement, use the rulebook placement visibility separately:

```text
adjacent to Poulpita reveal 2
one step beyond adjacent reveal 1
two or more steps away reveal 0
```

Keep these as two named processors to avoid confusing initial setup visibility with post-movement reveal behavior.

## 14. Privacy Model

### 14.1 Public State

Public state includes:

```text
room metadata
game phase
level
day index
night time spent
Poulpita position
Poulpita energy
Poulpita size
Poulpita carried shells
Poulpita learning points
map topology
revealed tiles
hidden tile counts per node
shelter and shell tokens on nodes
active capability
last active capability
public summary of each capability board
objective progress
command log summaries
```

### 14.2 Private Capability State

Private state includes:

```text
hand card IDs
deck order
debug-only random seed details
```

### 14.3 Public Capability Summary

```text
capability id
owner seat
PA count
hand size
max hand size
deck count
discard count
control takes this night
actions taken this control
special unlocked
special primed
```

### 14.4 Goldfish Exception

Goldfish projection includes all private capability states and should be clearly marked:

```text
projection_mode = goldfish
privacy_enforced = false
```

This prevents accidental reuse of goldfish projection in multiplayer.

## 15. UI Layout Specification

The UI must be designed around the separation between shared board state and focused capability state.

### 15.1 Main Board Area

The center of the screen contains the board. Each node shows:

```text
node ID
Poulpita marker if present
revealed tile cards or icons
hidden tile count
shelter token if present
shell count if present
octopus token count if present
legal move highlight when focused capability can move
```

### 15.2 Top Capability Strip

Other capability boards are shown as reduced panels aligned above the board.

Each reduced panel shows:

```text
capability name
owner
PA
hand size without card identities
control takes this night
actions used in current control
special state
active marker if it controls Poulpita
```

Clicking a panel changes the focused capability shown in the bottom panel. In multiplayer, this changes only inspection focus and does not grant authority.

### 15.3 Bottom Focused Capability Panel

The bottom panel shows the selected capability board.

Goldfish view:

```text
full hand
PA
available commands
move button for legal adjacent nodes
control/debug buttons
```

Multiplayer own-board view:

```text
full hand
PA
available legal commands
claim or release control when legal
```

Multiplayer other-board view:

```text
public summary
hidden hand count
suggestion buttons
no card identities
no action buttons except allowed pings
```

### 15.4 Command Feedback

Every submitted command must produce one of:

```text
accepted with new state version
rejected with machine-readable reason
state_version_conflict with current projection
```

The UI must show rejected commands as normal game feedback, not as application errors.

## 16. HTTP and WebSocket API

### 16.1 HTTP Routes

```text
POST /rooms
POST /rooms/{room_id}/join
GET /rooms/{room_id}/state
POST /rooms/{room_id}/commands
GET /rooms/{room_id}/events
```

### 16.2 WebSocket Routes

```text
WS /rooms/{room_id}/ws
```

Client to server messages:

```text
command
suggestion
ping
request_projection
```

Server to client messages:

```text
state_projection
command_accepted
command_rejected
domain_events
ephemeral_event
presence_update
```

### 16.3 Command Rejection Shape

```json
{
  "ok": false,
  "command_id": "cmd_...",
  "reason": "not_active_capability",
  "message": "Only the active capability can move Poulpita.",
  "current_version": 13
}
```

The `reason` field must be stable. The `message` field can be user-facing text.

## 17. Randomness

All random outcomes must be server-side and reproducible.

State stores:

```text
rng_seed
rng_counter
```

Every random operation consumes one deterministic draw and emits a domain event:

```text
random_drawn
  purpose
  result
  rng_counter_before
  rng_counter_after
```

Do not use client-side randomness for dice, tile placement, shuffling, or surprise cards.

## 18. Persistence

### 18.1 Early Version

Use in-memory rooms plus optional JSON snapshot export.

### 18.2 Testable Persistence

Persist:

```text
room metadata
latest state snapshot
event log
command log
content version
created_at
updated_at
```

### 18.3 Replay

A saved game must be reproducible by replaying commands from initial state under the same content version and random seed.

Replay test:

```text
load initial state
apply command log
compare final state to saved snapshot
```

## 19. Testing Strategy

### 19.1 Unit Tests

Each processor gets pure unit tests:

```text
movement adjacency
visibility reveal counts
control claim legality
release control legality
private projection masking
card draw from deck
interaction requirement matching
mandatory threat priority
```

### 19.2 Reducer Tests

Reducer tests apply command sequences and assert full state deltas.

Example movement test:

```text
given Poulpita on 1A
and active capability is agility
and 1B is adjacent to 1A
when move_poulpita targets 1B
then Poulpita node is 1B
and previous node is 1A
and version increments by 1
and movement event is emitted
```

### 19.3 Projection Tests

Projection tests are mandatory before any multiplayer feature.

Goldfish projection test:

```text
all capability hands are visible
projection mode is goldfish
privacy_enforced is false
```

Multiplayer projection test:

```text
own hand is visible
other hands are hidden
other hand sizes are visible
other deck orders are hidden
```

### 19.4 Scenario Tests

Scenario tests encode rulebook flows as command sequences. Start with movement-only scenarios, then Level 0 scenarios.

Scenario files:

```text
tests/scenarios/goldfish_movement_only.yaml
tests/scenarios/visibility_reveal.yaml
tests/scenarios/control_claim_release.yaml
tests/scenarios/level0_basic_hunt.yaml
```

## 20. Development Phases

### Phase 0: Skeleton and Contracts

Goal:

```text
Create project structure, shared types, command envelope, and an empty room lifecycle.
```

Deliverables:

```text
FastAPI app starts
React app starts
create room endpoint works
WebSocket connects
state projection returns setup state
pytest and frontend tests run in CI
```

Acceptance tests:

```text
creating a room returns room_id
joining a room returns seat_id
requesting state returns version 0
invalid command returns structured rejection
```

### Phase 1: Map-Only Goldfish

Goal:

```text
Render the 16-node board and move Poulpita with one selected capability.
```

Backend scope:

```text
GameState with map and Poulpita only
start_goldfish_game
move_poulpita
adjacency validation
state versioning
movement events
```

Frontend scope:

```text
board renderer
Poulpita marker
click adjacent node to move
command rejection display
```

Acceptance tests:

```text
Poulpita cannot move to a non-adjacent node
Poulpita can move to an adjacent node
state version increments after movement
movement event is broadcast
client board updates after movement
```

### Phase 2: Focused Capability UI Without Cards

Goal:

```text
Implement player-board layout before implementing cards.
```

Backend scope:

```text
capability states without decks
public capability summaries
goldfish projection
```

Frontend scope:

```text
top reduced capability panels
bottom focused capability panel
click top panel to focus it
focused panel changes legal command source
```

Acceptance tests:

```text
all five capabilities render
clicking a capability focuses it in the bottom panel
movement command uses focused capability in goldfish mode
other panels remain reduced
```

### Phase 3: Hidden and Revealed Tiles Without Effects

Goal:

```text
Represent hidden and revealed tile placeholders and test visibility.
```

Backend scope:

```text
NodeState hidden_tile_instance_ids
NodeState revealed_tile_instance_ids
visibility processor
movement-triggered reveal
```

Frontend scope:

```text
hidden tile count per node
revealed tile placeholders
reveal animation or event log entry
```

Acceptance tests:

```text
movement reveals up to 2 tiles on destination
movement reveals up to 1 tile on adjacent nodes if configured
hidden counts decrease
revealed counts increase
revealed tiles persist after leaving node
```

### Phase 4: Control Lease and Action Accounting

Goal:

```text
Replace debug movement with rule-shaped control taking.
```

Backend scope:

```text
night_idle and night_action phases
claim_control
release_control
max 3 takes per night
cannot take control twice in a row
1 to 3 actions per control
movement consumes one action
```

Frontend scope:

```text
claim control button
release control button
active capability marker
actions-used display
control-takes display
```

Acceptance tests:

```text
capability can claim control from night_idle
same capability cannot claim twice in a row
capability cannot exceed 3 takes per night
movement rejected if no active capability
movement rejected if actor does not control active capability in multiplayer projection tests
```

### Phase 5: PA Resource and Night Time

Goal:

```text
Movement consumes PA and advances night time.
```

Backend scope:

```text
PA counts
movement cost
night_time_spent
collect_pa with deterministic die result
```

Frontend scope:

```text
PA display
night time track
collect PA button
```

Acceptance tests:

```text
movement fails with insufficient PA
movement decrements PA
movement advances night time
collect PA uses server-side deterministic randomness
```

### Phase 6: Cards and Privacy

Goal:

```text
Implement capability hands, decks, and multiplayer-safe projections.
```

Backend scope:

```text
card config loading
deck state
hand state
draw_card command
hand size limit
projection masking
```

Frontend scope:

```text
own hand display
goldfish all-hands display
other player hidden hand count
```

Acceptance tests:

```text
goldfish sees all hands
multiplayer user sees only owned hands
other hands expose only counts
card draw moves one card from deck to hand
full hand requires discard or rejects draw
```

### Phase 7: Minimal Interaction Transaction

Goal:

```text
Resolve one simple prey tile from Level 0.
```

Backend scope:

```text
initiate_interaction
play_interaction_card
required_card_tags matching
success reward
failure shell for incomplete transaction if needed
remove resolved tile
```

Frontend scope:

```text
click revealed tile
show required cards
play card from focused hand
show transaction status
```

Acceptance tests:

```text
only allowed capability can initiate tile interaction
initiator must play at least one required card
other capability can contribute required card
success removes tile and grants reward
played cards leave hands
```

### Phase 8: Mandatory Threats and Movement Blocking

Goal:

```text
Implement movement consequences when a threat is revealed.
```

Backend scope:

```text
threat ordering
mandatory_threat phase
blocking movement while threat unresolved
automatic surprise placeholder hook
failure consequences subset
```

Frontend scope:

```text
threat blocker banner
legal response buttons
blocked movement feedback
```

Acceptance tests:

```text
revealed threat creates blocker
movement is rejected while blocker exists
collect PA and draw card remain legal while blocked
resolving threat clears blocker
```

### Phase 9: Day Phase and Level 0 Loop

Goal:

```text
Complete a playable tutorial loop with movement, cards, interactions, energy, and size increase.
```

Backend scope:

```text
end_night for Level 0
increase_size
energy cost
objective progress
victory and defeat check
end_day reset
```

Frontend scope:

```text
energy track
size track
objective card display
day phase panel
victory and defeat modal
```

Acceptance tests:

```text
energy increases after successful prey interaction
size increase consumes energy
Level 0 victory triggers after required size increases
defeat triggers if energy cannot satisfy required size increase at night end
```

### Phase 10: Multiplayer Room

Goal:

```text
Make the movement-only and Level 0 flows work with multiple users and privacy.
```

Backend scope:

```text
seat assignment
capability ownership
permission validation
client-specific projections
WebSocket broadcasts per projection
suggestion ephemeral events
```

Frontend scope:

```text
join room screen
seat assignment UI
own vs other capability states
suggestion pings
```

Acceptance tests:

```text
user cannot move using unowned capability
user can inspect other public boards
user cannot see other hands
suggestion event broadcasts without state version increment
simultaneous move commands serialize correctly
losing command receives rejection or version conflict
```

## 21. LLM Development Instructions

When using an LLM coding agent, give it one phase at a time. Do not ask it to implement the full game in one pass.

For each phase, require:

```text
updated backend code
updated frontend code when needed
unit tests
scenario tests when relevant
manual run instructions
short summary of changed files
known limitations
```

The LLM must not:

```text
skip tests
store private hands in public projections
let the client mutate state locally
use blocking loops for game flow
hardcode tile effects inside UI components
combine debug goldfish permissions with multiplayer permissions
implement full ECS before Phase 7
```

## 22. First LLM Task Prompt

Use this prompt for the first implementation pass:

```text
Implement Phase 0 and Phase 1 only.

Build a FastAPI backend and React TypeScript frontend for a goldfishing prototype of Ma vie de poulpe.

Backend requirements:
- Create a room.
- Start a goldfish game.
- Store one authoritative in-memory GameState per room.
- Represent a 16-node board from a map config file.
- Represent Poulpita position and previous position.
- Accept move_poulpita commands through a standard command envelope.
- Validate adjacency.
- Increment state version after every accepted command.
- Return structured command rejections.
- Broadcast state projections over WebSocket.
- Include pytest tests for room creation, adjacency movement, non-adjacent rejection, and version increments.

Frontend requirements:
- Connect to a room.
- Render the 16-node board.
- Show Poulpita on the current node.
- Allow clicking adjacent nodes to submit move_poulpita.
- Show command rejection messages.
- Update board from WebSocket state projections.

Do not implement cards, PA, interactions, day phase, tile effects, or multiplayer privacy yet.
```

## 23. Final Architecture Check

A phase is not complete until these questions are answered positively:

```text
Can the current state be serialized to JSON?
Can the command be replayed from a known initial state?
Does every accepted command increment the version?
Does every rejected command preserve the version?
Can the UI recover by requesting a fresh projection?
Are private fields absent from multiplayer projections?
Is goldfish behavior impossible to access from a multiplayer room?
Are all random outcomes generated by the server?
```
