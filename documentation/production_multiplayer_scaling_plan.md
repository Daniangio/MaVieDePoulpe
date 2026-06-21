# Production Scaling Plan for Auth, Lobby, Matchmaking, and UX

## Scope

This document describes the changes required to evolve the current prototype into a production-ready online card game able to sustain at least hundreds of concurrent players with a clear upgrade path beyond that.

The recommendations are based on the current architecture:
- FastAPI backend with a single `/ws` socket endpoint
- in-memory room/game state in `RoomManager`
- in-memory/fake user and game stores
- JWT auth with guest fallback and no persistent session model
- lobby/room flow driven directly over websocket actions
- frontend state coupled closely to websocket payloads

The target is not "internet scale" yet. The target is a robust small production service: stable auth, predictable matchmaking, safe reconnects, operational visibility, and a UX that does not feel like a debug tool.

---

## 1. Production target architecture

For hundreds of concurrent players, the correct architecture is still fairly small:

- **API service**: FastAPI app for auth, profile, decks, match history, catalog, configuration
- **Realtime gateway**: websocket service for presence, lobby, game events, and game commands
- **Persistent database**: PostgreSQL
- **Shared cache / pubsub**: Redis
- **Background workers**: lightweight task workers for matchmaking ticks, bot turns if needed, analytics/event fanout, replay persistence
- **Object storage**: for replays, logs, large exports if needed later

---

## 3. Authentication changes

### 3.5 Separate auth transport from game transport

Required changes:
- authenticate through HTTP first
- websocket should accept a validated session token/cookie at connect time
- avoid the current pattern of `accept socket -> then receive auth payload`

Why:
- easier to secure, instrument, and reject invalid clients before attaching them to game state

---

## 4. Lobby and presence redesign

### 4.1 Make presence a real shared service

Required changes:
- store online presence in Redis with TTL heartbeat
- track:
  - online/offline
  - in lobby / in queue / in room / in game
  - current client version
  - reconnect window state

Why:
- presence cannot remain process-local if you want multiple backend instances or robust reconnects

### 4.3 Redesign room lifecycle as explicit state machine

Required changes:
- define room states explicitly, for example:
  - `CREATED`
  - `WAITING_FOR_PLAYERS`
  - `READY_CHECK`
  - `DECK_LOCKED`
  - `MULLIGAN`
  - `IN_GAME`
  - `FINISHED`
  - `ABANDONED`
- define allowed transitions and server ownership of each transition

Why:
- current room/game behavior works, but production stability depends on explicit state transitions

### 4.4 Improve reconnect semantics

Required changes:
- assign each live game a reconnect window, for example 60-120 seconds
- keep seat ownership independent from socket connection
- on reconnect, restore:
  - game state
  - pending decisions
  - visible zones relevant to the reconnecting player
  - timers
- mark opponent UI as `reconnecting`, not just silent waiting

Why:
- disconnects are normal in production; the system must treat them as routine, not exceptional

---

## 6. Game session and server authority changes

### 6.1 Persist match metadata separately from full board state

Required separation:
- persistent match record: players, result, duration, format, timestamps
- recoverable live game snapshot: turn state, board state, pending decisions
- replay/event log: append-only actions and outcomes

Why:
- different read/write patterns
- easier recovery, debugging, analytics, and replay

### 6.2 Define one authoritative game worker per live match

For hundreds of players, one practical model is:
- any backend instance can host many live matches
- each match has one authoritative owner instance
- ownership is registered in Redis
- commands route to the owner
- state snapshots/events replicate to durable storage asynchronously

Why:
- avoids split-brain game state while still allowing horizontal scale

### 6.3 Timeouts and timers

Required production timers:
- mulligan timer
- response timer
- turn timer with reserve time / chess clock if desired later
- reconnect grace timer
- matchmaking accept timer

Why:
- live service without explicit timers becomes abusable and operationally expensive

---

## 7. UX changes required for production

### 7.1 Authentication UX

Current auth UX is enough for development, not for production.

Required improvements:
- clear distinction between guest and account play
- explicit `upgrade guest account` path
- password reset and email verification if using email
- session expiration/relogin messaging
- better auth error taxonomy: invalid credentials, rate-limited, network failure, account locked

### 7.2 Lobby UX

Required improvements:
- primary CTA should be `Play Casual`, `Play Ranked`, `Practice vs Bot`, `Goldfish`, `Custom Game`
- lobby chat should be secondary, not central
- presence should show meaningful state: in queue, in match, offline, reconnecting
- deck readiness should be explicit before queueing

### 7.3 Matchmaking UX

Required improvements:
- queue screen with elapsed wait time, selected deck, format, cancel button
- match found accept modal
- if queue expands search range, expose only minimal useful detail to player
- if reconnecting, show `Resume Match`

### 7.4 In-game UX

Required improvements:
- strong connection state indicator: connected / reconnecting / desynced
- clear pending state for commands sent to server
- explicit opponent status: thinking, reconnecting, timed out
- clearer match result and post-match screen
- guard against stale panels remaining open during reconnect/restate

### 7.5 Deck and collection UX

For production, deck validity cannot be a last-minute room check only.

Required improvements:
- deck list shows legality and last modified time
- queue button disabled until a legal deck is selected
- deck locking when entering queue/match
- copy/import/export deck flows

---

## 8. Security and fairness requirements

### 8.1 Never trust client game decisions

The current model is mostly server-authoritative, which is correct. Preserve that.

Required rule:
- client sends intent only
- server computes legality, visibility, and all outcomes
- never let client choose hidden information it should not see

### 8.2 Visibility segregation

As the game moves to real multiplayer:
- hidden hand/deck data must be filtered strictly per player session
- debug/goldfish paths must be impossible in production mode
- logs and analytics must not leak hidden data between players

### 8.3 Moderation and abuse tooling

Required minimum:
- mute/block for chat if public lobby remains
- report match / player
- audit log for auth and match events
- ban or temporary suspension mechanism

---

## 9. Operational changes

### 9.1 Observability

Required immediately:
- structured logs with request/session/game IDs
- metrics for:
  - websocket connects/disconnects
  - auth success/failure
  - queue wait times
  - active games
  - reconnect success rate
  - match completion rate
  - action latency / validation latency
  - bot turn duration
- distributed tracing is useful but not mandatory at first

### 9.2 Admin tools

Required minimum:
- inspect active rooms/games
- inspect queue state
- force-end stuck matches
- view reconnect/session state
- view recent server-side errors by game ID

### 9.3 Deployment and scaling

For the first production phase:
- run multiple API/websocket instances behind a load balancer
- use sticky sessions only if routing to authoritative match owner is not yet implemented; otherwise route by match ownership
- use PostgreSQL managed backups
- use Redis for shared presence and routing
- automate zero-downtime deploys with version gating for active matches

---

## 10. Recommended implementation roadmap

### Phase 1: Production foundation

Do first.

- replace fake user/game stores with PostgreSQL-backed repositories
- add real sessions and refresh tokens
- move guest flow to real temporary accounts
- move lobby/room/presence to Redis-backed shared state
- define explicit room/game lifecycle state machines
- add reconnect window and session resume
- add structured logs and core metrics

Result:
- stable custom games and bot games with recoverable sessions

### Phase 2: Matchmaking MVP

- add casual queue
- add queue entry and match acceptance flow
- auto-create room/game from accepted match
- deck locking at queue join
- queue UX and reconnect UX polish

Result:
- real public matchmaking at modest scale

### Phase 3: Competitive/ranked support

- MMR/ranking service
- queue segmentation by format/region/rating
- post-match progression and history
- anti-dodge handling
- richer moderation/admin tools

Result:
- sustainable live-service loop

### Phase 4: Scale hardening

- authoritative match ownership and routing
- async replay pipeline
- bot worker isolation if needed
- versioned protocol/contracts between client and server
- chaos testing around reconnect and failover

Result:
- resilient multi-instance operation

---

## 11. Highest-priority concrete issues in the current codebase

These are the first items I would address because they are structural blockers, not polish:

1. **Remove in-memory fake persistence from auth and room state**
   - `fake_users_db`, in-memory rooms, pending invites, game state ownership
2. **Replace websocket post-accept auth handshake with real session-authenticated websocket connect**
3. **Introduce persistent session and reconnect model**
4. **Move lobby/presence/room coordination to Redis-backed shared state**
5. **Add a proper matchmaking queue instead of relying on open rooms**
6. **Define room and game lifecycle state machines explicitly**
7. **Add observability before scale issues become opaque**
8. **Separate production UX from debug/dev UX paths**

If these are not done, hundreds of players will still be technically possible for short periods, but the service will not be operationally reliable.

---

## 12. Recommended product decisions

To keep scope controlled, I recommend the following product choices:

- keep **guest play**, but make it a real temporary account
- make **casual matchmaking** the first production queue; delay ranked until reconnect and fairness are stable
- keep **custom rooms** for direct challenges and testing, but do not treat them as the main match entry point
- keep **goldfish** and **debug** as explicitly non-production capabilities guarded by environment flags and server-side permission checks
- prefer **clear queue and reconnect UX** over adding more game modes early

---

## 13. Summary

For a few hundred concurrent players, the game does not need a radically different engine. It needs stricter boundaries:
- persistent identities and sessions
- shared presence and room state
- real matchmaking queues
- explicit reconnect semantics
- cleaner UX around queueing, connection state, and match flow
- operational visibility

The current game logic can remain largely server-authoritative and event-driven. The main production work is around state ownership, persistence, and player-facing flow discipline.

---

## 14. Operational target architecture

This section makes the earlier recommendations concrete.

### 14.1 Recommended system split

For the first real production deployment, use this ownership model:

```text
Browser Client
  ├─ HTTPS ───────────────> API Service ───────────────> PostgreSQL
  │                             │
  │                             └──────────────────────> Redis
  │
  └─ Authenticated WebSocket -> Realtime Gateway ─────> Redis
                                        │
                                        ├─────────────> Matchmaking Worker
                                        │
                                        └─────────────> Match Worker
                                                          ├────────────> Redis (routing / reconnect)
                                                          ├────────────> PostgreSQL (match metadata)
                                                          └────────────> Replay/Snapshot Store
```

- **Frontend client**
  - browser app
  - authenticates over HTTPS
  - opens one authenticated websocket for realtime state
- **API service**
  - login, registration, guest creation, token refresh, profile, decks, match history
  - reads/writes PostgreSQL
  - reads/writes Redis when session or presence state is needed
- **Realtime gateway**
  - websocket termination
  - presence heartbeats
  - lobby event fanout
  - routes game commands to the authoritative match owner
- **Match worker**
  - authoritative runtime for a live match
  - keeps live board state in memory
  - validates commands and emits events/state updates
  - writes snapshots/events asynchronously
- **Matchmaking worker**
  - consumes queue entries
  - creates match assignments
  - manages ready-check timeouts
- **PostgreSQL**
  - system of record for durable product data
- **Redis**
  - shared low-latency coordination layer
  - presence, queue state, routing, reconnect windows, transient room state
- **Object storage or replay storage service**
  - durable replays, exported event logs, bulky diagnostics

### 14.2 Data ownership by storage type

#### PostgreSQL should own

Use PostgreSQL for durable, relational, query-heavy data:

- users
- auth identities
- sessions and refresh token metadata
- decks and deck revisions
- match records and results
- rankings / MMR
- purchases / entitlements if added later
- moderation actions
- audit trails
- card catalog metadata if not static in repo

Reason:
- transactional consistency matters
- admin/reporting queries matter
- failure recovery matters
- this data must survive restarts and deployments

#### Redis should own

Use Redis for fast shared coordination, not as the permanent system of record:

- online presence with TTL
- websocket connection routing
- queue entries and queue heartbeats
- room presence / seat claims before game start
- reconnect windows
- active game owner lookup (`game_id -> worker_instance`)
- short-lived decision locks or idempotency keys
- pubsub/streams for lobby and game fanout

Reason:
- low latency
- shared across instances
- naturally ephemeral
- operationally simpler than forcing PostgreSQL into a realtime coordination role

#### In-memory match worker should own

Use in-memory state inside the authoritative match process for:

- current board state
- current stack / pending decisions
- clocks and timers for the match
- hidden information visibility projections derived from state
- immediate legality and resolution execution

Reason:
- this is the hot path
- game logic should not perform full-turn reads/writes from a database on every action
- server-authoritative turn resolution is simplest and fastest in memory

#### Snapshot / replay store should own

Persist asynchronously:

- periodic match snapshots
- append-only action/event log
- final replay artifact
- error/debug dump for stuck games

Reason:
- needed for recovery, disputes, and debugging
- does not belong on the synchronous action path unless absolutely necessary

### 14.3 Why PostgreSQL is still the right default

PostgreSQL is not the universal runtime store, but it is still the best default primary database here because:

- it handles transactional product data well
- schema evolution is mature and well understood
- it supports relational integrity across users, decks, sessions, and match history
- the operational ecosystem is excellent
- your current scale target does not justify jumping early to distributed SQL or NoSQL complexity

This means:
- **yes** to PostgreSQL as the main durable database
- **no** to PostgreSQL as the main live match state engine

### 14.4 What not to do

Avoid these architectural mistakes:

- storing every live board mutation directly in PostgreSQL on the synchronous gameplay path
- making matchmaking operate by scanning SQL rows as the primary realtime mechanism
- letting multiple backend instances mutate the same live match state concurrently
- treating websocket connection state as the identity/session source of truth
- mixing debug/goldfish capabilities into the same unrestricted production command set

Those choices will work briefly, then create correctness and latency problems.

---

## 15. Reference request/ownership flows

### 15.1 Authentication flow

Recommended flow:

1. client logs in or creates guest account via HTTPS
2. API service creates/rotates session
3. API service returns:
   - access token
   - refresh token or secure refresh cookie
   - session ID
4. client opens websocket with session auth already present
5. realtime gateway validates session and registers connection in Redis presence

Operational effect:
- websocket does not invent identity
- reconnect is tied to session, not only to a currently open socket

### 15.2 Matchmaking flow

Recommended flow:

1. player selects deck and queue type
2. API or realtime service validates deck legality
3. queue entry is written to Redis and mirrored to PostgreSQL if needed for audit
4. matchmaking worker periodically matches tickets
5. both users receive `match_found`
6. both accept within timeout
7. backend creates match record in PostgreSQL
8. match ownership is registered in Redis
9. players are attached to the owning match worker

Operational effect:
- queueing is low-latency
- match record is still durable
- no manual room-joining UX is required for normal play

### 15.3 Live match action flow

Recommended flow:

1. client sends command over websocket
2. gateway resolves `game_id -> owning worker`
3. command is routed to that worker
4. worker validates legality against in-memory authoritative state
5. worker applies state change
6. worker emits filtered player-specific state deltas
7. worker appends event log and periodic snapshot asynchronously

Operational effect:
- game latency stays low
- one process owns correctness
- persistence does not dominate the hot path

### 15.4 Reconnect flow

Recommended flow:

1. client disconnects unexpectedly
2. presence entry expires or is marked disconnected
3. match remains reserved for reconnect window
4. opponent sees `reconnecting`
5. client reconnects with same session
6. gateway resolves active match and reattaches user to match worker
7. match worker resends current authoritative visible state and pending decisions

Operational effect:
- reconnect is routine
- no need to reconstruct state from ad hoc client assumptions

---

## 16. Suggested schemas and keys

These are not final migrations, but they make the design operational.

### 16.1 PostgreSQL tables

Suggested minimum set:

- `users`
- `auth_identities`
- `sessions`
- `refresh_tokens`
- `decks`
- `deck_revisions`
- `matches`
- `match_players`
- `ratings`
- `moderation_actions`
- `audit_events`

Optional later:
- `queue_events`
- `purchases`
- `collection_cards`
- `season_progress`

### 16.2 Redis keys

Suggested key patterns:

- `presence:user:{user_id}`
- `session:{session_id}`
- `queue:{mode}:{region}`
- `match_owner:{game_id}`
- `room:{room_id}`
- `reconnect:{game_id}:{user_id}`
- `ws_conn:{connection_id}`
- `user_conn:{user_id}`

Use TTL aggressively for ephemeral coordination keys.

### 16.3 Match snapshot model

A practical model:

- full snapshot every N actions or every T seconds
- append-only event log between snapshots
- on recovery:
  - load latest snapshot
  - replay tail events

This is sufficient for hundreds of concurrent players and materially improves recoverability.

---

## 17. Immediate implementation decisions

If the goal is to start the production migration now, I would make these decisions up front:

1. **PostgreSQL stays** as the primary durable database
2. **Redis is introduced** for presence, queues, routing, and reconnects
3. **Live matches remain in memory** under one authoritative worker
4. **Normal play uses matchmaking queues**, not open rooms
5. **Guests become real temporary accounts** with upgrade path
6. **Websocket authentication becomes session-based**, not post-accept ad hoc auth
7. **Snapshots and replay logs become first-class artifacts**

These decisions are coherent together. Making only one or two of them in isolation will not solve the production gap.

---

## 18. Practical recommendation for this project

Given the current codebase and your scale target, the best practical stack is:

- **FastAPI** kept for API and probably websocket gateway initially
- **PostgreSQL** for durable application data
- **Redis** for coordination and queue state
- **single codebase, but internally split services/modules** first
- **one authoritative worker per match**
- **async snapshot + replay persistence**

I would not replace PostgreSQL with a more fashionable database at this stage.

That would create migration cost without solving the actual bottlenecks, which are:
- in-memory non-durable room/auth state
- lack of queue architecture
- lack of reconnect/session model
- lack of shared cross-instance coordination

Those are the production problems to solve first.

---

## 19. Concrete next steps for lobby and game rooms

Current status after the first migration slices:
- registered users are persisted in PostgreSQL
- sessions and refresh tokens are persisted
- registered-user decks and collections are persisted

That is the correct foundation. The next work should move **coordination state** out of process memory without trying to move the live match engine out of memory yet.

The practical rule is:
- **PostgreSQL** for durable room/game metadata
- **Redis** for presence, routing, transient room state, and pubsub
- **in-memory match worker** for the live board state of one active match

### 19.1 What to migrate next

Do these in order.

#### Step A — Persistent lobby presence

Add Redis-backed presence first.

Store:
- `presence:user:{user_id}` → online status, current socket/session, current screen, last heartbeat
- `presence:room:{room_id}` → connected members
- `presence:game:{game_id}` → connected seats and reconnect deadlines

Required behavior:
- websocket connect authenticates a real session
- heartbeat refreshes TTL
- disconnect marks the session stale, not immediately gone
- lobby lists read from Redis presence, not in-memory socket lists

Why first:
- this breaks the dependency on one process for “who is online”
- reconnect semantics become tractable

#### Step B — Room records in PostgreSQL

Create durable room metadata tables.

Suggested tables:
- `rooms`
  - `id`
  - `name`
  - `mode` (`custom`, `bot`, `goldfish`, later `matchmade`)
  - `status` (`created`, `waiting`, `ready`, `mulligan`, `in_game`, `finished`, `abandoned`)
  - `host_user_id`
  - `game_id nullable`
  - `created_at`, `updated_at`
- `room_seats`
  - `room_id`
  - `seat_index`
  - `user_id nullable`
  - `is_virtual`
  - `selected_deck_id nullable`
  - `ready_state`
- `room_invites`
  - `id`
  - `room_id`
  - `from_user_id`
  - `to_user_id`
  - `status`
  - `expires_at`

What remains in Redis:
- room viewer/member presence
- transient ready countdown timers
- room event fanout

Why this split:
- room existence and membership must survive backend restarts
- live websocket fanout still belongs in Redis/in-memory coordination

#### Step C — Explicit room service boundary

Refactor `RoomManager` into narrower responsibilities:
- `PresenceService`
- `RoomRepository`
- `RoomService`
- `MatchRoutingService`
- `LiveGameService`

Do **not** rewrite all game logic. Just stop letting one class own:
- auth-adjacent state
- lobby presence
- room metadata
- match routing
- live game execution

Target boundary:
- room creation/join/leave uses repository + Redis fanout
- game start creates a durable `game_record`, assigns an owner worker, and hands the live state to the game service

#### Step D — Authoritative match ownership

Before running multiple backend instances, add explicit owner mapping.

Redis keys:
- `game_owner:{game_id}` → `{instance_id, lease_expiry}`
- `user_active_game:{user_id}` → `game_id`
- `room_active_game:{room_id}` → `game_id`

Behavior:
- one instance claims ownership when a game starts
- all commands route through the gateway to that owner
- owner renews lease periodically
- if owner dies, the game can be marked recoverable or abandoned based on snapshot freshness

At this stage, the live board still stays in memory on the owner instance.

### 19.2 HTTP and websocket contract changes

Do not keep expanding the current ad hoc socket message surface indefinitely.

Split responsibilities:

#### HTTP
- auth
- decks / collection
- profile
- room creation
- invite creation / accept / decline
- matchmaking join / leave later
- initial room snapshots

#### Websocket
- authenticated realtime session
- presence heartbeat
- lobby updates
- room updates
- game state stream
- game command intents

Recommended connect flow:
1. client logs in over HTTP
2. client opens websocket with access token or session-bound cookie
3. server validates session and attaches socket to user/session
4. server emits initial lobby/room/game subscriptions

Do not keep the old pattern of “connect anonymously, then authenticate inside the socket” once production mode is active.

### 19.3 Room state machine to implement

Define it concretely and enforce transitions server-side.

Suggested room lifecycle:
- `CREATED`
- `WAITING_FOR_PLAYERS`
- `READY_CHECK`
- `DECK_SELECTION`
- `DECK_LOCKED`
- `MULLIGAN`
- `IN_GAME`
- `FINISHED`
- `ABANDONED`

Rules:
- deck changes are allowed in `WAITING_FOR_PLAYERS` and `DECK_SELECTION`
- once `DECK_LOCKED`, deck changes are rejected
- `MULLIGAN` creates the `game_id` and assigns live-game ownership
- `IN_GAME` is controlled by the match worker, not generic room code
- on game end, room transitions to `FINISHED`

This matters because the current code mixes room state and game state too freely.

### 19.4 Reconnect model for rooms and games

Implement reconnect deliberately.

For rooms:
- reconnect should restore room membership and selected deck state from PostgreSQL
- presence is restored from Redis heartbeat/session attach

For games:
- if `user_active_game:{user_id}` exists, login/lobby should expose `Resume Match`
- reconnecting socket resubscribes to the authoritative owner
- owner sends the latest game snapshot plus pending decision context

Add a table for recoverable runtime metadata if needed:
- `live_game_sessions`
  - `game_id`
  - `owner_instance_id`
  - `last_snapshot_at`
  - `reconnect_deadline_at`
  - `status`

### 19.5 Recommended implementation phases from here

This is the sequence I would actually execute.

#### Phase 1 — Presence and room persistence
- add Redis to runtime code, not only Docker
- implement `PresenceService`
- add `rooms`, `room_seats`, `room_invites` tables
- move room create/join/leave/invite flows to repository-backed state
- keep current live game start path, but reference room records instead of process-local room objects

Deliverable:
- custom rooms survive backend restart in metadata terms
- lobby presence no longer depends on one process

#### Phase 2 — Websocket auth and reconnect discipline
- attach websocket to a persistent session on connect
- move heartbeat and disconnect handling to Redis-backed presence
- expose `Resume Match` and `Resume Room`
- make reconnect restore room/game subscriptions reliably

Deliverable:
- stable reconnect and session ownership

#### Phase 3 — Match routing ownership
- add `game_owner:{game_id}` leasing
- route commands to owner instance
- separate gateway fanout from live game execution
- snapshot active games periodically

Deliverable:
- safe horizontal scaling for live matches

#### Phase 4 — Matchmaking and queue
- add queue tables plus Redis queue presence
- create queue → ready-check → room/game creation pipeline
- keep custom rooms as a separate product path

Deliverable:
- production casual queue

### 19.6 UX changes required while doing this

Do these alongside backend migration, not after.

Lobby:
- primary buttons should be `Casual`, `Custom Room`, `Bot`, `Goldfish`
- room list should come from server projections, not local assumptions
- show clear member states: `Selecting Deck`, `Ready`, `Disconnected`, `In Match`

Rooms:
- show durable room code / invite state
- deck lock state must be explicit
- once locked, disable deck editing entry points

Games:
- add `Reconnecting…` and `Waiting for opponent to reconnect`
- if reconnect deadline exists, show countdown
- if command is sent to a remote owner instance, keep the immediate optimistic pending state already introduced

### 19.7 What not to do yet

Do **not**:
- move full live board state into PostgreSQL
- implement cross-instance shared mutation of one live game
- replace the match engine with a distributed state machine
- build ranked/MMR before room/game/session ownership is stable

Those would increase complexity without addressing the current structural bottlenecks.

### 19.8 Immediate engineering task list

The next concrete tasks I recommend opening are:

1. Add `redis` dependency and runtime config
2. Implement `PresenceService` with heartbeat + TTL
3. Add PostgreSQL models for `rooms`, `room_seats`, `room_invites`
4. Refactor room create/join/leave APIs to use repository state
5. Attach websocket session at connect time
6. Persist `user_active_room` / `user_active_game` routing state in Redis
7. Add reconnect banner + resume CTA in frontend lobby/profile

That is the shortest path from the current codebase to a production-capable lobby/room architecture.
