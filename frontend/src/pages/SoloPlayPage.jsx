import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const playSubnavItems = [
  { label: "Solo Play", to: "/play/solo" },
];

const SoloPlayPage = () => {
  const { token } = useStore();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [maps, setMaps] = useState([]);
  const [selectedMapId, setSelectedMapId] = useState("");

  useEffect(() => {
    const loadMaps = async () => {
      if (!token) return;
      try {
        const response = await fetch(buildApiUrl("/api/game/maps"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Failed to load maps.");
        const loadedMaps = payload.maps || [];
        setMaps(loadedMaps);
        if (loadedMaps.length && !loadedMaps.some((entry) => entry.id === selectedMapId)) {
          setSelectedMapId(loadedMaps[0].id);
        }
      } catch (loadError) {
        setError(loadError.message || "Failed to load maps.");
      }
    };
    void loadMaps();
  }, [token]);

  const createQuickMatch = async () => {
    if (!token || creating || !selectedMapId) return;
    setCreating(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl("/api/game/rooms"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ mode: "solo", game_type: "goldfish", map_id: selectedMapId }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to create game room.");
      navigate(`/games/${payload.id}`);
    } catch (createError) {
      setError(createError.message || "Failed to create game room.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <PageSubnavigation items={playSubnavItems} />

      <section className="mb-5">
        <h1 className="text-2xl font-semibold text-white">Solo Play</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">
          Start a map-only goldfish room and move Poulpita around an admin-created board.
        </p>
      </section>

      {error ? <p className="mb-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}

      <section className="mb-4 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <label className="block max-w-lg text-sm">
          <span className="font-medium text-slate-300">Map</span>
          <select
            className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white"
            value={selectedMapId}
            onChange={(event) => setSelectedMapId(event.target.value)}
          >
            {maps.map((map) => (
              <option key={map.id} value={map.id}>
                {map.name}
              </option>
            ))}
          </select>
          {!maps.length ? <span className="mt-2 block text-xs text-amber-300">Create a map in the admin console before starting.</span> : null}
        </label>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <ModeCard
          title="Story"
          description="Prepared for future Ma vie de poulpe content."
          disabled
        />
        <ModeCard
          title="Rooms"
          description="Prepared for future multiplayer and custom room flows."
          disabled
        />
        <ModeCard
          title="Goldfish"
          description="Create a solo room with the movement-only Phase 1 prototype."
          actionLabel={creating ? "Creating..." : "Start"}
          onClick={createQuickMatch}
          disabled={creating || !selectedMapId}
        />
      </section>
    </>
  );
};

const ModeCard = ({ title, description, actionLabel = "Coming soon", disabled = false, onClick }) => (
  <article className="flex min-h-[15rem] flex-col justify-between rounded-lg border border-slate-800 bg-slate-900 p-5">
    <div>
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
    </div>
    <button
      className="mt-6 rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:border disabled:border-slate-700 disabled:bg-slate-950 disabled:text-slate-500"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {actionLabel}
    </button>
  </article>
);

export default SoloPlayPage;
