import { useEffect, useMemo, useRef, useState } from "react";
import { buildApiUrl } from "../utils/connection.js";

const emptyMapDraft = () => ({
  id: "",
  name: "Untitled map",
  nodes: {},
  adjacency: {},
  image_url: "",
  image_width: null,
  image_height: null,
});

const AdminMapEditor = ({ request, busy, setBusy, setError }) => {
  const [maps, setMaps] = useState([]);
  const [draftMap, setDraftMap] = useState(emptyMapDraft());
  const [imageFile, setImageFile] = useState(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");
  const [editorMode, setEditorMode] = useState("nodes");
  const [edgeStartNodeId, setEdgeStartNodeId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const imageInputRef = useRef(null);

  const selectedNode = selectedNodeId ? draftMap.nodes[selectedNodeId] : null;
  const editableMaps = useMemo(() => maps, [maps]);
  const boardImageUrl = imagePreviewUrl || (draftMap.image_url ? buildApiUrl(draftMap.image_url) : "");

  const loadMaps = async () => {
    try {
      const payload = await request("/api/admin/maps");
      setMaps(payload.maps || []);
    } catch (loadError) {
      setError(loadError.message || "Failed to load maps.");
    }
  };

  useEffect(() => {
    void loadMaps();
  }, []);

  const resetMapEditor = () => {
    setDraftMap(emptyMapDraft());
    setImageFile(null);
    setImagePreviewUrl("");
    setSelectedNodeId("");
    setEdgeStartNodeId("");
    if (imageInputRef.current) imageInputRef.current.value = "";
  };

  const editMap = (map) => {
    setDraftMap({ ...map, nodes: map.nodes || {}, adjacency: map.adjacency || {} });
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
      nodes: { ...current.nodes, [id]: { id, tier: 1, x, y } },
      adjacency: { ...current.adjacency, [id]: [] },
    }));
    setSelectedNodeId(id);
  };

  const updateSelectedNode = (patch) => {
    if (!selectedNodeId) return;
    setDraftMap((current) => ({
      ...current,
      nodes: { ...current.nodes, [selectedNodeId]: { ...current.nodes[selectedNodeId], ...patch } },
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
        adjacency: { ...current.adjacency, [fromId]: Array.from(fromAdjacent).sort(), [toId]: Array.from(toAdjacent).sort() },
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

  return (
    <section className="rounded-lg border border-cyan-200 bg-white/90 p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-teal-950">Maps</h2>
          <p className="mt-1 text-sm text-slate-600">Upload a board image, place nodes, and connect edges.</p>
        </div>
        <button className="rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50" onClick={resetMapEditor} type="button">
          New map
        </button>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[18rem_1fr_18rem]">
        <div className="space-y-2">
          {editableMaps.map((map) => (
            <div className="flex items-center justify-between gap-2 rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={map.id}>
              <button className="min-w-0 flex-1 text-left text-sm text-slate-700 hover:text-teal-800" onClick={() => editMap(map)} type="button">
                <span className="block truncate font-medium">{map.name}</span>
                <span className="text-xs text-slate-500">{Object.keys(map.nodes || {}).length} nodes</span>
              </button>
              <button className="rounded border border-rose-300 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50" onClick={() => removeMap(map.id)} type="button">
                Delete
              </button>
            </div>
          ))}
          {editableMaps.length === 0 ? <p className="rounded-md border border-cyan-100 bg-cyan-50 p-3 text-sm text-slate-500">No custom maps yet.</p> : null}
        </div>

        <div>
          <div className="mb-3 flex flex-wrap gap-2">
            <button className={`rounded-md px-3 py-2 text-sm ${editorMode === "nodes" ? "bg-teal-500 text-white" : "border border-cyan-300 bg-white text-teal-900"}`} onClick={() => setEditorMode("nodes")} type="button">Node mode</button>
            <button className={`rounded-md px-3 py-2 text-sm ${editorMode === "edges" ? "bg-teal-500 text-white" : "border border-cyan-300 bg-white text-teal-900"}`} onClick={() => setEditorMode("edges")} type="button">Edge mode</button>
            {edgeStartNodeId ? <span className="rounded-md bg-cyan-50 px-3 py-2 text-sm text-teal-800">Edge from {edgeStartNodeId}</span> : null}
          </div>

          <div className="relative mx-auto overflow-hidden rounded-lg border border-cyan-200 bg-cyan-50" onClick={addNodeAt} style={{ aspectRatio: draftMap.image_width && draftMap.image_height ? `${draftMap.image_width} / ${draftMap.image_height}` : "16 / 9", maxWidth: draftMap.image_width || undefined }}>
            {boardImageUrl ? <img alt="Board map" className="absolute inset-0 h-full w-full object-contain" src={boardImageUrl} /> : <div className="flex h-full min-h-[22rem] items-center justify-center text-sm text-slate-500">Upload an image to start placing nodes.</div>}
            <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
              {Object.entries(draftMap.adjacency || {}).flatMap(([fromId, adjacent]) => (adjacent || []).filter((toId) => fromId < toId).map((toId) => {
                const from = draftMap.nodes[fromId];
                const to = draftMap.nodes[toId];
                if (!from || !to) return null;
                return <line key={`${fromId}:${toId}`} stroke="rgba(13,148,136,0.75)" strokeWidth="0.006" x1={from.x} x2={to.x} y1={from.y} y2={to.y} />;
              }))}
            </svg>
            {Object.values(draftMap.nodes || {}).map((node) => (
              <button className={`absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border text-xs font-semibold ${selectedNodeId === node.id ? "border-teal-950 bg-teal-300 text-teal-950" : edgeStartNodeId === node.id ? "border-teal-600 bg-teal-100 text-teal-900" : "border-white bg-teal-600/90 text-white"}`} key={node.id} onClick={(event) => handleNodeClick(event, node.id)} style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%` }} type="button">
                {node.id}
              </button>
            ))}
          </div>
        </div>

        <aside className="space-y-3">
          <label className="block text-sm">
            <span className="text-slate-600">Name</span>
            <input className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800" value={draftMap.name} onChange={(event) => setDraftMap((current) => ({ ...current, name: event.target.value }))} />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Board image</span>
            <input ref={imageInputRef} className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-sm text-slate-700" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] || null)} />
          </label>
          {selectedNode ? (
            <div className="rounded-md border border-cyan-100 bg-cyan-50 p-3">
              <p className="font-semibold text-teal-950">Node {selectedNode.id}</p>
              <label className="mt-3 block text-sm">
                <span className="text-slate-600">Tier</span>
                <input className="mt-1 w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800" type="number" min="1" value={selectedNode.tier || 1} onChange={(event) => updateSelectedNode({ tier: Number(event.target.value) })} />
              </label>
              <p className="mt-3 text-xs text-slate-500">x {selectedNode.x.toFixed(3)} - y {selectedNode.y.toFixed(3)}</p>
              <button className="mt-3 w-full rounded-md border border-rose-300 bg-white px-3 py-2 text-sm text-rose-700 hover:bg-rose-50" onClick={deleteSelectedNode} type="button">Delete node</button>
            </div>
          ) : null}
          <button className="w-full rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-60" disabled={busy} onClick={saveMap} type="button">
            {busy ? "Saving..." : "Save map"}
          </button>
        </aside>
      </div>
    </section>
  );
};

export default AdminMapEditor;
