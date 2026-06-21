import { useEffect, useMemo, useState } from "react";
import HexTilePreview from "./HexTilePreview.jsx";
import { buildApiUrl } from "../utils/connection.js";

const emptyLevelDraft = () => ({
  id: "",
  name: "Untitled level",
  map_id: "",
  node_tile_counts: {},
  node_group_ids: {},
  groups: [{ id: "group-1", name: "Group 1", tile_counts: {} }],
});

const groupColors = ["#0d9488", "#2563eb", "#c026d3", "#ea580c", "#16a34a", "#be123c", "#7c3aed", "#0891b2"];

const AdminLevelEditor = ({ request, content, busy, setBusy, setError, onReload }) => {
  const [maps, setMaps] = useState([]);
  const [draft, setDraft] = useState(emptyLevelDraft());

  const tilesById = useMemo(() => Object.fromEntries((content.tiles || []).map((tile) => [tile.id, tile])), [content.tiles]);
  const eventsById = useMemo(() => Object.fromEntries((content.events || []).map((event) => [event.id, event])), [content.events]);
  const interactionsById = useMemo(() => Object.fromEntries((content.interactions || []).map((interaction) => [interaction.id, interaction])), [content.interactions]);
  const selectedMap = useMemo(() => maps.find((map) => map.id === draft.map_id) || null, [draft.map_id, maps]);
  const nodes = useMemo(() => Object.values(selectedMap?.nodes || {}).sort((a, b) => a.id.localeCompare(b.id)), [selectedMap]);
  const groupsById = useMemo(() => Object.fromEntries((draft.groups || []).map((group, index) => [group.id, { ...group, color: groupColors[index % groupColors.length] }])), [draft.groups]);

  const groupStats = useMemo(() => {
    return Object.fromEntries((draft.groups || []).map((group) => {
      const capacity = nodes.reduce((total, node) => total + (draft.node_group_ids[node.id] === group.id ? Number(draft.node_tile_counts[node.id] || 0) : 0), 0);
      const assigned = Object.values(group.tile_counts || {}).reduce((total, count) => total + Number(count || 0), 0);
      return [group.id, { capacity, assigned, valid: capacity === assigned }];
    }));
  }, [draft.groups, draft.node_group_ids, draft.node_tile_counts, nodes]);

  const canSave = nodes.length > 0 && nodes.every((node) => draft.node_group_ids[node.id]) && Object.values(groupStats).every((stats) => stats.valid);

  const levelFromMap = (map, base = emptyLevelDraft()) => {
    const groupId = base.groups?.[0]?.id || "group-1";
    const mapNodes = Object.keys(map?.nodes || {});
    return {
      ...base,
      map_id: map?.id || "",
      node_tile_counts: Object.fromEntries(mapNodes.map((nodeId) => [nodeId, Number(base.node_tile_counts?.[nodeId] ?? 3)])),
      node_group_ids: Object.fromEntries(mapNodes.map((nodeId) => [nodeId, base.node_group_ids?.[nodeId] || groupId])),
      groups: base.groups?.length ? base.groups : [{ id: groupId, name: "Group 1", tile_counts: {} }],
    };
  };

  const loadMaps = async () => {
    try {
      const payload = await request("/api/admin/maps");
      const loadedMaps = payload.maps || [];
      setMaps(loadedMaps);
      if (!draft.map_id && loadedMaps.length) setDraft(levelFromMap(loadedMaps[0]));
    } catch (loadError) {
      setError(loadError.message || "Failed to load maps.");
    }
  };

  useEffect(() => {
    void loadMaps();
  }, []);

  const startNewLevel = () => {
    const firstMap = maps[0] || null;
    setDraft(levelFromMap(firstMap, emptyLevelDraft()));
  };

  const editLevel = (level) => {
    const map = maps.find((entry) => entry.id === level.map_id) || null;
    setDraft(levelFromMap(map, { ...emptyLevelDraft(), ...level, groups: level.groups || [] }));
  };

  const changeMap = (mapId) => {
    const map = maps.find((entry) => entry.id === mapId) || null;
    setDraft(levelFromMap(map, { ...draft, id: "", map_id: mapId }));
  };

  const updateNode = (nodeId, patch) => {
    setDraft((current) => ({
      ...current,
      node_tile_counts: patch.tile_count === undefined ? current.node_tile_counts : { ...current.node_tile_counts, [nodeId]: Math.max(0, Number(patch.tile_count || 0)) },
      node_group_ids: patch.group_id === undefined ? current.node_group_ids : { ...current.node_group_ids, [nodeId]: patch.group_id },
    }));
  };

  const addGroup = () => {
    setDraft((current) => {
      let index = (current.groups || []).length + 1;
      let id = `group-${index}`;
      while ((current.groups || []).some((group) => group.id === id)) {
        index += 1;
        id = `group-${index}`;
      }
      return { ...current, groups: [...(current.groups || []), { id, name: `Group ${index}`, tile_counts: {} }] };
    });
  };

  const updateGroup = (groupId, patch) => {
    setDraft((current) => ({
      ...current,
      groups: (current.groups || []).map((group) => (group.id === groupId ? { ...group, ...patch } : group)),
    }));
  };

  const removeGroup = (groupId) => {
    setDraft((current) => {
      const groups = (current.groups || []).filter((group) => group.id !== groupId);
      const fallback = groups[0]?.id || "";
      return {
        ...current,
        groups,
        node_group_ids: Object.fromEntries(Object.entries(current.node_group_ids || {}).map(([nodeId, assignedGroupId]) => [nodeId, assignedGroupId === groupId ? fallback : assignedGroupId])),
      };
    });
  };

  const setGroupTileCount = (groupId, tileId, count) => {
    setDraft((current) => ({
      ...current,
      groups: (current.groups || []).map((group) => {
        if (group.id !== groupId) return group;
        const tileCounts = { ...(group.tile_counts || {}) };
        const normalizedCount = Math.max(0, Number(count || 0));
        if (normalizedCount) tileCounts[tileId] = normalizedCount;
        else delete tileCounts[tileId];
        return { ...group, tile_counts: tileCounts };
      }),
    }));
  };

  const saveLevel = async () => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", draft.name);
      form.set("map_id", draft.map_id);
      form.set("node_tile_counts_json", JSON.stringify(draft.node_tile_counts || {}));
      form.set("node_group_ids_json", JSON.stringify(draft.node_group_ids || {}));
      form.set("groups_json", JSON.stringify(draft.groups || []));
      const saved = await request(draft.id ? `/api/admin/content/levels/${draft.id}` : "/api/admin/content/levels", { method: draft.id ? "PUT" : "POST", body: form });
      setDraft(saved);
      await onReload();
    } catch (saveError) {
      setError(saveError.message || "Failed to save level.");
    } finally {
      setBusy(false);
    }
  };

  const deleteLevel = async (level) => {
    if (!window.confirm(`Delete ${level.name}?`)) return;
    setBusy(true);
    setError("");
    try {
      await request(`/api/admin/content/levels/${level.id}`, { method: "DELETE" });
      if (draft.id === level.id) startNewLevel();
      await onReload();
    } catch (deleteError) {
      setError(deleteError.message || "Failed to delete level.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-cyan-200 bg-white/90 p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-teal-950">Levels</h2>
          <p className="mt-1 text-sm text-slate-600">Assign map nodes to groups and fill each group with the exact number of tile copies.</p>
        </div>
        <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50" onClick={startNewLevel} type="button">New level</button>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[16rem_1fr]">
        <aside className="space-y-2">
          {(content.levels || []).map((level) => (
            <div className="flex items-center justify-between gap-2 rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={level.id}>
              <button className="min-w-0 flex-1 text-left text-sm text-slate-700 hover:text-teal-800" onClick={() => editLevel(level)} type="button">
                <span className="block truncate font-medium">{level.name}</span>
                <span className="text-xs text-slate-500">{maps.find((map) => map.id === level.map_id)?.name || level.map_id}</span>
              </button>
              <button className="rounded border border-rose-300 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" disabled={busy} onClick={() => deleteLevel(level)} type="button">Delete</button>
            </div>
          ))}
          {(content.levels || []).length === 0 ? <p className="rounded-md border border-cyan-100 bg-cyan-50 p-3 text-sm text-slate-500">No levels yet.</p> : null}
        </aside>

        <div className="grid gap-4">
          <div className="grid gap-3 lg:grid-cols-[1fr_18rem]">
            <label className="block text-sm">
              <span className="text-slate-600">Level name</span>
              <input className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800" value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Map</span>
              <select className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800" value={draft.map_id} onChange={(event) => changeMap(event.target.value)}>
                {maps.map((map) => <option key={map.id} value={map.id}>{map.name}</option>)}
              </select>
            </label>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(24rem,1fr)_22rem]">
            <LevelMap map={selectedMap} groupsById={groupsById} nodeGroupIds={draft.node_group_ids} />
            <NodeAssignment nodes={nodes} draft={draft} groups={draft.groups || []} onUpdateNode={updateNode} />
          </div>

          <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-teal-950">Groups</h3>
              <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50" onClick={addGroup} type="button">Add group</button>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {(draft.groups || []).map((group) => (
                <GroupEditor
                  group={group}
                  interactionsById={interactionsById}
                  eventById={eventsById}
                  key={group.id}
                  onRemove={removeGroup}
                  onSetTileCount={setGroupTileCount}
                  onUpdateGroup={updateGroup}
                  stats={groupStats[group.id] || { capacity: 0, assigned: 0, valid: false }}
                  tiles={content.tiles || []}
                />
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-cyan-100 bg-white p-3">
            <p className={`text-sm ${canSave ? "text-teal-700" : "text-rose-700"}`}>
              {canSave ? "Level is valid." : "Every node needs a group, and each group needs exactly as many tile copies as its node spaces."}
            </p>
            <button className="rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-60" disabled={busy || !canSave} onClick={saveLevel} type="button">
              {draft.id ? "Update level" : "Create level"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
};

const LevelMap = ({ map, groupsById, nodeGroupIds }) => {
  const boardImageUrl = map?.image_url ? buildApiUrl(map.image_url) : "";
  return (
    <div className="relative mx-auto overflow-hidden rounded-lg border border-cyan-200 bg-cyan-50" style={{ aspectRatio: map?.image_width && map?.image_height ? `${map.image_width} / ${map.image_height}` : "16 / 9", maxWidth: map?.image_width || undefined }}>
      {boardImageUrl ? <img alt="Level map" className="absolute inset-0 h-full w-full object-contain" src={boardImageUrl} /> : <div className="flex h-full min-h-[20rem] items-center justify-center text-sm text-slate-500">{map ? "Map has no image." : "Select a map."}</div>}
      {Object.values(map?.nodes || {}).map((node) => {
        const group = groupsById[nodeGroupIds[node.id]];
        return (
          <span
            className="absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white text-xs font-semibold text-white shadow"
            key={node.id}
            style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%`, backgroundColor: group?.color || "#94a3b8" }}
            title={group?.name || "No group"}
          >
            {node.id}
          </span>
        );
      })}
    </div>
  );
};

const NodeAssignment = ({ nodes, draft, groups, onUpdateNode }) => (
  <div className="rounded-md border border-cyan-100 bg-white p-3">
    <h3 className="text-sm font-semibold text-teal-950">Node spaces</h3>
    <div className="mt-2 max-h-[28rem] space-y-2 overflow-auto pr-1">
      {nodes.map((node) => (
        <div className="grid grid-cols-[3.5rem_4rem_1fr] items-center gap-2 rounded-md bg-cyan-50 p-2 text-sm" key={node.id}>
          <span className="font-semibold text-teal-950">{node.id}</span>
          <input className="rounded border border-cyan-200 bg-white px-2 py-1 text-sm" min="0" type="number" value={draft.node_tile_counts[node.id] ?? 3} onChange={(event) => onUpdateNode(node.id, { tile_count: Number(event.target.value) })} />
          <select className="min-w-0 rounded border border-cyan-200 bg-white px-2 py-1 text-sm" value={draft.node_group_ids[node.id] || ""} onChange={(event) => onUpdateNode(node.id, { group_id: event.target.value })}>
            <option value="">No group</option>
            {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </div>
      ))}
    </div>
  </div>
);

const GroupEditor = ({ group, stats, tiles, eventById, interactionsById, onUpdateGroup, onRemove, onSetTileCount }) => (
  <article className={`rounded-md border bg-white p-3 ${stats.valid ? "border-cyan-200" : "border-rose-200"}`}>
    <div className="flex items-center gap-2">
      <input className="min-w-0 flex-1 rounded border border-cyan-200 bg-white px-3 py-2 text-sm font-semibold text-teal-950" value={group.name} onChange={(event) => onUpdateGroup(group.id, { name: event.target.value })} />
      <span className={`rounded-full px-2 py-1 text-xs font-semibold ${stats.valid ? "bg-teal-100 text-teal-800" : "bg-rose-100 text-rose-700"}`}>{stats.assigned}/{stats.capacity}</span>
      <button className="rounded border border-rose-300 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" onClick={() => onRemove(group.id)} type="button">Remove</button>
    </div>

    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      {tiles.map((tile) => {
        const count = Number((group.tile_counts || {})[tile.id] || 0);
        return (
          <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={tile.id}>
            <HexTilePreview className="max-w-[8rem]" event={eventById[tile.event_id]} interactionsById={interactionsById} tile={tile} />
            <div className="mt-2 flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-teal-950">{tile.name}</span>
              <input className="w-16 rounded border border-cyan-200 bg-white px-2 py-1 text-sm" min="0" type="number" value={count} onChange={(event) => onSetTileCount(group.id, tile.id, Number(event.target.value))} />
            </div>
          </div>
        );
      })}
      {tiles.length === 0 ? <p className="text-sm text-slate-500">Create tiles first.</p> : null}
    </div>
  </article>
);

export default AdminLevelEditor;
