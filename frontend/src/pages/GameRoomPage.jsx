import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const GameRoomPage = () => {
  const { roomId } = useParams();
  const { token } = useStore();
  const navigate = useNavigate();
  const [roomState, setRoomState] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadState = async () => {
    if (!token || !roomId) return;
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/state`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load room state.");
      setRoomState(payload);
      setError("");
      if (payload.phase === "FINISHED") navigate(`/games/${roomId}/post-game`, { replace: true });
    } catch (loadError) {
      setError(loadError.message || "Failed to load room state.");
    }
  };

  useEffect(() => {
    void loadState();
    const intervalId = window.setInterval(loadState, 1500);
    return () => window.clearInterval(intervalId);
  }, [roomId, token]);

  const endGame = async () => {
    if (!token || !roomId || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/end`), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to end room.");
      navigate(`/games/${roomId}/post-game`);
    } catch (endError) {
      setError(endError.message || "Failed to end room.");
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 p-4 text-slate-100">
      <section className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-3xl items-center justify-center">
        <div className="w-full rounded-lg border border-slate-800 bg-slate-900 p-6 shadow-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-200">Proxy room</p>
          <h1 className="mt-3 text-3xl font-semibold text-white">Ma vie de poulpe</h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            This room is intentionally empty while the new game logic is being built.
          </p>

          <div className="mt-6 rounded-md border border-slate-800 bg-slate-950 p-4">
            <div className="flex items-center gap-3 text-sm text-slate-300">
              {roomState ? <CheckCircle2 className="text-teal-300" size={18} /> : <Loader2 className="animate-spin text-slate-500" size={18} />}
              <span>{roomState?.message || "Loading room state..."}</span>
            </div>
            {roomState ? (
              <p className="mt-3 font-mono text-xs text-slate-500">
                {roomState.room_id} · rev {roomState.revision}
              </p>
            ) : null}
          </div>

          {error ? <p className="mt-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}

          <div className="mt-6 flex justify-end">
            <button
              className="rounded-md bg-teal-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:cursor-wait disabled:opacity-60"
              disabled={busy}
              onClick={endGame}
              type="button"
            >
              {busy ? "Ending..." : "End and continue"}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
};

export default GameRoomPage;
