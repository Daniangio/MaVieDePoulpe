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
  objectives: [],
  starting_energy: 3,
  starting_neurons: 0,
  night_duration_steps: 24,
  surprise_deck_id: "",
  poulpita_starting_node_id: "",
  node_tokens: {},
});

const groupColors = ["#0d9488", "#2563eb", "#c026d3", "#ea580c", "#16a34a", "#be123c", "#7c3aed", "#0891b2"];

const AdminLevelEditor = ({ request, content, busy, setBusy, setError, onReload }) => {
  const [maps, setMaps] = useState([]);
  const [draft, setDraft] = useState(emptyLevelDraft());
  const [selectedNodeId, setSelectedNodeId] = useState("");

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
      poulpita_starting_node_id: base.poulpita_starting_node_id || map?.starting_node_id || mapNodes[0] || "",
      node_tokens: Object.fromEntries(Object.entries(base.node_tokens || {}).filter(([nodeId]) => mapNodes.includes(nodeId))),
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
    setSelectedNodeId("");
    setDraft(levelFromMap(firstMap, emptyLevelDraft()));
  };

  const editLevel = (level) => {
    const map = maps.find((entry) => entry.id === level.map_id) || null;
    setSelectedNodeId("");
    setDraft(levelFromMap(map, { ...emptyLevelDraft(), ...level, groups: level.groups || [] }));
  };

  const changeMap = (mapId) => {
    const map = maps.find((entry) => entry.id === mapId) || null;
    setSelectedNodeId("");
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
    setSelectedNodeId("");
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
      form.set("objectives_json", JSON.stringify(draft.objectives || []));
      form.set("starting_energy", String(Math.max(0, Math.min(32, Number(draft.starting_energy ?? 3)))));
      form.set("starting_neurons", String(Math.max(0, Number(draft.starting_neurons ?? 0))));
      form.set("night_duration_steps", String(Math.max(1, Number(draft.night_duration_steps ?? 24))));
      form.set("surprise_deck_id", draft.surprise_deck_id || "");
      form.set("poulpita_starting_node_id", draft.poulpita_starting_node_id || "");
      form.set("node_tokens_json", JSON.stringify(draft.node_tokens || {}));
      const saved = await request(draft.id ? `/api/admin/content/levels/${draft.id}` : "/api/admin/content/levels", { method: draft.id ? "PUT" : "POST", body: form });
      setDraft(saved);
      await onReload();
    } catch (saveError) {
      setError(saveError.message || "Failed to save level.");
    } finally {
      setBusy(false);
    }
  };

  const addObjective = (type) => {
    setDraft((current) => ({
      ...current,
      objectives: [
        ...(current.objectives || []),
        {
          id: `objective-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          type,
          target: type === "increase_size" ? 1 : undefined,
        },
      ],
    }));
  };

  const updateObjective = (objectiveId, patch) => {
    setDraft((current) => ({
      ...current,
      objectives: (current.objectives || []).map((objective) => (objective.id === objectiveId ? { ...objective, ...patch } : objective)),
    }));
  };

  const removeObjective = (objectiveId) => {
    setDraft((current) => ({
      ...current,
      objectives: (current.objectives || []).filter((objective) => objective.id !== objectiveId),
    }));
  };

  const toggleNodeToken = (nodeId, tokenType) => {
    setDraft((current) => {
      const currentTokens = current.node_tokens?.[nodeId] || [];
      const hasToken = currentTokens.some((token) => (typeof token === "string" ? token : token.type) === tokenType);
      const nextTokens = hasToken
        ? currentTokens.filter((token) => (typeof token === "string" ? token : token.type) !== tokenType)
        : [...currentTokens, { type: tokenType }];
      const nodeTokens = { ...(current.node_tokens || {}) };
      if (nextTokens.length) nodeTokens[nodeId] = nextTokens;
      else delete nodeTokens[nodeId];
      return { ...current, node_tokens: nodeTokens };
    });
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
          <div className="grid gap-3 lg:grid-cols-[1fr_13rem_7rem_7rem_8rem_13rem]">
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
            <label className="block text-sm">
              <span className="text-slate-600">Starting energy</span>
              <input
                className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800"
                max="32"
                min="0"
                type="number"
                value={Number(draft.starting_energy ?? 3)}
                onChange={(event) => setDraft((current) => ({ ...current, starting_energy: Math.max(0, Math.min(32, Number(event.target.value || 0))) }))}
              />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Starting neurons</span>
              <input
                className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800"
                min="0"
                type="number"
                value={Number(draft.starting_neurons ?? 0)}
                onChange={(event) => setDraft((current) => ({ ...current, starting_neurons: Math.max(0, Number(event.target.value || 0)) }))}
              />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Night steps</span>
              <input
                className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800"
                min="1"
                type="number"
                value={Number(draft.night_duration_steps ?? 24)}
                onChange={(event) => setDraft((current) => ({ ...current, night_duration_steps: Math.max(1, Number(event.target.value || 1)) }))}
              />
            </label>
            <label className="block text-sm">
              <span className="text-slate-600">Surprise deck</span>
              <select className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800" value={draft.surprise_deck_id || ""} onChange={(event) => setDraft((current) => ({ ...current, surprise_deck_id: event.target.value }))}>
                <option value="">None</option>
                {(content.surprise_decks || []).map((deck) => <option key={deck.id} value={deck.id}>{deck.name}</option>)}
              </select>
            </label>
          </div>

          <div>
            <LevelMap
              groups={draft.groups || []}
              groupsById={groupsById}
              map={selectedMap}
              nodeGroupIds={draft.node_group_ids}
              nodeTileCounts={draft.node_tile_counts}
              onSelectGroup={(nodeId, groupId) => updateNode(nodeId, { group_id: groupId })}
              onSetNodeTileCount={(nodeId, tileCount) => updateNode(nodeId, { tile_count: tileCount })}
              onSetStartingNode={(nodeId) => setDraft((current) => ({ ...current, poulpita_starting_node_id: nodeId }))}
              onToggleNodeToken={toggleNodeToken}
              nodeTokens={draft.node_tokens || {}}
              startingNodeId={draft.poulpita_starting_node_id}
              selectedNodeId={selectedNodeId}
              setSelectedNodeId={setSelectedNodeId}
            />
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

          <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-teal-950">Objectives</h3>
                <p className="text-xs text-slate-600">All objectives listed here must be completed to win the level.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs text-teal-900 hover:bg-cyan-50" onClick={() => addObjective("increase_size")} type="button">Increase size</button>
                <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs text-teal-900 hover:bg-cyan-50" onClick={() => addObjective("find_shelter")} type="button">Find shelter</button>
                <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-xs text-teal-900 hover:bg-cyan-50" onClick={() => addObjective("secure_shelter")} type="button">Secure shelter</button>
              </div>
            </div>
            <div className="grid gap-2">
              {(draft.objectives || []).map((objective) => (
                <div className="grid gap-2 rounded-md border border-cyan-100 bg-white p-2 text-sm md:grid-cols-[1fr_9rem_auto]" key={objective.id}>
                  <select
                    className="rounded border border-cyan-200 bg-white px-2 py-1 text-slate-800"
                    onChange={(event) => updateObjective(objective.id, { type: event.target.value, target: event.target.value === "increase_size" ? Number(objective.target || 1) : undefined })}
                    value={objective.type}
                  >
                    <option value="increase_size">Increase size</option>
                    <option value="find_shelter">Find a shelter</option>
                    <option value="secure_shelter">Secure a shelter</option>
                  </select>
                  {objective.type === "increase_size" ? (
                    <label className="flex items-center gap-2 text-xs text-slate-600">
                      Times
                      <input className="w-full rounded border border-cyan-200 bg-white px-2 py-1 text-sm text-slate-800" min="1" type="number" value={Number(objective.target || 1)} onChange={(event) => updateObjective(objective.id, { target: Number(event.target.value) })} />
                    </label>
                  ) : (
                    <span className="text-xs text-slate-500">No value</span>
                  )}
                  <button className="rounded border border-rose-300 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" onClick={() => removeObjective(objective.id)} type="button">Remove</button>
                </div>
              ))}
              {(draft.objectives || []).length === 0 ? <p className="rounded border border-dashed border-cyan-200 bg-white p-3 text-sm text-slate-500">No objectives: this level will not auto-win.</p> : null}
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

const LevelMap = ({ map, groups, groupsById, nodeGroupIds, nodeTileCounts, nodeTokens, startingNodeId, selectedNodeId, setSelectedNodeId, onSelectGroup, onSetNodeTileCount, onSetStartingNode, onToggleNodeToken }) => {
  const boardImageUrl = map?.image_url ? buildApiUrl(map.image_url) : "";
  const selectedNode = selectedNodeId ? map?.nodes?.[selectedNodeId] : null;
  const opensUp = Number(selectedNode?.y || 0) > 0.62;
  return (
    <div className="relative mx-auto overflow-visible" style={{ aspectRatio: map?.image_width && map?.image_height ? `${map.image_width} / ${map.image_height}` : "16 / 9", maxWidth: map?.image_width || undefined }}>
      <div className="absolute inset-0 overflow-hidden rounded-lg border border-cyan-200 bg-cyan-50">
        {boardImageUrl ? <img alt="Level map" className="absolute inset-0 h-full w-full object-contain" src={boardImageUrl} /> : <div className="flex h-full min-h-[20rem] items-center justify-center text-sm text-slate-500">{map ? "Map has no image." : "Select a map."}</div>}
        {Object.values(map?.nodes || {}).map((node) => {
          const group = groupsById[nodeGroupIds[node.id]];
          const tokens = nodeTokens?.[node.id] || [];
          const tokenTypes = tokens.map((token) => (typeof token === "string" ? token : token.type));
          return (
            <div
              className="absolute -translate-x-1/2 -translate-y-1/2"
              key={node.id}
              style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%` }}
            >
              <button
                className={`flex min-h-11 min-w-11 flex-col items-center justify-center rounded-full border-2 px-2 text-center text-[0.62rem] font-semibold leading-tight text-white shadow ${selectedNodeId === node.id ? "border-teal-950 ring-2 ring-white" : "border-white"}`}
                onClick={() => setSelectedNodeId(selectedNodeId === node.id ? "" : node.id)}
                style={{ backgroundColor: group?.color || "#94a3b8" }}
                title={group?.name || "No group"}
                type="button"
              >
                <span>{startingNodeId === node.id ? "P - " : ""}{node.id}</span>
                <span className="max-w-[4.5rem] truncate">{group?.name || "No group"}</span>
              </button>
              {tokenTypes.length ? (
                <div className="pointer-events-none absolute left-1/2 top-full mt-0.5 flex -translate-x-1/2 gap-1">
                  {tokenTypes.map((type) => (
                    <span className="rounded-full border border-white bg-teal-950/90 px-1.5 py-0.5 text-[0.55rem] font-bold uppercase text-cyan-50 shadow" key={type}>{type === "shelter" ? "Shelter" : "Octopus"}</span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {selectedNode ? (
        <div
          className="absolute z-20 w-52 -translate-x-1/2 rounded-md border border-cyan-200 bg-white p-2 text-sm shadow-lg"
          style={{ left: `${selectedNode.x * 100}%`, top: opensUp ? `calc(${selectedNode.y * 100}% - 0.9rem)` : `calc(${selectedNode.y * 100}% + 1.9rem)`, transform: opensUp ? "translate(-50%, -100%)" : "translateX(-50%)" }}
        >
          <p className="mb-2 text-xs font-semibold text-teal-950">Node {selectedNode.id}</p>
          <label className="mb-2 block text-xs text-slate-600">
            Tile spaces
            <input className="mt-1 w-full rounded border border-cyan-200 bg-white px-2 py-1 text-sm text-slate-800" min="0" type="number" value={nodeTileCounts[selectedNode.id] ?? 3} onChange={(event) => onSetNodeTileCount(selectedNode.id, Number(event.target.value))} />
          </label>
          <button
            className={`mb-2 w-full rounded border px-2 py-1 text-xs ${startingNodeId === selectedNode.id ? "border-teal-400 bg-teal-100 text-teal-900" : "border-cyan-200 bg-white text-slate-700 hover:bg-cyan-50"}`}
            onClick={() => onSetStartingNode(selectedNode.id)}
            type="button"
          >
            {startingNodeId === selectedNode.id ? "Poulpita starts here" : "Set Poulpita start"}
          </button>
          <div className="mb-2 grid grid-cols-2 gap-1">
            {["shelter", "octopus"].map((tokenType) => {
              const checked = (nodeTokens?.[selectedNode.id] || []).some((token) => (typeof token === "string" ? token : token.type) === tokenType);
              return (
                <button
                  className={`rounded border px-2 py-1 text-xs ${checked ? "border-teal-400 bg-teal-100 text-teal-900" : "border-cyan-200 bg-white text-slate-700 hover:bg-cyan-50"}`}
                  key={tokenType}
                  onClick={() => onToggleNodeToken(selectedNode.id, tokenType)}
                  type="button"
                >
                  {checked ? "Remove" : "Add"} {tokenType === "shelter" ? "Shelter" : "Octopus"}
                </button>
              );
            })}
          </div>
          <div className="space-y-1">
            {groups.map((group) => {
              const decoratedGroup = groupsById[group.id];
              return (
                <button
                  className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs ${nodeGroupIds[selectedNode.id] === group.id ? "bg-cyan-100 text-teal-950" : "text-slate-700 hover:bg-cyan-50"}`}
                  key={group.id}
                  onClick={() => {
                    onSelectGroup(selectedNode.id, group.id);
                    setSelectedNodeId("");
                  }}
                  type="button"
                >
                  <span className="h-3 w-3 rounded-full" style={{ backgroundColor: decoratedGroup?.color || "#94a3b8" }} />
                  <span className="min-w-0 flex-1 truncate">{group.name}</span>
                </button>
              );
            })}
            {groups.length === 0 ? <p className="text-xs text-slate-500">Create a group first.</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};

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
