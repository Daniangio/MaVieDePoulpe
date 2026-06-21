import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import BoardView from "../components/BoardView";
import { useStore } from "../store.js";
import type { CommandRejection, GameProjection, NodeId } from "../types/game";
import { buildApiUrl, buildWsUrl } from "../utils/connection.js";

const activeCapabilityId = "poulpita";

const makeCommandId = () =>
  globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `cmd_${Date.now()}_${Math.random()}`;

const GameRoomPage = () => {
  const { roomId } = useParams();
  const { token, user } = useStore();
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

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

  const movePoulpita = (targetNodeId: NodeId) => {
    void submitCommand("move_poulpita", {
      capability_id: activeCapabilityId,
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
    <main className="min-h-screen bg-slate-950 p-4 text-slate-100">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-200">Goldfish prototype</p>
            <h1 className="mt-2 text-2xl font-semibold text-white">Ma vie de poulpe</h1>
            <p className="mt-2 text-sm text-slate-400">
              Room {roomId} · version {projection?.version ?? "-"} · phase {projection?.phase || "loading"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {projection?.phase === "setup" ? (
              <button
                className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-60"
                disabled={pending}
                onClick={startGoldfishGame}
                type="button"
              >
                Start goldfish game
              </button>
            ) : null}
            <button
              className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
              disabled={pending}
              onClick={() => void loadProjection()}
              type="button"
            >
              Refresh
            </button>
            <button
              className="rounded-md border border-rose-500/60 px-3 py-2 text-sm text-rose-100 hover:bg-rose-950 disabled:opacity-60"
              disabled={pending}
              onClick={endGame}
              type="button"
            >
              End
            </button>
          </div>
        </header>

        {feedback ? <p className="rounded-md border border-amber-500/40 bg-amber-950/40 px-3 py-2 text-sm text-amber-100">{feedback}</p> : null}
        {error ? <p className="rounded-md border border-rose-500/40 bg-rose-950/60 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

        {projection?.phase === "setup" ? (
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-6 text-sm text-slate-300">
            Create the authoritative GameState by starting the goldfish game.
          </section>
        ) : null}

        {projection && projection.phase !== "setup" ? (
          <BoardView onMove={movePoulpita} pending={pending} projection={projection} />
        ) : null}

        {latestEvent ? (
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">
            <span className="font-semibold text-white">Latest event:</span> {String(latestEvent.type || "event")}
            {"from_node_id" in latestEvent && "to_node_id" in latestEvent ? (
              <span>
                {" "}
                {String(latestEvent.from_node_id)} -&gt; {String(latestEvent.to_node_id)}
              </span>
            ) : null}
          </section>
        ) : null}
      </div>
    </main>
  );
};

export default GameRoomPage;
