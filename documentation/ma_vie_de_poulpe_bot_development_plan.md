# Ma Vie de Poulpe — Solo Human + Three Bots Development Plan

## Purpose

Implement a first bot-assisted solo mode for **Ma Vie de Poulpe** in the existing FastAPI/React web game.

The initial mode has:

- **One human player**.
- **Three bot players**.
- Four player seats mapped to the four non-collective abilities:
  - Agility
  - Camouflage
  - Force
  - Propulsion
- **Intelligence remains a shared collective ability**, not a fifth player seat.
- The human chooses one of the four player abilities at setup.
- The other three abilities are assigned to bots.
- Bots propose short, conditional team plans.
- The human acts as the **orchestrator**: they open a panel over the board, inspect the proposed plans, and click one to authorize it.
- After authorization, the backend executes all commands belonging to that plan until:
  - the plan completes;
  - the plan becomes invalid;
  - new information creates a meaningful decision point;
  - a private human choice is required;
  - a command is rejected;
  - or the human cancels execution.

The bot system must use the existing game commands and authoritative reducer. It must never mutate `GameState` directly.

This document is intended as an implementation specification for a coding LLM. The “LLM” is the development agent, **not a runtime dependency**. The first bot implementation should be deterministic and algorithmic, with seeded stochastic evaluation added later.

---

# 1. Product Behaviour

## 1.1 Solo game setup

Add a game mode such as:

```text
solo_with_bots
```

During setup, the human selects their ability:

```text
agility | camouflage | force | propulsion
```

The remaining three abilities become bot-controlled.

Example:

```text
Human: Agility
Bot 1: Camouflage
Bot 2: Force
Bot 3: Propulsion
Shared: Intelligence
```

Do not treat Intelligence as a fifth autonomous player. Intelligence is a shared board whose public cards and actions can be considered by the team planner and used during plan execution according to the game rules.

The mode should preserve the existing goldfish mode and avoid breaking current rooms.

## 1.2 Human role

The human has two roles:

1. They directly control their selected ability when acting manually.
2. They act as team orchestrator by choosing among bot-proposed plans.

The human must always be allowed to:

- close the plan panel;
- ignore all proposals and play manually;
- request new proposals;
- cancel an executing plan;
- inspect why a plan stopped;
- resume manual play after a plan ends or is invalidated.

## 1.3 Proposal overlay

Add a closable overlay panel that visually covers the game board, while leaving the surrounding interface and player boards available where practical.

The panel contains:

- current phase and relevant urgency;
- three to five ranked plans;
- proposer identity;
- plan title;
- short rationale;
- expected public costs;
- expected outcome;
- risk label;
- a concise step preview;
- an **Execute plan** button;
- a **Recalculate plans** button;
- a close button.

Example:

```text
Camouflage: Resolve the moray threat
High priority · Moderate risk

Plan:
1. Camouflage takes control
2. Camouflage starts the interaction
3. Bot abilities contribute available cards
4. Resolve if requirements are complete

Expected public cost:
1 AP · 2 night steps · 1 control take

Why:
This is the highest-priority compulsory tile. Leaving it unresolved
blocks lower-priority interactions.

[Execute plan]
```

The UI must not expose exact private bot cards. It may say:

```text
Bot support is likely
```

or:

```text
At least one bot has committed support
```

but not:

```text
Force holds Charge
```

unless an explicit omniscient/debug mode is enabled.

## 1.4 Plan execution

Clicking a proposal authorizes a complete **option**, not merely one atomic action.

A plan may execute several commands, for example:

```text
take_control(camouflage)
collect_action_points(camouflage)
start_interaction(tile_17)
play_interaction_card(bot force, card ...)
play_interaction_card(bot intelligence, card ...)
resolve_interaction()
```

Every command must:

- be issued through the existing command envelope;
- use the current room version as `expected_version`;
- be validated by the authoritative reducer;
- produce normal state changes and WebSocket projections;
- be recorded in the normal event history;
- additionally produce bot-execution events for explainability.

The executor must not assume that a precomputed sequence remains valid. After every accepted command, it reads the updated state and checks the plan continuation policy.

## 1.5 When execution must stop

A plan stops with one of these statuses:

```text
completed
replan_required
human_input_required
invalidated
command_rejected
cancelled
game_finished
```

### Stop and request a new plan when

- movement reveals new tiles;
- a new compulsory threat appears;
- a surprise card is drawn;
- a die roll materially changes available resources;
- a card draw changes interaction feasibility;
- an interaction succeeds or fails;
- the day/night phase changes;
- an objective is completed;
- a planned resource is no longer available;
- a better safety-critical plan becomes necessary;
- the plan reaches its declared terminal condition.

Not every version change invalidates a plan. Commands belonging to the selected plan naturally increment the room version.

### Pause for human input when

- the human’s private hand may need to contribute a card;
- a full human hand requires choosing a discard;
- a surprise cost requires a human-private decision;
- the plan asks the human ability to initiate an action not previously authorized;
- multiple materially different branches require player judgement.

In the first implementation, do not let a bot inspect or automatically play the human’s private hand.

---

# 2. Architectural Principles

## 2.1 Keep the reducer authoritative

The gameplay source of truth remains the existing backend reducer, currently centered around:

```text
backend/app/game_room_service.py
```

The bot subsystem must:

- inspect state;
- build observer-specific projections;
- propose plans;
- issue normal commands;
- observe reducer results.

It must not duplicate game-rule mutations.

Avoid writing bot-only implementations of movement, interaction resolution, AP spending, tile effects, objectives, or phase changes. Bot simulations should eventually call the same pure transition logic as live commands.

## 2.2 Separate four layers

Implement four distinct layers:

```text
Observer projection
    ↓
Ability planners
    ↓
Team proposal aggregation
    ↓
Plan executor
```

### Observer projection

Produces the state an individual bot is legally allowed to know.

### Ability planner

Generates a small number of short plans from one ability’s local perspective.

### Proposal aggregation

Deduplicates, evaluates, ranks, and presents team options. In version 1 the human, not an autonomous orchestrator, makes the final selection.

### Plan executor

Turns the chosen conditional plan into validated commands, one command at a time.

## 2.3 Plans, not long scripts

The planning unit is an **option**: a short goal-directed policy with:

- preconditions;
- a first command;
- expected costs;
- continuation rules;
- completion conditions;
- invalidation conditions.

Do not generate large fixed command arrays extending far into unknown future states.

Good option examples:

```text
Resolve visible compulsory tile
Move to an adjacent node and inspect what is revealed
Collect AP for a specific ability
Draw toward a required interaction
Return toward the shelter
End the night safely
Secure the current shelter
Grow Poulpita
Buy an ability upgrade
```

## 2.4 One shared team objective

Bot abilities must not have selfish scores. They share one team value function.

Abilities differ because they have different:

- private hands;
- AP;
- control limits;
- initiation permissions;
- decks;
- upgrades;
- available actions.

They should not receive rewards for “using their own ability.”

---

# 3. Backend Design

## 3.1 Suggested module structure

Create a dedicated package:

```text
backend/app/bots/
    __init__.py
    models.py
    room_bot_state.py
    observers.py
    beliefs.py
    legal_actions.py
    proposals.py
    scoring.py
    planner.py
    executor.py
    invalidation.py
    serialization.py
    api.py

    generators/
        __init__.py
        common.py
        night.py
        interactions.py
        exploration.py
        return_to_shelter.py
        day.py

    tests/
        test_observers.py
        test_legal_actions.py
        test_proposals.py
        test_executor.py
        test_invalidation.py
```

Adapt naming to the existing project conventions rather than forcing this exact layout.

## 3.2 Seat assignment model

Add a room-level configuration separate from the core game rules:

```python
from typing import Literal
from pydantic import BaseModel

AbilityId = Literal[
    "agility",
    "camouflage",
    "force",
    "propulsion",
    "intelligence",
]

ControllerType = Literal["human", "bot", "shared"]


class AbilityController(BaseModel):
    ability_id: AbilityId
    controller_type: ControllerType
    seat_id: str | None = None


class BotRoomConfig(BaseModel):
    mode: Literal["solo_with_bots"]
    human_ability_id: AbilityId
    controllers: list[AbilityController]
    privacy_mode: Literal[
        "solo_faithful",
        "omniscient_debug",
    ] = "solo_faithful"
```

Validation:

- `human_ability_id` must be one of the four non-Intelligence abilities.
- Exactly one non-Intelligence ability is human-controlled.
- Exactly three non-Intelligence abilities are bot-controlled.
- Intelligence is always `shared`.

Do not bind bot identity to ability identity too deeply. Future modes may assign multiple abilities to one player.

## 3.3 Bot runtime state

Do not put transient planning caches inside the canonical gameplay state unless replay persistence requires it.

Create a room-keyed bot runtime object:

```python
class BotRoomState(BaseModel):
    room_id: str
    config: BotRoomConfig

    proposal_set_id: str | None = None
    proposals_generated_from_version: int | None = None
    proposals: list["PlanProposal"] = []

    active_execution: "PlanExecutionState | None" = None

    last_public_belief_fingerprint: str | None = None
    bot_status: Literal[
        "idle",
        "planning",
        "awaiting_selection",
        "executing",
        "awaiting_human",
        "error",
    ] = "idle"
```

For the prototype this may live in the same runtime store as rooms. Preserve a clean interface so it can later be stored in Redis.

## 3.4 Observer-specific projections

Implement:

```python
def build_bot_observation(
    game_state: GameState,
    observer_ability_id: str,
    bot_config: BotRoomConfig,
) -> BotObservation:
    ...
```

A bot observation contains:

- all public game state;
- exact private state for the observing ability;
- public Intelligence hand/state;
- hidden placeholders for other abilities’ hands;
- known deck definitions;
- known hand sizes;
- known discard piles if rules make them public;
- action history;
- belief summaries derived only from legal information.

Implement a separate public projection:

```python
def build_public_planning_observation(
    game_state: GameState,
    bot_config: BotRoomConfig,
) -> PublicPlanningObservation:
    ...
```

The proposal aggregator should not automatically receive all bot hands.

### Required privacy tests

For each ability:

- snapshot the observation;
- assert its exact hand is present;
- assert other private hands are absent;
- assert public hand sizes remain present;
- assert Intelligence visibility follows the intended rule;
- assert card identifiers cannot leak through nested fields or event metadata.

## 3.5 Legal primitive actions

Expose a pure helper:

```python
def enumerate_legal_commands(
    state: GameState,
    actor_ability_id: str,
    observer: BotObservation | None = None,
) -> list[LegalCommandTemplate]:
    ...
```

It should enumerate legal primitives such as:

- take control;
- collect AP;
- move to each adjacent node;
- draw, including legal discard candidates for bot hands;
- initiate each currently legal tile interaction;
- play or withdraw each legal bot card during an interaction;
- resolve or fail an interaction;
- legal surprise decisions;
- legal day actions;
- end night;
- end day.

Do not enumerate all multi-action combinations here.

Reuse existing validation functions where possible. The reducer remains the final validator.

## 3.6 Proposal data model

Use separate backend-private and frontend-safe representations.

```python
class ResourceEstimate(BaseModel):
    ap_by_ability: dict[str, float] = {}
    time_steps: float = 0
    control_takes_by_ability: dict[str, float] = {}
    energy_delta_expected: float = 0
    shells_delta_expected: float = 0
    neurons_delta_expected: float = 0


class PublicPlanSummary(BaseModel):
    plan_id: str
    proposer_ability_id: str | None
    title: str
    rationale: str
    risk_label: Literal["low", "moderate", "high", "forced"]
    confidence: float | None = None
    step_preview: list[str]
    expected_resources: ResourceEstimate
    objective_effect: str | None = None
    warnings: list[str] = []


class PlanProposal(BaseModel):
    plan_id: str
    proposal_set_id: str
    created_from_version: int

    owner_ability_id: str | None
    intent: str
    public_summary: PublicPlanSummary

    preconditions: list["PlanPredicate"]
    completion_conditions: list["PlanPredicate"]
    invalidation_conditions: list["PlanPredicate"]
    replanning_triggers: set[str]

    execution_graph: "PlanExecutionGraph"

    expected_resources: ResourceEstimate
    hard_safety_passed: bool
    score: float
    risk_score: float

    # Never serialize this into the normal frontend response.
    private_basis: dict | None = None
```

`private_basis` may contain facts such as exact bot-card support. It must be filtered from client serialization.

## 3.7 Plan execution graph

Version 1 can use a small directed graph rather than a general workflow engine.

```python
class PlanStep(BaseModel):
    step_id: str
    kind: Literal[
        "command",
        "bot_card_contribution",
        "check",
        "stop",
    ]

    actor_ability_id: str | None = None
    command_type: str | None = None
    payload_template: dict = {}

    condition: "PlanPredicate | None" = None

    next_on_success: str | None = None
    next_on_false: str | None = None
    next_on_rejection: str | None = None


class PlanExecutionGraph(BaseModel):
    first_step_id: str
    steps: dict[str, PlanStep]
```

Keep predicates declarative and narrow:

```text
active ability is X
tile T still exists
tile T is currently legal
AP >= cost
night time below threshold
interaction active for tile T
requirements complete
human contribution may be needed
phase is night/day
objective not already complete
```

Do not use `eval` or arbitrary code strings.

## 3.8 Plan generator interface

```python
class AbilityPlanGenerator(Protocol):
    ability_id: str

    def generate(
        self,
        observation: BotObservation,
        public_context: PublicPlanningObservation,
    ) -> list[PlanProposal]:
        ...
```

Initial generation budget:

- up to two proposals per bot-controlled ability;
- up to two shared/public proposals from an Intelligence/team generator;
- merge equivalent intents;
- rank and expose three to five plans.

The human-controlled ability does not have a private bot planner in version 1. A public team planner may still recommend that the human act, but such a plan must stop before using the human’s private cards or making an unapproved private choice.

## 3.9 Initial proposal generators

Implement these in order.

### A. Resolve compulsory tile

Generate when a legal compulsory tile blocks other actions.

Plan:

```text
take control with a legal initiating bot ability, if needed
start interaction
auto-contribute legal bot cards
resolve if complete
otherwise stop for human contribution or replanning
```

### B. Resolve optional visible tile

Generate for legal visible prey/exploration/threat tiles.

Score reward against:

- AP;
- time;
- card scarcity;
- failure cost;
- objective relevance;
- return-to-shelter reserve.

### C. Collect AP

Generate when a bot ability has low AP and enough future action/control capacity to use it.

The plan normally ends after the die result because the resulting AP is new information.

### D. Draw a card

Generate when a draw materially increases the probability of resolving a visible or expected requirement.

The plan ends after the draw.

If the bot hand is full, the bot may choose its own discard using a deterministic card-value heuristic. Human discard choices always pause.

### E. Move and inspect

Generate one-step movement options to adjacent nodes.

The plan ends after movement because tile revelation can change priorities.

### F. Return toward shelter

Generate when:

- the shelter threshold is near;
- overrun risk is meaningful;
- objectives are sufficiently advanced;
- or safety reserve is low.

Initially use shortest-path distance over map adjacency, adjusted for known compulsory threats.

Execute one movement step and then replan. Do not commit to a long route through unrevealed nodes.

### G. End night

Generate only when reducer requirements are satisfied.

### H. Day plans

Generate:

- move shells to secure current shelter;
- retrieve shells if required for next-night tile plans;
- buy a hand-size upgrade;
- buy a deck-exchange upgrade;
- grow Poulpita;
- end day.

Day plans may execute multiple deterministic commands if no alternative allocation decision arises. For example, “deposit three shells to secure shelter” may execute all three transfers and then stop.

## 3.10 Intelligence handling

Intelligence is shared and public.

Implement it as:

- a shared card contributor during interactions;
- a source of public/team proposals where appropriate;
- not a seat;
- not counted among the three bot players;
- not given independent control ownership unless game rules explicitly require Intelligence to take control.

If Intelligence can take control under the implemented rules, represent such actions as `owner_ability_id="intelligence"` and `proposer_ability_id=None` or `"intelligence"`, but keep its controller type `shared`.

## 3.11 Initial belief model

Start with exact card-count bookkeeping, not Monte Carlo search.

For each hidden ability track:

- known deck composition;
- public discard/played cards;
- unknown hand size;
- remaining unknown card counts.

Expose queries such as:

```python
probability_has_interaction(
    observer: BotObservation,
    target_ability_id: str,
    interaction_id: str,
) -> float

probability_team_covers_requirements(
    public_observation: PublicPlanningObservation,
    requirements: list[str],
) -> float

probability_next_draw_is_useful(
    observation: BotObservation,
    ability_id: str,
    useful_interaction_ids: set[str],
) -> float
```

Use hypergeometric calculations where possible.

For dual-purpose cards, determine requirement coverage using matching. Never count one card as satisfying two requirements simultaneously.

Hidden tiles can initially use simple group-level expected risk. Add consistent particle assignments only after the deterministic vertical slice works.

## 3.12 Scoring and safety

Use lexicographic filtering before weighted scoring.

### Hard safety filter

Reject plans that clearly:

- cause immediate game loss;
- make a current compulsory interaction illegal or ignored;
- consume required carried shells reserved for a mandatory objective without justification;
- leave no legal control/action capacity;
- spend energy to zero;
- create unavoidable overrun failure;
- violate interaction priority rules.

### Risk budget

Estimate:

- probability of interaction success;
- failure damage;
- time remaining;
- known distance to shelter;
- control takes required to reach safety;
- AP required for the next safe action.

In the first version use conservative rules rather than pretending to have precise probabilities.

### Utility score

Among safe plans, score:

```text
objective progress
+ survival margin
+ energy and useful shared resources
+ expected tile reward
+ information gained
+ improved next-state flexibility
- AP cost
- time cost
- control-take cost
- scarce-card cost
- expected failure cost
- overrun risk
```

Keep weights in configuration, not hard-coded across planner modules.

## 3.13 Proposal cache

Cache proposals by:

- room ID;
- source game version;
- phase;
- relevant state fingerprint;
- observer belief fingerprint.

Do not reuse a proposal merely because it remains technically legal.

Each proposal declares dependencies such as:

```text
Poulpita node
visible tiles on current and adjacent nodes
active ability
relevant ability AP
relevant hand fingerprint
control takes
night time
energy
interaction state
pending surprise
objective progress
phase
```

Invalidate only when a relevant dependency changes.

## 3.14 Executor

Create one execution lock per room.

Pseudo-flow:

```python
async def execute_selected_plan(room_id: str, plan_id: str) -> None:
    acquire_room_bot_execution_lock(room_id)

    plan = load_current_plan(room_id, plan_id)
    state = load_authoritative_game_state(room_id)

    verify_plan_matches_current_proposal_set(plan, state)

    mark_execution_started(plan)

    while True:
        state = load_authoritative_game_state(room_id)

        status = evaluate_plan_status(plan, state)

        if status.requires_stop:
            finalize_and_emit(status)
            regenerate_proposals_if_needed()
            return

        step = resolve_next_step(plan, state)

        if step.requires_human_input:
            pause_and_emit_human_input(step)
            return

        command = materialize_command(
            step=step,
            room_id=room_id,
            expected_version=state.version,
        )

        result = submit_through_existing_command_service(command)

        emit_bot_plan_step(result)

        if result.rejected:
            pause_as_command_rejected(result)
            regenerate_proposals()
            return
```

Never reuse an old `expected_version` between steps.

### Execution pacing

The backend should execute asynchronously and emit progress over WebSocket.

For the prototype:

- use the project’s existing task/runtime pattern if available;
- otherwise use a narrowly scoped asynchronous room task;
- do not block a request while a long plan runs;
- add an optional short visual delay between steps, for example 250–500 ms;
- make the delay configurable and disable it in tests and simulations.

The game UI should be locked against conflicting manual mutations while a bot plan is executing, except for **Cancel plan**.

## 3.15 Backend endpoints

Use existing API conventions. A possible API is:

```text
POST /api/rooms/{room_id}/bot-mode/setup
GET  /api/rooms/{room_id}/bot-proposals
POST /api/rooms/{room_id}/bot-proposals/recalculate
POST /api/rooms/{room_id}/bot-plans/{plan_id}/execute
POST /api/rooms/{room_id}/bot-execution/cancel
GET  /api/rooms/{room_id}/bot-status
```

### Setup body

```json
{
  "mode": "solo_with_bots",
  "human_ability_id": "agility",
  "privacy_mode": "solo_faithful"
}
```

### Execute response

Return immediately with an execution identifier:

```json
{
  "execution_id": "exec_...",
  "plan_id": "plan_...",
  "status": "executing"
}
```

Actual progress arrives by WebSocket.

## 3.16 WebSocket events

Add explicit events:

```text
bot_proposals_generating
bot_proposals_updated
bot_plan_started
bot_plan_step_started
bot_plan_step_completed
bot_plan_paused
bot_plan_completed
bot_plan_invalidated
bot_plan_cancelled
bot_human_input_required
bot_error
```

Each event should include:

- room ID;
- execution/proposal identifiers;
- source and resulting game versions where relevant;
- public explanation;
- no hidden bot-hand data.

---

# 4. Frontend Design

## 4.1 Suggested component structure

```text
frontend/src/components/bots/
    BotPlanToggle.tsx
    BotPlanOverlay.tsx
    BotPlanCard.tsx
    BotPlanExecutionStatus.tsx
    BotPlanStepList.tsx
    BotHumanInputPrompt.tsx
    BotRiskBadge.tsx
    BotResourceSummary.tsx
```

Integrate them into:

```text
frontend/src/pages/GameRoomPage.tsx
```

The board remains rendered by the existing `BoardView.tsx`.

## 4.2 Overlay layout

The overlay should be anchored to the board container rather than the full browser window where possible.

Structure:

```text
Board container
├── BoardView
├── floating “Plans” button
├── execution status chip
└── BotPlanOverlay
```

When open:

- dim or blur the board underneath;
- cover most of the board;
- remain closable;
- preserve mobile scrolling;
- do not destroy board state;
- show one column on mobile and a wider card layout on desktop.

The panel should not be a mandatory blocking modal. The human may close it and inspect the board before choosing.

## 4.3 Panel states

### No proposals

```text
No current plans.
[Calculate plans]
```

### Planning

Show a progress indicator:

```text
Bots are evaluating the current state…
```

### Awaiting selection

Show ranked plan cards.

### Executing

Show:

- plan title;
- current step;
- completed steps;
- cancel button;
- a compact public event log.

The panel may be closed during execution. A persistent chip remains visible:

```text
Executing: Return to shelter · Step 2/3
```

### Replan required

Automatically refresh proposals and open the panel by default:

```text
The move revealed a compulsory threat.
Choose a new plan.
```

Allow users to disable automatic opening later, but keep it on for version 1.

### Human input required

Show a clear explanation and either:

- render an input inside the overlay;
- or close/minimize the overlay and highlight the normal relevant game UI.

Example:

```text
The interaction may require support from your Agility hand.
Choose cards in your player board, then continue or abandon the plan.
```

Do not reveal what bots expected the human to hold.

## 4.4 Plan card content

Each card should show only decision-relevant data:

```text
Proposer icon/name
Plan title
Forced / Low / Moderate / High risk
Short rationale
2–5 step preview
Expected AP and time
Control takes used
Possible shared-resource changes
Warnings
Execute button
```

Avoid false precision. For heuristic version 1, use:

```text
Low / Moderate / High confidence
```

rather than values such as `73.8%` unless a real probabilistic model produced them.

## 4.5 Frontend state

Add a dedicated hook or store slice:

```typescript
type BotUiState = {
  isOverlayOpen: boolean;
  status:
    | "disabled"
    | "idle"
    | "planning"
    | "awaiting_selection"
    | "executing"
    | "awaiting_human"
    | "error";

  proposalSetId?: string;
  proposals: PublicPlanSummary[];
  activeExecution?: BotExecutionView;
  lastStopReason?: string;
};
```

Suggested hook:

```text
useBotPlans(roomId)
```

Responsibilities:

- fetch initial bot status;
- subscribe to WebSocket bot events;
- recalculate proposals;
- execute plan;
- cancel execution;
- open panel automatically on replan;
- clear stale proposals when game version changes outside an active plan.

## 4.6 Input locking

While a plan is executing:

- disable normal mutating board/player controls;
- keep inspection UI available;
- keep overlay close available;
- keep cancel available.

Do not rely only on frontend locking. The backend room execution lock must also prevent conflicting commands or reject them cleanly.

When the human cancels, finish the currently accepted reducer command, stop before issuing the next command, regenerate proposals, and restore manual controls.

---

# 5. End-to-End User Flow

## 5.1 Start game

1. User selects level.
2. User selects `solo_with_bots`.
3. User chooses one of Agility, Camouflage, Force, Propulsion.
4. Backend creates seat/controller assignments.
5. Game starts through the existing start flow.
6. Backend generates the first proposal set.
7. UI shows the floating Plans button and opens the overlay.

## 5.2 Choose plan

1. User inspects the board.
2. User opens the plan overlay if closed.
3. User clicks a proposed plan.
4. Frontend calls the execute endpoint.
5. Manual mutation controls become disabled.
6. Backend executes validated commands one at a time.
7. UI receives and displays step events.

## 5.3 Plan reaches a decision boundary

Example: a movement reveals a threat.

1. Move command succeeds.
2. Tile visibility is updated by the normal reducer.
3. Executor detects `tiles_revealed`.
4. Current plan stops as `replan_required`.
5. Backend generates a new proposal set.
6. Overlay opens with the explanation:
   `Movement revealed a compulsory threat.`
7. Human selects the next plan.

## 5.4 Interaction needs human support

1. A bot initiates an interaction.
2. Bot-controlled abilities contribute according to their private policies.
3. Requirements remain incomplete.
4. The human ability could possibly help.
5. Executor pauses as `human_input_required`.
6. UI asks the human to inspect and optionally play cards.
7. After human action:
   - continue the current interaction if still coherent; or
   - invalidate and regenerate proposals.

For version 1, it is acceptable to stop the selected plan and generate new proposals after the human contributes.

---

# 6. Development Phases

## Phase 0 — Inspect and document current code paths

Before editing:

- locate the canonical `GameState` model;
- locate command models and envelope creation;
- trace one frontend command from click to reducer;
- trace WebSocket projection broadcasting;
- identify room storage and concurrency behaviour;
- locate all command validation and state mutation functions;
- locate seeded/random game operations;
- inspect current player-board rendering and privacy assumptions.

Deliverable:

```text
documentation/bot_implementation_map.md
```

It should list exact files and functions that the implementation will reuse.

Do not begin by inventing a parallel bot game engine.

## Phase 1 — Solo seat assignment and UI skeleton

Backend:

- add `solo_with_bots` configuration;
- assign one human and three bots;
- mark Intelligence shared;
- expose controller assignments in game projection;
- add feature flag if necessary.

Frontend:

- add mode and ability selection;
- show bot badges on the three bot ability boards;
- add Plans floating button;
- add overlay with mocked plan cards;
- verify open/close behaviour on desktop and mobile.

Acceptance criteria:

- existing goldfish mode still works;
- user can start a one-human/three-bot room;
- controller ownership is visible;
- Intelligence is not shown as a fifth player;
- overlay opens and closes without affecting the board.

## Phase 2 — Bot observations and deterministic proposals

Backend:

- implement redacted bot observations;
- implement public planning observation;
- implement legal command enumeration;
- implement deterministic proposal generators:
  - forced interaction;
  - collect AP;
  - draw;
  - move one step;
  - return one step toward shelter;
  - end night;
  - basic day actions;
- add proposal endpoints and WebSocket events;
- add private/public proposal serialization.

Frontend:

- replace mock plans with server proposals;
- show rationale, steps, cost, risk;
- add recalculate button.

Acceptance criteria:

- three bot abilities generate proposals from their own views;
- no private bot card IDs leak into public proposal payloads;
- proposals correspond to commands that are currently legal;
- forced compulsory interactions rank above optional actions;
- user can still ignore proposals and play manually.

## Phase 3 — Multi-command plan executor

Backend:

- implement room execution lock;
- implement execution graph;
- issue commands through the existing command service;
- use current `expected_version` for every command;
- detect completion, invalidation and rejection;
- support cancellation;
- emit execution events.

Frontend:

- execute button;
- input locking;
- live step display;
- cancel button;
- compact status when overlay is closed;
- automatic reopen on replan.

Initial executable plans:

```text
take control + collect AP
take control + move
take control + start interaction
deposit multiple shells
grow + end day, only when unambiguous and safe
```

Acceptance criteria:

- one click can execute multiple commands;
- every command appears in normal game history;
- reducer remains authoritative;
- plan stops after movement revelation or random result;
- stale version causes safe pause/replan, not silent corruption;
- cancel stops before the next command.

## Phase 4 — Cooperative interactions

Backend:

- add bot-card contribution policy;
- add requirement matching;
- support Intelligence contribution;
- support dual-purpose cards without double counting;
- pause for possible human contribution;
- resolve automatically only when requirements are complete and the plan authorizes resolution;
- support optional counterattack as a separate plan decision.

Frontend:

- display “bots contributed support” without exposing hidden cards;
- show human contribution prompt;
- explain whether success is ready;
- expose separate Resolve / Accept failure decisions when needed.

Acceptance criteria:

- two bot abilities can cooperate in one interaction;
- Intelligence can contribute as shared ability;
- human cards remain private to bot planners;
- incomplete interactions do not automatically fail;
- counterattack is not attempted merely because it is possible.

## Phase 5 — Card beliefs, resource reservations and risk

Backend:

- exact remaining-card counts;
- hypergeometric hand probabilities;
- probability that a draw is useful;
- team requirement coverage estimate;
- resource reservation model;
- safe return heuristic;
- configurable scoring;
- conservative risk labels.

Acceptance criteria:

- planner chooses draw more often as useful-card density rises;
- planner chooses AP more often when AP is the actual bottleneck;
- planner preserves resources required for an objective;
- planner recommends returning earlier with low energy/time margin;
- proposal descriptions do not claim unsupported numeric precision.

## Phase 6 — Hidden-tile particles and simulation

Only begin after the deterministic system is stable.

Refactor reducer transition logic so it can be called on cloned state with seeded randomness.

Implement:

- consistent hidden-tile assignment particles;
- surprise-deck particles;
- short rollouts over proposed options;
- expected outcome and tail-risk estimates;
- simulation mode that runs without UI animation.

Use the same plan generators and evaluator for live bots and balance simulations.

Acceptance criteria:

- fixed seed produces reproducible simulations;
- omniscient and privacy-faithful modes are separately measurable;
- thousands of games can run without WebSocket/frontend dependencies;
- simulation does not mutate live room state.

## Phase 7 — Autonomous orchestrator for balance simulation

Add only after the human-orchestrated mode works.

Implement an orchestrator that automatically selects the best safe proposal.

Modes:

```text
human_orchestrator
heuristic_orchestrator
stochastic_rollout_orchestrator
omniscient_upper_bound
```

Collect metrics:

- win rate;
- loss reason;
- level completion time;
- energy trajectory;
- objective completion;
- control-take usage;
- AP waste;
- card draws;
- failed interactions;
- return-to-shelter margin;
- proposal selected by type;
- human/privacy versus omniscient performance gap.

---

# 7. Testing Plan

## 7.1 Backend unit tests

### Observation privacy

- each bot sees its own hand;
- each bot does not see other hidden hands;
- Intelligence visibility is correct;
- frontend-safe proposal contains no private basis;
- event logs do not leak card identities.

### Legal actions

- forced compulsory priority;
- legal initiator;
- control limits;
- action limits;
- AP and time costs;
- adjacency;
- end-night requirements;
- day-action requirements.

### Proposal generation

- forced threat outranks optional prey;
- no illegal tile bypass;
- return plan appears near overrun;
- end-night plan appears only at shelter after threshold;
- day upgrade is not proposed when unaffordable;
- carried and shelter shells are not confused.

### Card matching

- one normal card satisfies one requirement;
- one dual-purpose card satisfies one of its options;
- one dual-purpose card never satisfies two requirements;
- multiple abilities can cover a requirement set;
- Intelligence cards are included correctly.

### Executor

- fills current expected version;
- revalidates after every command;
- stops after random/information event;
- handles rejection;
- handles cancellation;
- releases room lock on all terminal paths;
- never mutates state outside reducer.

## 7.2 Integration scenarios

1. **Take control and collect AP**
   - select plan;
   - two commands execute;
   - AP roll appears;
   - plan completes and proposals regenerate.

2. **Move reveals compulsory tile**
   - select movement;
   - move executes;
   - tile appears;
   - plan stops;
   - forced-interaction proposal ranks first.

3. **Two bots resolve interaction**
   - initiator starts;
   - second bot contributes;
   - interaction resolves;
   - cards discard normally.

4. **Human contribution needed**
   - bots cannot complete interaction;
   - execution pauses;
   - no bot inspects human hand;
   - UI requests human action.

5. **Return before overrun**
   - low margin state;
   - return proposal ranks above optional reward.

6. **Day resource conflict**
   - energy is enough either to grow or survive, but not safely both;
   - unsafe growth is filtered or clearly warned.

7. **Version conflict**
   - inject a concurrent state change;
   - command is rejected or plan invalidates;
   - no duplicate command executes.

## 7.3 Frontend tests

Use the project’s existing test stack.

Verify:

- overlay opens/closes;
- proposal cards render;
- execution disables mutating controls;
- closing overlay keeps execution chip;
- cancel works;
- replan automatically opens panel;
- human-input state is understandable;
- mobile overlay scrolls;
- hidden details are absent from rendered JSON/payload.

## 7.4 Determinism

All bot tests must support fixed random seeds.

Randomness includes:

- AP die;
- card draws and reshuffles;
- tile placement;
- surprise draws;
- rollout sampling.

Do not seed production games globally. Pass RNG explicitly or through an existing room RNG abstraction.

---

# 8. Logging and Explainability

Store public bot events in the room event log:

```text
proposal set generated
plan selected by human
plan execution started
command issued
command result
plan paused
plan invalidated
plan completed
plan cancelled
```

Example:

```json
{
  "type": "bot_plan_invalidated",
  "plan_id": "plan_123",
  "reason": "new_compulsory_tile_revealed",
  "source_version": 41,
  "resulting_version": 42
}
```

Keep private reasoning separate from the public event log.

A debug log may record:

- private hand basis;
- exact heuristic scores;
- belief calculations;
- discarded candidate plans.

It must be gated by debug mode and must not be sent to normal clients.

---

# 9. Configuration

Create a bot configuration object or JSON file:

```json
{
  "max_proposals_per_bot": 2,
  "max_public_proposals": 5,
  "step_delay_ms": 350,
  "auto_open_overlay_on_replan": true,
  "risk": {
    "minimum_energy_reserve": 2,
    "return_time_margin": 2,
    "high_risk_failure_probability": 0.35
  },
  "weights": {
    "objective_progress": 100,
    "energy": 8,
    "neurons": 4,
    "seashells": 5,
    "information_gain": 2,
    "ap_cost": -2,
    "time_cost": -4,
    "control_take_cost": -5,
    "failure_damage": -12
  }
}
```

These values are placeholders. Do not present them as balanced defaults until tested.

Store plan explanations independently from weights where possible, so changing balance does not require rewriting UI text.

---

# 10. Important Edge Cases

Handle explicitly:

- human chooses a different ability when restarting;
- a plan references a tile removed by another effect;
- movement reveals several equal-priority compulsory tiles;
- a non-compulsory tile has greater priority than compulsory tiles;
- no ability can legally initiate a compulsory tile;
- the active ability has no actions remaining;
- all remaining control takes are exhausted;
- interaction remains open while a plan is cancelled;
- a surprise panel interrupts plan execution;
- bot hand is full and draw requires discard;
- human hand is full and draw was recommended;
- deck reshuffles;
- Intelligence contributes but is not a player seat;
- counterattack becomes possible after normal success;
- shelter shells differ from carried shells;
- size growth would reduce energy to zero;
- secure-shelter discount changes growth feasibility;
- phase changes during execution;
- game ends during a plan;
- WebSocket reconnect occurs while a plan is executing;
- duplicate execute requests arrive;
- execution endpoint is retried by the client.

Use idempotent execution identifiers and room locks to avoid duplicate plan runs.

---

# 11. Coding-Agent Instructions

The coding LLM should follow this order:

1. Inspect existing models and command flow.
2. Write the implementation map.
3. Add tests for current behaviour before refactoring.
4. Add the solo controller assignment with minimal schema changes.
5. Add observer redaction and tests.
6. Add proposal models and mocked generators.
7. Connect real legal actions.
8. Add the frontend overlay.
9. Add executor for one simple multi-command plan.
10. Expand plan types incrementally.
11. Add interactions.
12. Add probability and simulation only after the vertical slice works.

During implementation:

- reuse existing Pydantic and TypeScript types;
- preserve existing API conventions;
- keep planner functions pure where possible;
- keep reducer calls centralized;
- use exhaustive type checking for plan status and step kinds;
- avoid broad exception swallowing;
- log structured failure reasons;
- do not introduce a runtime language-model API;
- do not rewrite unrelated admin tooling;
- do not make bot logic depend on visual components;
- do not couple simulations to WebSocket or React;
- keep every phase deployable and testable.

---

# 12. Definition of Done for the First Release

The first release is complete when:

1. A user can start a game as one of the four non-Intelligence abilities.
2. The other three abilities are visibly bot-controlled.
3. Intelligence remains collective.
4. The server generates three to five legal, understandable plans.
5. A closable overlay covers the board and displays those plans.
6. Clicking a plan executes more than one command when appropriate.
7. Execution uses the normal versioned command path and reducer.
8. Execution stops safely at new-information or human-choice boundaries.
9. The UI explains why execution stopped.
10. The player can cancel and resume manual play.
11. Bot private hands are not exposed through proposal payloads.
12. Compulsory priority, AP, time, control, phase and interaction rules remain enforced by the reducer.
13. Deterministic unit and integration tests cover the main flows.
14. Existing non-bot gameplay remains functional.

The first release does **not** need:

- reinforcement learning;
- a runtime LLM;
- full POMDP search;
- perfect balancing;
- long-horizon campaign optimization;
- autonomous selection of plans;
- mass simulation.

Those are later extensions built on the same plan proposal and execution architecture.
