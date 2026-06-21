import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useStore } from "../store.js";
import { fetchWithRetry } from "../utils/connection.js";

const LobbyPage = () => {
  const { token, user } = useStore();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadLobby = async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetchWithRetry(
        "/api/lobby/state",
        {
          headers: { Authorization: `Bearer ${token}` },
        },
        { attempts: 5, initialDelayMs: 300, maxDelayMs: 4000 }
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load lobby.");
      setUsers(Array.isArray(payload.users) ? payload.users : []);
    } catch (loadError) {
      setError(loadError.message || "Failed to load lobby.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadLobby();
    const intervalId = window.setInterval(loadLobby, 10000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  return (
    <>
      <section className="grid gap-4 md:grid-cols-[1fr_18rem]">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold text-white">Lobby</h1>
              <p className="mt-1 text-sm text-slate-400">
                Registered players and realtime presence. Game rooms belong in your game layer.
              </p>
            </div>
            <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800" onClick={loadLobby}>
              Refresh
            </button>
          </div>

          {error ? <p className="mt-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}
          {loading ? <p className="mt-6 text-slate-400">Loading lobby...</p> : null}

          <div className="mt-5 divide-y divide-slate-800">
            {users.map((entry) => (
              <div key={entry.id} className="flex items-center justify-between gap-3 py-3">
                <div>
                  <Link className="font-medium text-white hover:text-teal-200" to={`/profile/${entry.id}`}>
                    {entry.username}
                  </Link>
                  <p className="mt-1 text-xs text-slate-500">{entry.id}</p>
                </div>
                <div className="flex items-center gap-2">
                  {entry.is_admin ? (
                    <span className="rounded-full bg-indigo-500/15 px-2 py-1 text-xs text-indigo-200">admin</span>
                  ) : null}
                  <span className={`rounded-full px-2 py-1 text-xs ${entry.online ? "bg-emerald-500/15 text-emerald-200" : "bg-slate-800 text-slate-400"}`}>
                    {entry.online ? "online" : "offline"}
                  </span>
                </div>
              </div>
            ))}
            {!loading && users.length === 0 ? <p className="py-6 text-slate-400">No registered users yet.</p> : null}
          </div>
        </div>

        <aside className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold text-white">Signed in</h2>
          <p className="mt-2 text-sm text-slate-300">{user?.username}</p>
          <p className="mt-1 break-all text-xs text-slate-500">{user?.id}</p>
          <button
            className="mt-4 w-full rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300"
            onClick={() => navigate(`/profile/${user?.id}`)}
          >
            Open profile
          </button>
        </aside>
      </section>
    </>
  );
};

export default LobbyPage;
