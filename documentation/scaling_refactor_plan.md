# Distributed Runtime Refactor Plan (Updated April 25, 2026)

This plan incorporates the latest architectural critique and re-prioritizes work to remove process-local correctness risks before adding more operational tooling.

---

## 1) What was addressed now

### 1.1 Removed process-local runtime registries
- `backend/app/runtime_registry.py` no longer keeps `runtime_users` / `runtime_match_records` in-memory caches.
- Runtime user and match lookup now hydrates from persistent sources:
  - `users` / `user_profiles` (registered users),
  - `room_seats` + `rooms` (bot/virtual identities),
  - `match_participants` + `match_records`.
- `remember_*` / `forget_*` APIs remain as compatibility no-ops.

### 1.2 Removed runtime-match in-memory fallback in admin match listing
- `backend/app/admin_router.py::_all_match_summaries` no longer reads in-memory runtime maps.
- Match summaries are DB-first, then replay artifact fallback.

### 1.3 Removed bridge-local match cache
- `backend/app/distributed/local_runtime_bridge.py` no longer stores `_match_record_cache`.
- Match record lookup is now DB-backed per read (deterministic across workers).

### 1.4 Added per-command runtime cache eviction in worker bridge
- After each processed stream entry (success or failure), worker bridge now evicts per-game process-local runtime caches.
- New hook: `ActiveMatchService.evict_runtime_cache(game_id)` drops:
  - `game_states[game_id]`
  - `turn_managers[game_id]`
  - strategic bot snapshot/query cache entries for that game
- Important: control state required across commands is preserved (`pending_mulligans`, timer state, RNG state).

### 1.5 Lobby membership no longer depends on process-local `LobbyService.users`
- `RoomManager` lobby gating/broadcast now resolves lobby users from presence (`PresenceService`) first.
- Fallback to `LobbyService.users` remains only as compatibility path (tests and non-presence environments), not as primary runtime source-of-truth.
- Matchmaking/challenge/create/join guards now use async lobby checks based on live presence location.

---

## 2) Remaining in-memory components (intentional vs transitional)

## 2.1 Transitional (must be removed for full multi-node determinism)
- `RoomManager.rooms`
- `RoomManager.game_states`, `RoomManager.turn_managers` (now treated as command-scoped caches and actively evicted by worker bridge; still structurally present)
- `LobbyService.users`
- `runtime_state.py` process singletons (`room_manager`, `connection_manager`, `presence_service`)
- `LocalDistributedRuntimeBridge` itself (compatibility bridge; not final worker core)

## 2.2 Intentional local-only state (acceptable during current phase)
- WebSocket connection sockets in `ConnectionManager.active_connections` (node-local by design, cross-node fanout already via Redis pub/sub)

---

## 3) Critical ordering (updated)

1. **Finish in-memory removal from game execution path**
   - Move authoritative match state transitions to worker-owned Redis/DB hydration path only.
   - Keep gateway stateless with enqueue + fanout only.
2. **Then build DLQ tooling/UI**
   - Requeue/purge tooling is useful only after deterministic command handling is guaranteed.

---

## 4) OCC correctness constraints (non-negotiable)

## 4.1 Monotonic versioning
- `version` must only increase.
- Any semantic undo is modeled as a **new compensating command**, never a rewind write.

## 4.2 Idempotency must commit atomically with state
- `command_id` dedupe marker is part of the CAS-committed state payload (`recent_command_ids`), not a separate side write.

## 4.3 Recovery semantics
- `XAUTOCLAIM` reclaim must tolerate zombie workers.
- Stale writer must fail CAS, never overwrite newer committed version.

---

## 5) Required test coverage before “production-ready” claim

## 5.1 Zombie worker chaos test
- Simulate:
  1. worker A reads message,
  2. worker B reclaims and commits,
  3. worker A resumes and tries stale CAS.
- Assert:
  - stale CAS rejected,
  - command applied exactly once,
  - `recent_command_ids` contains one instance.

## 5.2 In-memory-free recovery tests
- Restart worker/gateway with empty process memory.
- Validate ongoing games recover from Redis + DB only.
- Validate no behavior depends on `RoomManager` pre-existing process maps.

## 5.3 Timer fault-tolerance tests
- Timer must survive worker restart and fire once.
- Due events must be driven by Redis schedule state (no `sleep`-bound local timers).

---

## 6) Replay archival hardening

- Keep `game:stream:<game_id>` until archival commit succeeds.
- Archive flow:
  1. consume terminal signal,
  2. serialize stream,
  3. upload object storage,
  4. persist artifact URI in DB,
  5. only then purge/truncate source stream.
- For large streams, prefer streaming/chunked JSON serialization + compression instead of whole-payload `gzip.compress()` in RAM.

---

## 7) Next implementation milestones

1. Replace local bridge execution path with direct worker command dispatcher that does not require in-process `RoomManager` maps.
2. Move lobby/user presence source-of-truth to Redis presence + DB projections (remove `LobbyService.users` dependency).
3. Add zombie-worker OCC chaos tests and timer restart tests.
4. After 1–3, implement DLQ admin operations (inspect/requeue/purge) and runbook.
