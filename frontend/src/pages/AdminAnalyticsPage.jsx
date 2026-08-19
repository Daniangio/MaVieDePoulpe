import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart3, Brain, CircleCheck, CircleX, Gauge, MapPinned, Shell, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const adminSubnavItems = [
  { label: "Backoffice", to: "/admin" },
  { label: "Game content", to: "/admin/content" },
  { label: "Game analytics", to: "/admin/analytics" },
];

const abilityLabels = {
  agility: "Agility",
  camouflage: "Camouflage",
  force: "Force",
  propulsion: "Propulsion",
  intelligence: "Intelligence",
  team: "Team",
};

const sourceLabel = (source) => source === "bot_simulation" ? "Bot simulation" : "Saved game";
const titleCase = (value) => String(value || "").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

const Distribution = ({ title, rows, tone = "teal" }) => {
  const max = Math.max(1, ...(rows || []).map((entry) => Number(entry.count || 0)));
  return (
    <article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-teal-950">{title}</h3>
      {!rows?.length ? <p className="mt-4 text-sm text-slate-500">No recorded changes yet.</p> : <div className="mt-4 space-y-2">
        {rows.map((entry) => <div className="grid grid-cols-[2.5rem_1fr_2.25rem] items-center gap-2 text-xs" key={entry.value}>
          <span className="font-medium text-slate-600">{entry.value}</span>
          <span className="h-2 overflow-hidden rounded-full bg-cyan-50"><span className={`block h-full rounded-full ${tone === "rose" ? "bg-rose-400" : tone === "violet" ? "bg-violet-400" : "bg-teal-400"}`} style={{ width: `${(Number(entry.count || 0) / max) * 100}%` }} /></span>
          <span className="text-right text-slate-500">{entry.count}</span>
        </div>)}
      </div>}
    </article>
  );
};

const OverviewCard = ({ icon: Icon, label, value, tone = "teal" }) => (
  <article className="flex min-w-0 items-center gap-3 rounded-lg border border-cyan-100 bg-white p-4 shadow-sm">
    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${tone === "amber" ? "bg-amber-100 text-amber-700" : tone === "rose" ? "bg-rose-100 text-rose-700" : "bg-teal-100 text-teal-700"}`}><Icon size={19} /></span>
    <div className="min-w-0"><p className="text-xs text-slate-500">{label}</p><p className="truncate text-xl font-semibold text-teal-950">{value}</p></div>
  </article>
);

const NodeHeatmap = ({ map, visits }) => {
  const max = Math.max(1, ...(visits || []).map((entry) => Number(entry.count || 0)));
  const visitsByNode = useMemo(() => Object.fromEntries((visits || []).map((entry) => [entry.node_id, entry.count])), [visits]);
  const nodes = Object.values(map?.nodes || {});
  if (!nodes.length) return <article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><h3 className="text-sm font-semibold text-teal-950">Visited-node density</h3><p className="mt-4 text-sm text-slate-500">No map data is retained for the selected games.</p></article>;
  const boardImage = map?.image_url ? buildApiUrl(map.image_url) : "";
  return (
    <article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold text-teal-950">Visited-node density</h3><p className="text-xs text-slate-500">A node is counted when Poulpita enters it.</p></div>
      <div className="relative mt-4 overflow-hidden rounded-md border border-cyan-100 bg-cyan-50" style={{ aspectRatio: map?.image_width && map?.image_height ? `${map.image_width} / ${map.image_height}` : "16 / 9", backgroundImage: boardImage ? `url(${boardImage})` : undefined, backgroundSize: "contain", backgroundPosition: "center", backgroundRepeat: "no-repeat" }}>
        {nodes.map((node) => {
          const count = Number(visitsByNode[node.id] || 0);
          const intensity = count / max;
          const size = 18 + intensity * 34;
          return <div className="absolute -translate-x-1/2 -translate-y-1/2" key={node.id} style={{ left: `${Number(node.x || 0) * 100}%`, top: `${Number(node.y || 0) * 100}%` }} title={`${node.id}: ${count} visits`}>
            <span className="flex items-center justify-center rounded-full border-2 border-white font-semibold text-white shadow" style={{ width: size, height: size, backgroundColor: count ? `rgba(13, 148, 136, ${0.35 + intensity * 0.6})` : "rgba(100, 116, 139, 0.35)", fontSize: Math.max(9, size * 0.26) }}>{count || ""}</span>
            <span className="absolute left-1/2 top-full mt-0.5 -translate-x-1/2 rounded bg-white/90 px-1 text-[9px] font-medium text-slate-700 shadow-sm">{node.id}</span>
          </div>;
        })}
      </div>
    </article>
  );
};

const AdminAnalyticsPage = () => {
  const { token, user } = useStore();
  const [levels, setLevels] = useState([]);
  const [levelId, setLevelId] = useState("");
  const [availableGames, setAvailableGames] = useState([]);
  const [selectedGameIds, setSelectedGameIds] = useState([]);
  const [availableNights, setAvailableNights] = useState([]);
  const [selectedNightIndices, setSelectedNightIndices] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(buildApiUrl(path), { ...options, headers: { Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Admin request failed.");
    return payload;
  }, [token]);

  const loadAnalytics = useCallback(async (nextLevelId, gameIds = null, nightIndices = null) => {
    if (!nextLevelId) return;
    setLoading(true);
    setError("");
    try {
      const payload = await request("/api/admin/game-analytics", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level_id: nextLevelId, ...(gameIds ? { game_ids: gameIds } : {}), ...(nightIndices ? { night_indices: nightIndices } : {}) }) });
      setAnalytics(payload.analytics || null);
      if (!gameIds) {
        const allGames = payload.games || [];
        setAvailableGames(allGames);
        setSelectedGameIds(allGames.map((game) => game.id));
      }
      if (!nightIndices) {
        const nights = payload.analytics?.resource_filter?.available_nights || [];
        setAvailableNights(nights);
        setSelectedNightIndices(nights);
      }
    } catch (loadError) {
      setError(loadError.message || "Failed to analyze saved games.");
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    if (!token) return;
    void request("/api/admin/content").then((payload) => {
      const nextLevels = payload.levels || [];
      setLevels(nextLevels);
      if (nextLevels[0]?.id) {
        setLevelId(nextLevels[0].id);
        void loadAnalytics(nextLevels[0].id);
      }
    }).catch((loadError) => setError(loadError.message || "Failed to load levels."));
  }, [loadAnalytics, request, token]);

  const selectLevel = (nextLevelId) => {
    setLevelId(nextLevelId);
    setAvailableGames([]);
    setSelectedGameIds([]);
    setAvailableNights([]);
    setSelectedNightIndices([]);
    setAnalytics(null);
    void loadAnalytics(nextLevelId);
  };

  const toggleGame = (gameId) => {
    const nextIds = selectedGameIds.includes(gameId) ? selectedGameIds.filter((id) => id !== gameId) : [...selectedGameIds, gameId];
    if (!nextIds.length) return;
    setSelectedGameIds(nextIds);
    void loadAnalytics(levelId, nextIds, selectedNightIndices);
  };

  const toggleNight = (night) => {
    const nextNights = selectedNightIndices.includes(night)
      ? selectedNightIndices.filter((entry) => entry !== night)
      : [...selectedNightIndices, night].sort((left, right) => left - right);
    if (!nextNights.length) return;
    setSelectedNightIndices(nextNights);
    void loadAnalytics(levelId, selectedGameIds, nextNights);
  };

  if (!user?.is_admin) return <div className="rounded-lg border border-slate-800 bg-slate-900 p-6"><h1 className="text-2xl font-semibold text-white">Game analytics</h1><p className="mt-2 text-slate-400">Admin access is required.</p><Link className="mt-5 inline-block rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950" to="/lobby">Back to lobby</Link></div>;

  const overview = analytics?.overview || {};
  return <div className="-m-4 min-h-screen bg-gradient-to-b from-cyan-50 via-teal-50 to-white p-4 text-slate-800">
    <PageSubnavigation items={adminSubnavItems} />
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-semibold text-teal-950">Game Analytics</h1><p className="mt-1 text-sm text-teal-800">Compare saved games and bot simulations to tune one level at a time.</p></div>
      <label className="text-sm font-medium text-teal-950">Level<select className="ml-2 rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800 outline-none focus:border-teal-500" value={levelId} onChange={(event) => selectLevel(event.target.value)}>{levels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}</select></label>
    </div>
    {error ? <p className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
    {!levelId ? <p className="rounded-lg border border-cyan-100 bg-white p-5 text-slate-500">Create a level before collecting analytics.</p> : null}
    {levelId ? <>
      <section className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold text-teal-950">Games included</h2><p className="text-xs text-slate-500">Choose completed normal games and saved bot simulations for this level.</p></div><button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50" disabled={loading} onClick={() => void loadAnalytics(levelId, selectedGameIds, selectedNightIndices)} type="button">Refresh</button></div>
        <div className="mt-3 max-h-48 overflow-y-auto pr-2"><div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{availableGames.map((game) => <label className={`flex cursor-pointer items-center gap-3 rounded-md border p-3 ${selectedGameIds.includes(game.id) ? "border-teal-300 bg-teal-50" : "border-cyan-100 bg-white"}`} key={game.id}><input checked={selectedGameIds.includes(game.id)} onChange={() => toggleGame(game.id)} type="checkbox" /><span className="min-w-0"><span className="block truncate text-sm font-medium text-teal-950">{sourceLabel(game.source)} · {game.outcome}</span><span className="block text-xs text-slate-500">Day {game.final_day} · {game.final_energy} energy · {new Date(game.created_at).toLocaleString()}{game.detail_level === "event_log" ? " · event log detail" : ""}</span></span></label>)}{!availableGames.length ? <p className="py-3 text-sm text-slate-500">No saved games exist for this level yet.</p> : null}</div></div>
      </section>
      {loading ? <p className="mt-5 text-sm text-teal-700">Refreshing balance data...</p> : null}
      {analytics ? <div className="mt-5 space-y-5">
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><OverviewCard icon={BarChart3} label="Games" value={overview.games || 0} /><OverviewCard icon={CircleCheck} label="Win rate" value={`${overview.win_rate || 0}%`} /><OverviewCard icon={Gauge} label="Average final day" value={overview.average_final_day || 0} tone="amber" /><OverviewCard icon={Zap} label="Average final energy" value={overview.average_final_energy || 0} tone="amber" /><OverviewCard icon={Brain} label="Average steps" value={overview.average_steps || 0} /></section>
        <section className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-teal-950">Per-night resource filter</h2><p className="text-xs text-slate-500">Filter only the distributions and subtotal below.</p></div><div className="flex flex-wrap gap-2">{availableNights.map((night) => <label className={`cursor-pointer rounded-md border px-3 py-2 text-sm ${selectedNightIndices.includes(night) ? "border-teal-300 bg-teal-50 text-teal-900" : "border-cyan-100 bg-white text-slate-500"}`} key={night}><input className="sr-only" checked={selectedNightIndices.includes(night)} onChange={() => toggleNight(night)} type="checkbox" />Night {night}</label>)}</div></div><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><OverviewCard icon={Zap} label="Energy gained" value={analytics.resource_filter?.totals?.energy_gained_per_night || 0} /><OverviewCard icon={Zap} label="Energy lost" value={analytics.resource_filter?.totals?.energy_lost_per_night || 0} tone="rose" /><OverviewCard icon={Brain} label="Neurons gained" value={analytics.resource_filter?.totals?.neurons_gained_per_night || 0} /><OverviewCard icon={Brain} label="Neurons spent" value={analytics.resource_filter?.totals?.neurons_spent_per_night || 0} tone="rose" /><OverviewCard icon={Shell} label="Night samples" value={analytics.resource_filter?.samples || 0} tone="amber" /></div></section>
        <section className="grid gap-4 xl:grid-cols-4"><Distribution title="Energy gained per night" rows={analytics.resource_distributions?.energy_gained_per_night} /><Distribution title="Energy lost per night" rows={analytics.resource_distributions?.energy_lost_per_night} tone="rose" /><Distribution title="Neurons gained per night" rows={analytics.resource_distributions?.neurons_gained_per_night} tone="violet" /><Distribution title="Neurons spent per night" rows={analytics.resource_distributions?.neurons_spent_per_night} tone="rose" /></section>
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.6fr)]"><NodeHeatmap map={analytics.map} visits={analytics.node_visits} /><div className="space-y-4"><article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><h3 className="text-sm font-semibold text-teal-950">Interactions</h3><div className="mt-4 grid grid-cols-3 gap-2 text-center"><div><p className="text-lg font-semibold text-teal-950">{analytics.interaction_outcomes?.resolved || 0}</p><p className="text-xs text-slate-500">resolved</p></div><div><p className="text-lg font-semibold text-rose-600">{analytics.interaction_outcomes?.failed || 0}</p><p className="text-xs text-slate-500">failed</p></div><div><p className="text-lg font-semibold text-teal-700">{analytics.interaction_outcomes?.success_rate || 0}%</p><p className="text-xs text-slate-500">success rate</p></div></div></article><article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><h3 className="text-sm font-semibold text-teal-950">Special powers</h3><div className="mt-3 space-y-2 text-sm">{analytics.special_abilities?.map((entry) => <div className="flex justify-between" key={entry.ability_id}><span>{abilityLabels[entry.ability_id] || titleCase(entry.ability_id)}</span><span className="font-semibold text-teal-800">{entry.count}</span></div>)}{!analytics.special_abilities?.length ? <p className="text-sm text-slate-500">No special powers used.</p> : null}</div></article></div></section>
        <section className="grid gap-4 lg:grid-cols-2"><article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><h3 className="text-sm font-semibold text-teal-950">Upgrades bought by day</h3><div className="mt-4 flex flex-wrap gap-2">{analytics.upgrades_by_day?.map((entry) => <span className="rounded-md bg-violet-50 px-3 py-2 text-sm text-violet-800" key={entry.day}>Day {entry.day}: <strong>{entry.count}</strong></span>)}{!analytics.upgrades_by_day?.length ? <p className="text-sm text-slate-500">No upgrades bought.</p> : null}</div></article><article className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><h3 className="text-sm font-semibold text-teal-950">Outcomes and loss reasons</h3><div className="mt-3 grid gap-3 sm:grid-cols-2"><div>{analytics.outcomes?.map((entry) => <p className="flex justify-between text-sm" key={entry.id}><span>{titleCase(entry.id)}</span><strong>{entry.count}</strong></p>)}</div><div>{analytics.loss_reasons?.map((entry) => <p className="flex justify-between gap-3 text-sm" key={entry.id}><span className="truncate">{titleCase(entry.id)}</span><strong>{entry.count}</strong></p>)}{!analytics.loss_reasons?.length ? <p className="text-sm text-slate-500">No loss reasons recorded.</p> : null}</div></div></article></section>
        <section className="rounded-lg border border-cyan-100 bg-white p-4 shadow-sm"><div className="flex items-center gap-2"><MapPinned size={18} className="text-teal-600" /><h3 className="text-sm font-semibold text-teal-950">Actions by ability</h3></div><div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{analytics.actions_by_ability?.map((entry) => <article className="rounded-md border border-cyan-100 bg-cyan-50/40 p-3" key={entry.ability_id}><div className="flex justify-between"><h4 className="font-semibold text-teal-950">{abilityLabels[entry.ability_id] || titleCase(entry.ability_id)}</h4><span className="text-sm text-slate-500">{entry.total}</span></div><div className="mt-3 space-y-1.5">{entry.actions.map((action) => <div className="flex justify-between text-xs" key={action.id}><span className="text-slate-600">{action.label}</span><strong className="text-teal-800">{action.count}</strong></div>)}</div></article>)}{!analytics.actions_by_ability?.length ? <p className="text-sm text-slate-500">No actions recorded for the selected games.</p> : null}</div></section>
      </div> : null}
    </> : null}
  </div>;
};

export default AdminAnalyticsPage;
