import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import BoardView from "../components/BoardView";
import { useStore } from "../store.js";
import type { CapabilityProjection, CommandRejection, GameProjection, NodeId } from "../types/game";
import { buildApiUrl, buildWsUrl } from "../utils/connection.js";

const makeCommandId = () =>
  globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `cmd_${Date.now()}_${Math.random()}`;

const phaseLabel = (projection: GameProjection | null) => {
  if (!projection) return "Loading";
  if (projection.phase === "setup") return "Setup";
  if (projection.phase === "game_over") return "Game over";
  return `Night ${projection.day_index || 1}`;
};

const CapabilityBoard = ({
  capability,
  active,
  focused,
  compact,
  pending,
  moveMode,
  onFocus,
  onTakeControl,
  onCollect,
  onMoveMode,
}: {
  capability: CapabilityProjection;
  active: boolean;
  focused: boolean;
  compact?: boolean;
  pending: boolean;
  moveMode: boolean;
  onFocus?: () => void;
  onTakeControl?: () => void;
  onCollect?: () => void;
  onMoveMode?: () => void;
}) => (
  <article
    className={[
      "group relative min-w-0 rounded-md border bg-slate-900 text-slate-100 shadow-xl transition",
      active ? "border-teal-300" : focused ? "border-amber-300" : "border-slate-700",
      compact ? "h-full p-2 hover:z-40 hover:h-52 hover:bg-slate-900" : "h-full p-3",
    ].join(" ")}
    onDoubleClick={onFocus}
  >
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <h3 className="truncate text-sm font-semibold text-white">{capability.name}</h3>
        <p className="text-xs text-slate-400">{active ? "Controls Poulpita" : focused ? "In focus" : "Waiting"}</p>
      </div>
      <div className="rounded bg-slate-800 px-2 py-1 text-xs font-semibold text-teal-100">{capability.pa} AP</div>
    </div>
    <div className={compact ? "mt-2 grid grid-cols-2 gap-2 text-xs" : "mt-3 grid grid-cols-3 gap-2 text-xs"}>
      <div className="rounded bg-slate-800 p-2">
        <span className="block text-slate-400">Control</span>
        <strong>
          {capability.control_takes_this_night}/{capability.max_control_takes_per_night}
        </strong>
      </div>
      <div className="rounded bg-slate-800 p-2">
        <span className="block text-slate-400">Actions</span>
        <strong>
          {capability.actions_taken_this_control}/{capability.max_actions_per_control}
        </strong>
      </div>
      {!compact ? (
        <div className="rounded bg-slate-800 p-2">
          <span className="block text-slate-400">Focus</span>
          <strong>{focused ? "Yes" : "No"}</strong>
        </div>
      ) : null}
    </div>
    {compact ? <p className="mt-2 hidden text-xs text-slate-400 group-hover:block">Double-click to focus this board.</p> : null}
    {!compact ? (
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="rounded bg-teal-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50"
          disabled={pending || active}
          onClick={onTakeControl}
          type="button"
        >
          Take control
        </button>
        <button
          className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-50"
          disabled={pending || !active}
          onClick={onCollect}
          type="button"
        >
          Collect AP
        </button>
        <button
          className={[
            "rounded border px-3 py-2 text-xs text-slate-100 disabled:opacity-50",
            moveMode ? "border-amber-300 bg-amber-950" : "border-slate-600 hover:bg-slate-800",
          ].join(" ")}
          disabled={pending || !active || capability.pa < 1}
          onClick={onMoveMode}
          type="button"
        >
          Move
        </button>
      </div>
    ) : null}
  </article>
);

const GameRoomPage = () => {
  const { roomId } = useParams();
  const { token, user } = useStore();
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [maps, setMaps] = useState<Array<{ id: string; name: string }>>([]);
  const [focusedCapabilityId, setFocusedCapabilityId] = useState<string | null>(null);
  const [moveMode, setMoveMode] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const capabilityMap = projection?.capabilities || {};
  const capabilities = useMemo(() => {
    if (!projection) return [];
    if (projection.player_boards?.length) return projection.player_boards;
    return (projection.capability_order || Object.keys(capabilityMap))
      .map((id) => capabilityMap[id])
      .filter(Boolean);
  }, [capabilityMap, projection]);
  const selectedCapabilityId = focusedCapabilityId || projection?.focused_capability_id || capabilities[0]?.id || "";
  const selectedCapability = selectedCapabilityId ? capabilityMap[selectedCapabilityId] : null;
  const otherCapabilities = capabilities.filter((capability) => capability.id !== selectedCapabilityId);

  useEffect(() => {
    if (projection && !focusedCapabilityId) {
      setFocusedCapabilityId(projection.focused_capability_id || projection.capability_order?.[0] || null);
    }
  }, [focusedCapabilityId, projection]);

  const latestEvent = useMemo(() => {
    const events = projection?.events || [];
    return events.length ? events[events.length - 1] : null;
  }, [projection?.events]);

  const loadProjection = async () => {
    if (!token || !roomId) return;
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/state`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load game state.");
      setProjection(payload);
      setError("");
    } catch (loadError: any) {
      setError(loadError.message || "Failed to load game state.");
    }
  };

  useEffect(() => {
    void loadProjection();
  }, [roomId, token]);

  useEffect(() => {
    const loadMaps = async () => {
      if (!token) return;
      try {
        const response = await fetch(buildApiUrl("/api/game/maps"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Failed to load maps.");
        setMaps(payload.maps || []);
      } catch (loadError: any) {
        setError(loadError.message || "Failed to load maps.");
      }
    };
    void loadMaps();
  }, [token]);

  useEffect(() => {
    if (!token || !roomId) return undefined;
    const socket = new WebSocket(buildWsUrl(`/api/game/rooms/${roomId}/ws`, { token }));
    socketRef.current = socket;
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message?.type === "state_projection") {
          setProjection(message.payload);
          setError("");
        }
      } catch (_error) {
        setError("Received an invalid room update.");
      }
    };
    socket.onerror = () => setError("Room websocket is unavailable; HTTP commands will still work.");
    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;
    };
    return () => {
      socketRef.current = null;
      socket.close(1000, "leaving room");
    };
  }, [roomId, token]);

  const submitCommand = async (type: string, payload: Record<string, unknown> = {}) => {
    if (!token || !roomId || pending) return null;
    setPending(true);
    setFeedback("");
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/commands`), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          command_id: makeCommandId(),
          room_id: roomId,
          actor_user_id: user?.id,
          actor_seat_id: "goldfish",
          expected_version: projection?.version ?? 0,
          type,
          payload,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || "Command failed.");
      if (result.ok === false) {
        const rejection = result as CommandRejection;
        setFeedback(rejection.message || rejection.reason || "Command rejected.");
        if (rejection.projection) setProjection(rejection.projection);
        return result;
      }
      if (result.projection) setProjection(result.projection);
      return result;
    } catch (commandError: any) {
      setError(commandError.message || "Command failed.");
      return null;
    } finally {
      setPending(false);
    }
  };

  const startGoldfishGame = () => {
    void submitCommand("start_goldfish_game");
  };

  const selectMap = (mapId: string) => {
    setMoveMode(false);
    void submitCommand("select_map", { map_id: mapId });
  };

  const takeControl = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("take_control", { capability_id: selectedCapabilityId });
  };

  const collectActionPoints = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("collect_action_points", { capability_id: selectedCapabilityId });
  };

  const movePoulpita = (targetNodeId: NodeId) => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("move_poulpita", {
      capability_id: selectedCapabilityId,
      target_node_id: targetNodeId,
    });
  };

  const endGame = async () => {
    if (!token || !roomId || pending) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/end`), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to end room.");
      navigate(`/games/${roomId}/post-game`);
    } catch (endError: any) {
      setError(endError.message || "Failed to end room.");
      setPending(false);
    }
  };

  return (
    <main className="h-screen overflow-hidden bg-slate-950 text-slate-100">
      <header className="flex h-[5vh] min-h-10 items-center justify-between border-b border-slate-800 bg-slate-900 px-4">
        <div className="min-w-0 text-sm">
          <span className="font-semibold text-white">Ma vie de poulpe</span>
          <span className="ml-3 text-slate-400">v{projection?.version ?? "-"} - {phaseLabel(projection)}</span>
        </div>
        <div className="flex items-center gap-2">
          {projection?.phase === "setup" ? (
            <>
              <select
                className="h-8 rounded border border-slate-700 bg-slate-950 px-2 text-xs text-white"
                disabled={pending || !maps.length}
                onChange={(event) => selectMap(event.target.value)}
                value={projection.selected_map_id || projection.map.id || ""}
              >
                {maps.map((map) => (
                  <option key={map.id} value={map.id}>
                    {map.name}
                  </option>
                ))}
              </select>
              <button className="rounded bg-teal-400 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending} onClick={startGoldfishGame} type="button">
                Start
              </button>
            </>
          ) : null}
          <button className="rounded border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50" disabled={pending} onClick={endGame} type="button">
            End game
          </button>
        </div>
      </header>

      <section className="relative z-30 grid h-[15vh] grid-cols-4 gap-2 overflow-visible border-b border-slate-800 bg-slate-950 px-4 py-1">
        {otherCapabilities.map((capability) => (
          <CapabilityBoard
            active={projection?.active_capability_id === capability.id}
            capability={capability}
            compact
            focused={false}
            key={capability.id}
            moveMode={moveMode}
            onFocus={() => {
              setFocusedCapabilityId(capability.id);
              setMoveMode(false);
            }}
            pending={pending}
          />
        ))}
      </section>

      {feedback || error ? (
        <div className="pointer-events-none fixed left-1/2 top-[22vh] z-50 w-[min(42rem,calc(100vw-2rem))] -translate-x-1/2">
          {feedback ? <p className="rounded-md border border-amber-500/50 bg-amber-950/95 px-3 py-2 text-sm text-amber-100">{feedback}</p> : null}
          {error ? <p className="mt-2 rounded-md border border-rose-500/50 bg-rose-950/95 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
        </div>
      ) : null}

      <section className="grid h-[50vh] grid-cols-[minmax(0,75%)_minmax(14rem,25%)] overflow-hidden">
        <div className="min-w-0 overflow-hidden border-r border-slate-800">
          {projection ? (
            <BoardView moveMode={moveMode} onMove={movePoulpita} pending={pending} projection={projection} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">Loading room state.</div>
          )}
        </div>
        <aside className="flex h-full flex-col gap-3 overflow-hidden bg-slate-900 p-4">
          <div>
            <p className="text-xs uppercase text-slate-500">Poulpita</p>
            <h2 className="mt-1 text-xl font-semibold text-white">{phaseLabel(projection)}</h2>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Node</span>
              <strong>{projection?.poulpita.node_id || "-"}</strong>
            </div>
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Time</span>
              <strong>{projection?.night_time_spent ?? 0}/24</strong>
            </div>
          </div>
          <div className="rounded bg-slate-800 p-3 text-xs text-slate-300">
            <span className="block text-slate-400">Initiative</span>
            <p className="mt-1">{projection?.active_capability_id ? capabilityMap[projection.active_capability_id]?.name : "No capability controls Poulpita."}</p>
          </div>
          {latestEvent ? <p className="mt-auto text-xs text-slate-500">Latest: {String(latestEvent.type || "event")}</p> : null}
        </aside>
      </section>

      <section className="grid h-[30vh] grid-cols-[minmax(18rem,28rem)_1fr] gap-2 overflow-hidden border-t border-slate-800 bg-slate-950 p-1">
        {selectedCapability ? (
          <CapabilityBoard
            active={projection?.active_capability_id === selectedCapability.id}
            capability={selectedCapability}
            focused
            moveMode={moveMode}
            onCollect={collectActionPoints}
            onMoveMode={() => setMoveMode((value) => !value)}
            onTakeControl={takeControl}
            pending={pending}
          />
        ) : (
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-sm text-slate-400">No focused player board.</div>
        )}
        <div className="grid h-full grid-cols-[1fr_12rem] gap-3 overflow-hidden">
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
            <h3 className="text-sm font-semibold text-white">Player hand</h3>
            <div className="mt-3 flex h-[calc(100%-2rem)] items-center justify-center rounded border border-dashed border-slate-700 text-sm text-slate-500">
              Cards are not implemented in Goldfish mode.
            </div>
          </div>
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400">
            <h3 className="text-sm font-semibold text-white">Action track</h3>
            <p className="mt-2">{selectedCapability?.actions_taken_this_control ?? 0} actions this control.</p>
            {moveMode ? <p className="mt-2 text-amber-200">Click an adjacent map node.</p> : null}
          </div>
        </div>
      </section>
    </main>
  );
};

export default GameRoomPage;
