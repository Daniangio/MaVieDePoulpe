# Ma Vie De Poulpe Bot Implementation Map

This map records the existing code paths the bot implementation must reuse. It is the Phase 0 handoff before adding planner and executor logic.

## Backend Entry Points

- `backend/app/game_router.py`
  - `POST /api/game/rooms` creates a room through `GameRoomService.create_room`.
  - `GET /api/game/rooms/{room_id}/state` returns the current projection.
  - `POST /api/game/rooms/{room_id}/commands` sends a normal command envelope to `GameRoomService.enqueue_game_command`.
  - `GET /api/game/rooms/{room_id}/ws` sends `state_projection` messages and supports `request_projection`.

- `backend/app/schemas.py`
  - `GameRoomCreateRequest` is the setup request shape.
  - `GameCommandRequest` is the standard command envelope.
  - `GameCommandQueuedResponse` carries accepted/rejected command results.
  - `GameStateResponse` is the public projection shape.

## Authoritative Game State And Reducer

- `backend/app/game_room_service.py`
  - `GameRoomService.create_room` creates room metadata and the setup `GameState`.
  - `_setup_state` builds a setup projection from the selected level and map.
  - `_goldfish_state` builds the initial playable state.
  - `GameRoomService.enqueue_game_command` either applies a command directly or sends it to Redis/worker when `USE_DISTRIBUTED_GAME_RUNTIME=true`.
  - `GameRoomService.apply_command` loads room/state, applies `_reduce`, saves the result, and broadcasts the projection.
  - `GameRoomService._reduce` is the authoritative reducer. Bot code must issue commands through this path and must not mutate state directly.
  - `CommandRejection` is the structured rejection path.
  - `_project_state` builds the frontend-facing projection.

## Existing Commands To Reuse

Commands currently handled by `_reduce` include:

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

Every bot command must include the current `expected_version`.

## State Storage And Concurrency

- In-memory state lives in `GameRoomService._memory_rooms`, `_memory_states`, and `_memory_results`.
- Redis persistence uses `_room_key`, `_state_key`, and `_result_key`.
- Distributed command processing uses `COMMAND_STREAM_KEY`, `_command_result_key`, and `GameWorker`.
- Per-room mutation locking currently happens in `GameRoomService.apply_command` through `self._room_locks[room_id]`.
- Bot execution should use the same lock or a small additional execution lock before issuing multi-command plans.

## Randomness

Random operations currently happen inside `game_room_service.py`:

- deck expansion and shuffling in `_expand_deck`;
- discard reshuffle in `_refill_draw_pile_from_discard`;
- surprise deck shuffling in `_goldfish_state`;
- level tile placement shuffling in level setup helpers;
- AP die roll in `collect_action_points`.

Future deterministic bot tests should either monkeypatch `random` as current tests do, or introduce a room RNG abstraction before adding simulations.

## Content And Rules Configuration

- `backend/app/game_content_service.py`
  - `get_game_content_catalog` returns tiles, categories, interactions, cards, tokens, surprise cards/decks, action costs, and Poulpita panel configuration.
  - `get_level_config` returns level setup including map, tile groups, starting node, starting energy/neurons, night duration, surprise deck, objectives, and node tokens.
  - `get_player_board_configs` feeds capability deck/hand/control setup.

- `backend/app/map_service.py`
  - `get_map` loads admin-created map configs.
  - The board projection contains node coordinates, adjacency, and image metadata.

## Frontend Command Flow

- `frontend/src/pages/GameRoomPage.tsx`
  - `loadProjection` fetches `/api/game/rooms/{room_id}/state`.
  - The WebSocket receives `state_projection` messages.
  - `submitCommand` sends the standard command envelope and updates projection from the response.
  - Board/player UI handlers call `submitCommand` for every mutation.
  - The interaction panel and surprise panel are UI-only until the user submits existing reducer commands.

- `frontend/src/components/BoardView.tsx`
  - Renders map image, nodes, Poulpita, shelters, and tile instances.
  - Emits node move and tile inspect callbacks.

- `frontend/src/components/HexTilePreview.jsx`
  - Shared visual tile component used in admin and game UI.

## Phase 1 Bot Surface Added

- Room creation now accepts `mode="solo_with_bots"` and `human_ability_id`.
- Valid human bot-mode abilities are `agility`, `camouflage`, `force`, and `propulsion`.
- `intelligence` is marked `shared`, not a fifth bot/player seat.
- Projections expose `bot_config` and per-capability controller metadata:
  - `controller_type`;
  - `controller_seat_id`;
  - `is_human_controlled`;
  - `is_bot_controlled`;
  - `is_shared_controlled`.
- The frontend setup page lets the user choose manual goldfish or solo-with-bots and choose their ability.
- The game UI shows controller chips and a Phase 1 mocked Plans overlay.

## Next Backend Reuse Points

Phase 2 should add a dedicated `backend/app/bots/` package that depends on these existing functions:

- use `_project_state` output as the public planning baseline;
- build redacted bot observations from loaded raw state;
- enumerate legal command templates by mirroring reducer preconditions, while still letting `_reduce` remain final authority;
- serialize frontend-safe proposals without private hand/card identifiers;
- add endpoints beside `game_router.py` for proposal fetch/recalculate.

Phase 3 should execute selected plans by repeatedly calling `GameRoomService.enqueue_game_command` or a shared internal helper that preserves the same command envelope, version validation, reducer path, event log, state save, and WebSocket broadcast.
