import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const GameHistoryPage = () => {
  const { userId } = useParams();
  const { token, user } = useStore();
  const [results, setResults] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const targetUserId = userId || user?.id;
  const isOwnProfile = targetUserId === user?.id;
  const profileSubnavItems = [
    { label: "Profile", to: `/profile/${targetUserId}` },
    { label: "Friends", to: `/profile/${targetUserId}/friends` },
    { label: "History", to: `/profile/${targetUserId}/history` },
  ];

  useEffect(() => {
    const loadHistory = async () => {
      if (!token || !isOwnProfile) {
        setLoading(false);
        return;
      }
      setError("");
      setLoading(true);
      try {
        const response = await fetch(buildApiUrl("/api/game/history"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Failed to load match history.");
        setResults(Array.isArray(payload.results) ? payload.results : []);
      } catch (loadError) {
        setError(loadError.message || "Failed to load match history.");
      } finally {
        setLoading(false);
      }
    };
    void loadHistory();
  }, [isOwnProfile, token]);

  return (
    <>
      <PageSubnavigation items={profileSubnavItems} />

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <h1 className="text-2xl font-semibold text-white">History</h1>
        {!isOwnProfile ? <p className="mt-2 text-slate-400">Match history is private.</p> : null}
        {error ? <p className="mt-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}
        {loading ? <p className="mt-5 text-slate-400">Loading history...</p> : null}
        {!loading && isOwnProfile && results.length === 0 ? <p className="mt-5 text-slate-400">No completed games yet.</p> : null}
        <div className="mt-5 divide-y divide-slate-800">
          {results.map((result) => (
            <Link
              className="flex items-center justify-between gap-3 py-3 text-left hover:bg-slate-950"
              key={result.id}
              to={`/games/${result.room_id}/post-game`}
            >
              <span>
                <span className="font-medium text-white">Proxy room</span>
                <span className="ml-2 text-xs text-slate-500">{new Date(result.created_at).toLocaleString()}</span>
              </span>
              <span className="text-sm text-slate-300">{result.score} score</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
};

export default GameHistoryPage;
