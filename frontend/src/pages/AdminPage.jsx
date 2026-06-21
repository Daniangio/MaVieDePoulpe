import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const emptyMapDraft = () => ({
  id: "",
  name: "Untitled map",
  nodes: {},
  adjacency: {},
  starting_node_id: "",
  image_url: "",
  image_width: null,
  image_height: null,
});

const AdminPage = () => {
  const { token, user } = useStore();
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [maps, setMaps] = useState([]);
  const [draftMap, setDraftMap] = useState(emptyMapDraft());
  const [imageFile, setImageFile] = useState(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");
  const [editorMode, setEditorMode] = useState("nodes");
  const [edgeStartNodeId, setEdgeStartNodeId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const imageInputRef = useRef(null);

  const selectedNode = selectedNodeId ? draftMap.nodes[selectedNodeId] : null;
  const editableMaps = useMemo(() => maps.filter((entry) => entry.id !== "default-16"), [maps]);
  const boardImageUrl = imagePreviewUrl || (draftMap.image_url ? buildApiUrl(draftMap.image_url) : "");

  const request = async (path, options = {}) => {
    const response = await fetch(buildApiUrl(path), {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Admin request failed.");
    return payload;
  };

  const loadUsers = async () => {
    if (!token) return;
    setError("");
    try {
      setUsers(await request(`/api/admin/users?query=${encodeURIComponent(query)}`));
    } catch (loadError) {
      setError(loadError.message || "Failed to load users.");
    }
  };

  const loadAudit = async () => {
    if (!token) return;
    try {
      setAuditLogs(await request("/api/admin/audit-logs"));
    } catch (_error) {
      setAuditLogs([]);
    }
  };

  const loadMaps = async () => {
    if (!token) return;
    try {
      const payload = await request("/api/admin/maps");
      setMaps(payload.maps || []);
    } catch (loadError) {
      setError(loadError.message || "Failed to load maps.");
    }
  };

  const loadUserDetail = async (userId) => {
    setError("");
    try {
      setSelectedUser(await request(`/api/admin/users/${userId}`));
    } catch (loadError) {
      setError(loadError.message || "Failed to load user.");
    }
  };

  useEffect(() => {
    void loadUsers();
    void loadAudit();
    void loadMaps();
  }, [token]);

  const toggleAdmin = async (target) => {
    if (!target?.id) return;
    setBusy(true);
    setError("");
    try {
      const updated = await request(`/api/admin/users/${target.id}/admin`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_admin: !target.is_admin }),
      });
      setSelectedUser(updated);
      await loadUsers();
      await loadAudit();
    } catch (actionError) {
      setError(actionError.message || "Failed to update admin flag.");
    } finally {
      setBusy(false);
    }
  };

  const resetMapEditor = () => {
    setDraftMap(emptyMapDraft());
    setImageFile(null);
    setImagePreviewUrl("");
    setSelectedNodeId("");
    setEdgeStartNodeId("");
    if (imageInputRef.current) imageInputRef.current.value = "";
  };

  const editMap = (map) => {
    setDraftMap({
      ...map,
      nodes: map.nodes || {},
      adjacency: map.adjacency || {},
    });
    setImageFile(null);
    setImagePreviewUrl("");
    setSelectedNodeId("");
    setEdgeStartNodeId("");
    if (imageInputRef.current) imageInputRef.current.value = "";
  };

  const setImage = (file) => {
    setImageFile(file || null);
    if (!file) {
      setImagePreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setImagePreviewUrl(url);
    const image = new Image();
    image.onload = () => {
      setDraftMap((current) => ({ ...current, image_width: image.naturalWidth, image_height: image.naturalHeight }));
    };
    image.src = url;
  };

  const nextNodeId = () => {
    let index = Object.keys(draftMap.nodes || {}).length + 1;
    while (draftMap.nodes[`N${index}`]) index += 1;
    return `N${index}`;
  };

  const addNodeAt = (event) => {
    if (editorMode !== "nodes") return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    const id = nextNodeId();
    setDraftMap((current) => ({
      ...current,
      starting_node_id: current.starting_node_id || id,
      nodes: {
        ...current.nodes,
        [id]: { id, tier: 1, x, y },
      },
      adjacency: {
        ...current.adjacency,
        [id]: [],
      },
    }));
    setSelectedNodeId(id);
  };

  const updateSelectedNode = (patch) => {
    if (!selectedNodeId) return;
    setDraftMap((current) => ({
      ...current,
      nodes: {
        ...current.nodes,
        [selectedNodeId]: {
          ...current.nodes[selectedNodeId],
          ...patch,
        },
      },
    }));
  };

  const deleteSelectedNode = () => {
    if (!selectedNodeId) return;
    setDraftMap((current) => {
      const nodes = { ...current.nodes };
      delete nodes[selectedNodeId];
      const adjacency = {};
      Object.entries(current.adjacency || {}).forEach(([nodeId, adjacent]) => {
        if (nodeId !== selectedNodeId) adjacency[nodeId] = (adjacent || []).filter((entry) => entry !== selectedNodeId);
      });
      return {
        ...current,
        nodes,
        adjacency,
        starting_node_id: current.starting_node_id === selectedNodeId ? Object.keys(nodes)[0] || "" : current.starting_node_id,
      };
    });
    setSelectedNodeId("");
    setEdgeStartNodeId("");
  };

  const toggleEdge = (fromId, toId) => {
    if (!fromId || !toId || fromId === toId) return;
    setDraftMap((current) => {
      const fromAdjacent = new Set(current.adjacency[fromId] || []);
      const toAdjacent = new Set(current.adjacency[toId] || []);
      if (fromAdjacent.has(toId)) {
        fromAdjacent.delete(toId);
        toAdjacent.delete(fromId);
      } else {
        fromAdjacent.add(toId);
        toAdjacent.add(fromId);
      }
      return {
        ...current,
        adjacency: {
          ...current.adjacency,
          [fromId]: Array.from(fromAdjacent).sort(),
          [toId]: Array.from(toAdjacent).sort(),
        },
      };
    });
  };

  const handleNodeClick = (event, nodeId) => {
    event.stopPropagation();
    setSelectedNodeId(nodeId);
    if (editorMode !== "edges") return;
    if (!edgeStartNodeId) {
      setEdgeStartNodeId(nodeId);
      return;
    }
    toggleEdge(edgeStartNodeId, nodeId);
    setEdgeStartNodeId("");
  };

  const saveMap = async () => {
    setBusy(true);
    setError("");
    try {
      if (!draftMap.id && !imageFile) throw new Error("Upload a board image before creating a new map.");
      const form = new FormData();
      form.set("name", draftMap.name || "Untitled map");
      form.set("nodes_json", JSON.stringify(draftMap.nodes || {}));
      form.set("adjacency_json", JSON.stringify(draftMap.adjacency || {}));
      form.set("starting_node_id", draftMap.starting_node_id || Object.keys(draftMap.nodes || {})[0] || "");
      if (draftMap.image_width) form.set("image_width", String(draftMap.image_width));
      if (draftMap.image_height) form.set("image_height", String(draftMap.image_height));
      if (imageFile) form.set("image", imageFile);
      const path = draftMap.id ? `/api/admin/maps/${draftMap.id}` : "/api/admin/maps";
      const saved = await request(path, { method: draftMap.id ? "PUT" : "POST", body: form });
      setDraftMap(saved);
      setImageFile(null);
      setImagePreviewUrl("");
      await loadMaps();
    } catch (saveError) {
      setError(saveError.message || "Failed to save map.");
    } finally {
      setBusy(false);
    }
  };

  const removeMap = async (mapId) => {
    if (!mapId || !window.confirm("Delete this map?")) return;
    setBusy(true);
    setError("");
    try {
      await request(`/api/admin/maps/${mapId}`, { method: "DELETE" });
      if (draftMap.id === mapId) resetMapEditor();
      await loadMaps();
    } catch (deleteError) {
      setError(deleteError.message || "Failed to delete map.");
    } finally {
      setBusy(false);
    }
  };

  if (!user?.is_admin) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900 p-6">
        <h1 className="text-2xl font-semibold text-white">Admin</h1>
        <p className="mt-2 text-slate-400">Admin access is required.</p>
        <Link className="mt-5 inline-block rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950" to="/lobby">
          Back to lobby
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Admin Backoffice</h1>
          <p className="mt-1 text-sm text-slate-400">Manage users, maps, and administrative changes.</p>
        </div>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-teal-400"
            placeholder="Search users"
          />
          <button className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950" onClick={loadUsers}>
            Search
          </button>
        </div>
      </div>

      {error ? <p className="mb-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}

      <section className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="mb-3 font-semibold text-white">Users</h2>
          <div className="divide-y divide-slate-800">
            {users.map((entry) => (
              <button key={entry.id} className="flex w-full items-center justify-between gap-3 py-3 text-left hover:bg-slate-950" onClick={() => loadUserDetail(entry.id)}>
                <span>
                  <span className="font-medium text-white">{entry.username}</span>
                  <span className="ml-2 text-xs text-slate-500">{entry.email}</span>
                </span>
                <span className="flex gap-2">
                  {entry.is_admin ? <span className="rounded-full bg-indigo-500/15 px-2 py-1 text-xs text-indigo-200">admin</span> : null}
                  <span className={`rounded-full px-2 py-1 text-xs ${entry.online ? "bg-emerald-500/15 text-emerald-200" : "bg-slate-800 text-slate-400"}`}>
                    {entry.online ? "online" : "offline"}
                  </span>
                </span>
              </button>
            ))}
            {users.length === 0 ? <p className="py-5 text-slate-400">No users found.</p> : null}
          </div>
        </div>

        <aside className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <h2 className="font-semibold text-white">Selected User</h2>
          {selectedUser ? (
            <div className="mt-4 space-y-3">
              <p className="font-medium text-white">{selectedUser.user.username}</p>
              <p className="break-all text-xs text-slate-500">{selectedUser.user.id}</p>
              <p className="text-sm text-slate-400">Friends: {selectedUser.friends_count}</p>
              <p className="text-sm text-slate-400">Incoming requests: {selectedUser.incoming_requests_count}</p>
              <p className="text-sm text-slate-400">Outgoing requests: {selectedUser.outgoing_requests_count}</p>
              <button className="w-full rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60" onClick={() => toggleAdmin(selectedUser.user)} disabled={busy}>
                {selectedUser.user.is_admin ? "Remove admin" : "Make admin"}
              </button>
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-400">Select a user to inspect.</p>
          )}
        </aside>
      </section>

      <section className="mt-4 rounded-lg border border-slate-800 bg-slate-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">Maps</h2>
            <p className="mt-1 text-sm text-slate-400">Upload a board image, place nodes, and connect edges.</p>
          </div>
          <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800" onClick={resetMapEditor} type="button">
            New map
          </button>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[18rem_1fr_18rem]">
          <div className="space-y-2">
            {editableMaps.map((map) => (
              <div className="flex items-center justify-between gap-2 rounded-md border border-slate-800 bg-slate-950 p-2" key={map.id}>
                <button className="min-w-0 flex-1 text-left text-sm text-slate-200 hover:text-white" onClick={() => editMap(map)} type="button">
                  <span className="block truncate font-medium">{map.name}</span>
                  <span className="text-xs text-slate-500">{Object.keys(map.nodes || {}).length} nodes</span>
                </button>
                <button className="rounded border border-rose-500/50 px-2 py-1 text-xs text-rose-100 hover:bg-rose-950" onClick={() => removeMap(map.id)} type="button">
                  Delete
                </button>
              </div>
            ))}
            {editableMaps.length === 0 ? <p className="rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-400">No custom maps yet.</p> : null}
          </div>

          <div>
            <div className="mb-3 flex flex-wrap gap-2">
              <button className={`rounded-md px-3 py-2 text-sm ${editorMode === "nodes" ? "bg-teal-400 text-slate-950" : "border border-slate-700 text-slate-200"}`} onClick={() => setEditorMode("nodes")} type="button">
                Node mode
              </button>
              <button className={`rounded-md px-3 py-2 text-sm ${editorMode === "edges" ? "bg-teal-400 text-slate-950" : "border border-slate-700 text-slate-200"}`} onClick={() => setEditorMode("edges")} type="button">
                Edge mode
              </button>
              {edgeStartNodeId ? <span className="rounded-md bg-slate-950 px-3 py-2 text-sm text-teal-200">Edge from {edgeStartNodeId}</span> : null}
            </div>

            <div className="relative mx-auto overflow-hidden rounded-lg border border-slate-800 bg-slate-950" onClick={addNodeAt} style={{ aspectRatio: draftMap.image_width && draftMap.image_height ? `${draftMap.image_width} / ${draftMap.image_height}` : "16 / 9", maxWidth: draftMap.image_width || undefined }}>
              {boardImageUrl ? (
                <img
                  alt="Board map"
                  className="absolute inset-0 h-full w-full object-contain"
                  onLoad={(event) => {
                    const { naturalWidth, naturalHeight } = event.currentTarget;
                    if (!draftMap.image_width || !draftMap.image_height) {
                      setDraftMap((current) => ({ ...current, image_width: naturalWidth, image_height: naturalHeight }));
                    }
                  }}
                  src={boardImageUrl}
                />
              ) : (
                <div className="flex h-full min-h-[22rem] items-center justify-center text-sm text-slate-500">Upload an image to start placing nodes.</div>
              )}
              <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
                {Object.entries(draftMap.adjacency || {}).flatMap(([fromId, adjacent]) =>
                  (adjacent || [])
                    .filter((toId) => fromId < toId)
                    .map((toId) => {
                      const from = draftMap.nodes[fromId];
                      const to = draftMap.nodes[toId];
                      if (!from || !to) return null;
                      return <line key={`${fromId}:${toId}`} stroke="rgba(45,212,191,0.75)" strokeWidth="0.006" x1={from.x} x2={to.x} y1={from.y} y2={to.y} />;
                    })
                )}
              </svg>
              {Object.values(draftMap.nodes || {}).map((node) => (
                <button
                  className={`absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border text-xs font-semibold ${selectedNodeId === node.id ? "border-white bg-teal-300 text-slate-950" : edgeStartNodeId === node.id ? "border-teal-200 bg-teal-950 text-teal-100" : "border-slate-200 bg-slate-950/85 text-white"}`}
                  key={node.id}
                  onClick={(event) => handleNodeClick(event, node.id)}
                  style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%` }}
                  type="button"
                >
                  {node.id}
                </button>
              ))}
            </div>
          </div>

          <aside className="space-y-3">
            <label className="block text-sm">
              <span className="text-slate-300">Name</span>
              <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={draftMap.name} onChange={(event) => setDraftMap((current) => ({ ...current, name: event.target.value }))} />
            </label>
            <label className="block text-sm">
              <span className="text-slate-300">Board image</span>
              <input ref={imageInputRef} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] || null)} />
            </label>
            <label className="block text-sm">
              <span className="text-slate-300">Starting node</span>
              <select className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={draftMap.starting_node_id || ""} onChange={(event) => setDraftMap((current) => ({ ...current, starting_node_id: event.target.value }))}>
                {Object.keys(draftMap.nodes || {}).map((nodeId) => (
                  <option value={nodeId} key={nodeId}>{nodeId}</option>
                ))}
              </select>
            </label>
            {selectedNode ? (
              <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
                <p className="font-semibold text-white">Node {selectedNode.id}</p>
                <label className="mt-3 block text-sm">
                  <span className="text-slate-300">Tier</span>
                  <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white" type="number" min="1" value={selectedNode.tier || 1} onChange={(event) => updateSelectedNode({ tier: Number(event.target.value) })} />
                </label>
                <p className="mt-3 text-xs text-slate-500">x {selectedNode.x.toFixed(3)} · y {selectedNode.y.toFixed(3)}</p>
                <button className="mt-3 w-full rounded-md border border-rose-500/60 px-3 py-2 text-sm text-rose-100 hover:bg-rose-950" onClick={deleteSelectedNode} type="button">
                  Delete node
                </button>
              </div>
            ) : null}
            <button className="w-full rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-60" disabled={busy} onClick={saveMap} type="button">
              {busy ? "Saving..." : "Save map"}
            </button>
          </aside>
        </div>
      </section>

      <section className="mt-4 rounded-lg border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-3 font-semibold text-white">Audit Logs</h2>
        <div className="divide-y divide-slate-800">
          {auditLogs.map((entry) => (
            <div key={entry.id} className="py-3 text-sm">
              <p className="text-white">{entry.action} <span className="text-slate-500">on</span> {entry.target_type}:{entry.target_id}</p>
              <p className="mt-1 text-xs text-slate-500">{entry.admin_username} · {new Date(entry.created_at).toLocaleString()}</p>
            </div>
          ))}
          {auditLogs.length === 0 ? <p className="py-5 text-slate-400">No audit logs yet.</p> : null}
        </div>
      </section>
    </>
  );
};

export default AdminPage;
