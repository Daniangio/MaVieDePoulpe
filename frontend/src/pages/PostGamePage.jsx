import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const PostGamePage = () => {
  const { roomId } = useParams();
  const { token, user } = useStore();
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;

    const loadResult = async () => {
      if (!token || !roomId || cancelled) return;
      attempts += 1;
      try {
        const response = await fetch(buildApiUrl(`/api/game/results/${roomId}`), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (response.status === 404 && attempts < 10) {
          window.setTimeout(loadResult, 500);
          return;
        }
        if (!response.ok) throw new Error(payload.detail || "Failed to load result.");
        if (!cancelled) setResult(payload);
      } catch (loadError) {
        if (!cancelled) setError(loadError.message || "Failed to load result.");
      }
    };

    void loadResult();
    return () => {
      cancelled = true;
    };
  }, [roomId, token]);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-200">Post-game</p>
      <h1 className="mt-3 text-2xl font-semibold text-white">Results</h1>
      {error ? <p className="mt-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}
      {!result && !error ? <p className="mt-4 text-slate-400">Preparing results...</p> : null}
      {result ? (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <Metric label="Outcome" value={result.outcome} />
            <Metric label="Score" value={result.score} />
            <Metric label="Turns" value={result.turns} />
          </div>
          <p className="mt-5 text-sm text-slate-300">{result.summary}</p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950" to="/play/solo">
              Play again
            </Link>
            <Link className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800" to={`/profile/${user?.id}/history`}>
              Match history
            </Link>
          </div>
        </>
      ) : null}
    </section>
  );
};

const Metric = ({ label, value }) => (
  <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
    <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</dt>
    <dd className="mt-2 text-xl font-semibold capitalize text-white">{value}</dd>
  </div>
);

export default PostGamePage;
