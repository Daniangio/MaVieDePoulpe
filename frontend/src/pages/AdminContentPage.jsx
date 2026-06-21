import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const adminSubnavItems = [
  { label: "Backoffice", to: "/admin" },
  { label: "Game content", to: "/admin/content" },
];

const emptyInteraction = { id: "", name: "", image_url: "" };
const emptyEvent = { id: "", name: "", category_id: "", image_url: "" };
const emptyTile = { id: "", name: "", event_id: "", interaction_ids: [] };

const imageUrl = (entry) => (entry?.image_url ? buildApiUrl(entry.image_url) : "");

const AdminContentPage = () => {
  const { token, user } = useStore();
  const [content, setContent] = useState({ categories: [], interactions: [], events: [], tiles: [], cards: [] });
  const [categoryName, setCategoryName] = useState("");
  const [interactionDraft, setInteractionDraft] = useState(emptyInteraction);
  const [eventDraft, setEventDraft] = useState(emptyEvent);
  const [tileDraft, setTileDraft] = useState(emptyTile);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const interactionImageRef = useRef(null);
  const eventImageRef = useRef(null);

  const categoriesById = useMemo(() => Object.fromEntries(content.categories.map((category) => [category.id, category])), [content.categories]);
  const eventsById = useMemo(() => Object.fromEntries(content.events.map((event) => [event.id, event])), [content.events]);
  const interactionsById = useMemo(() => Object.fromEntries(content.interactions.map((interaction) => [interaction.id, interaction])), [content.interactions]);

  const request = async (path, options = {}) => {
    const response = await fetch(buildApiUrl(path), {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Admin content request failed.");
    return payload;
  };

  const loadContent = async () => {
    if (!token) return;
    setError("");
    try {
      setContent(await request("/api/admin/content"));
    } catch (loadError) {
      setError(loadError.message || "Failed to load game content.");
    }
  };

  useEffect(() => {
    void loadContent();
  }, [token]);

  const resetInteraction = () => {
    setInteractionDraft(emptyInteraction);
    if (interactionImageRef.current) interactionImageRef.current.value = "";
  };

  const resetEvent = () => {
    setEventDraft(emptyEvent);
    if (eventImageRef.current) eventImageRef.current.value = "";
  };

  const resetTile = () => {
    setTileDraft(emptyTile);
  };

  const saveCategory = async (category = null) => {
    const name = category ? category.name : categoryName;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", name);
      await request(category ? `/api/admin/content/categories/${category.id}` : "/api/admin/content/categories", {
        method: category ? "PUT" : "POST",
        body: form,
      });
      setCategoryName("");
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save category.");
    } finally {
      setBusy(false);
    }
  };

  const deleteItem = async (path, label) => {
    if (!window.confirm(`Delete ${label}?`)) return;
    setBusy(true);
    setError("");
    try {
      await request(path, { method: "DELETE" });
      await loadContent();
    } catch (deleteError) {
      setError(deleteError.message || `Failed to delete ${label}.`);
    } finally {
      setBusy(false);
    }
  };

  const saveInteraction = async () => {
    setBusy(true);
    setError("");
    try {
      const file = interactionImageRef.current?.files?.[0] || null;
      if (!interactionDraft.id && !file) throw new Error("Upload an interaction symbol image.");
      const form = new FormData();
      form.set("name", interactionDraft.name);
      if (file) form.set("image", file);
      await request(
        interactionDraft.id ? `/api/admin/content/interactions/${interactionDraft.id}` : "/api/admin/content/interactions",
        { method: interactionDraft.id ? "PUT" : "POST", body: form }
      );
      resetInteraction();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save interaction.");
    } finally {
      setBusy(false);
    }
  };

  const saveEvent = async () => {
    setBusy(true);
    setError("");
    try {
      const file = eventImageRef.current?.files?.[0] || null;
      if (!eventDraft.id && !file) throw new Error("Upload an event image.");
      const form = new FormData();
      form.set("name", eventDraft.name);
      form.set("category_id", eventDraft.category_id);
      if (file) form.set("image", file);
      await request(eventDraft.id ? `/api/admin/content/events/${eventDraft.id}` : "/api/admin/content/events", {
        method: eventDraft.id ? "PUT" : "POST",
        body: form,
      });
      resetEvent();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save event.");
    } finally {
      setBusy(false);
    }
  };

  const saveTile = async () => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", tileDraft.name);
      form.set("event_id", tileDraft.event_id);
      form.set("interaction_ids_json", JSON.stringify(tileDraft.interaction_ids));
      await request(tileDraft.id ? `/api/admin/content/tiles/${tileDraft.id}` : "/api/admin/content/tiles", {
        method: tileDraft.id ? "PUT" : "POST",
        body: form,
      });
      resetTile();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save tile.");
    } finally {
      setBusy(false);
    }
  };

  const toggleTileInteraction = (interactionId) => {
    setTileDraft((current) => {
      const selected = new Set(current.interaction_ids || []);
      if (selected.has(interactionId)) selected.delete(interactionId);
      else selected.add(interactionId);
      return { ...current, interaction_ids: Array.from(selected) };
    });
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
      <PageSubnavigation items={adminSubnavItems} />
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-white">Game Content</h1>
        <p className="mt-1 text-sm text-slate-400">Design interaction symbols, event tiles, tile requirements, and generated cards.</p>
      </div>

      {error ? <p className="mb-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}

      <section className="grid gap-4 xl:grid-cols-[20rem_1fr]">
        <aside className="space-y-4">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="font-semibold text-white">Categories</h2>
            <div className="mt-3 flex gap-2">
              <input className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="Category name" />
              <button className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={busy} onClick={() => saveCategory()} type="button">Add</button>
            </div>
            <div className="mt-3 space-y-2">
              {content.categories.map((category) => (
                <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950 p-2" key={category.id}>
                  <input className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none" value={category.name} onChange={(event) => setContent((current) => ({ ...current, categories: current.categories.map((item) => item.id === category.id ? { ...item, name: event.target.value } : item) }))} />
                  <button className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200" disabled={busy} onClick={() => saveCategory(category)} type="button">Save</button>
                  <button className="rounded border border-rose-500/50 px-2 py-1 text-xs text-rose-100" disabled={busy} onClick={() => deleteItem(`/api/admin/content/categories/${category.id}`, category.name)} type="button">Delete</button>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="font-semibold text-white">Interaction Type</h2>
            <label className="mt-3 block text-sm">
              <span className="text-slate-300">Name</span>
              <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={interactionDraft.name} onChange={(event) => setInteractionDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Charge" />
            </label>
            <label className="mt-3 block text-sm">
              <span className="text-slate-300">Card symbol</span>
              <input ref={interactionImageRef} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300" type="file" accept="image/png,image/jpeg,image/webp" />
            </label>
            <div className="mt-3 flex gap-2">
              <button className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={busy} onClick={saveInteraction} type="button">{interactionDraft.id ? "Update" : "Create"}</button>
              <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200" onClick={resetInteraction} type="button">Clear</button>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="font-semibold text-white">Event / Animal</h2>
            <label className="mt-3 block text-sm">
              <span className="text-slate-300">Name</span>
              <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={eventDraft.name} onChange={(event) => setEventDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Crab" />
            </label>
            <label className="mt-3 block text-sm">
              <span className="text-slate-300">Category</span>
              <select className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={eventDraft.category_id} onChange={(event) => setEventDraft((current) => ({ ...current, category_id: event.target.value }))}>
                <option value="">Select category</option>
                {content.categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
              </select>
            </label>
            <label className="mt-3 block text-sm">
              <span className="text-slate-300">Tile image</span>
              <input ref={eventImageRef} className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300" type="file" accept="image/png,image/jpeg,image/webp" />
            </label>
            <div className="mt-3 flex gap-2">
              <button className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={busy} onClick={saveEvent} type="button">{eventDraft.id ? "Update" : "Create"}</button>
              <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200" onClick={resetEvent} type="button">Clear</button>
            </div>
          </div>
        </aside>

        <div className="space-y-4">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold text-white">Tiles</h2>
              <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200" onClick={resetTile} type="button">New tile</button>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-[18rem_1fr]">
              <div className="space-y-3">
                <input className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={tileDraft.name} onChange={(event) => setTileDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Tile name" />
                <select className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white" value={tileDraft.event_id} onChange={(event) => setTileDraft((current) => ({ ...current, event_id: event.target.value }))}>
                  <option value="">Select event</option>
                  {content.events.map((event) => <option key={event.id} value={event.id}>{event.name}</option>)}
                </select>
                <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
                  <p className="mb-2 text-sm font-medium text-slate-300">Required interactions</p>
                  <div className="space-y-2">
                    {content.interactions.map((interaction) => (
                      <label className="flex items-center gap-2 text-sm text-slate-200" key={interaction.id}>
                        <input checked={(tileDraft.interaction_ids || []).includes(interaction.id)} onChange={() => toggleTileInteraction(interaction.id)} type="checkbox" />
                        {interaction.name}
                      </label>
                    ))}
                  </div>
                </div>
                <button className="w-full rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={busy} onClick={saveTile} type="button">{tileDraft.id ? "Update tile" : "Create tile"}</button>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {content.tiles.map((tile) => {
                  const event = eventsById[tile.event_id];
                  return (
                    <article className="rounded-md border border-slate-800 bg-slate-950 p-3" key={tile.id}>
                      <div className="flex gap-3">
                        {imageUrl(event) ? <img alt="" className="h-14 w-14 rounded object-cover" src={imageUrl(event)} /> : null}
                        <div className="min-w-0">
                          <h3 className="truncate font-semibold text-white">{tile.name}</h3>
                          <p className="text-xs text-slate-400">{event?.name || "Missing event"} - {categoriesById[event?.category_id]?.name || "No category"}</p>
                        </div>
                      </div>
                      <p className="mt-3 text-xs text-slate-500">Requires: {(tile.interaction_ids || []).map((id) => interactionsById[id]?.name || id).join(", ")}</p>
                      <div className="mt-3 flex gap-2">
                        <button className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200" onClick={() => setTileDraft(tile)} type="button">Edit</button>
                        <button className="rounded border border-rose-500/50 px-2 py-1 text-xs text-rose-100" disabled={busy} onClick={() => deleteItem(`/api/admin/content/tiles/${tile.id}`, tile.name)} type="button">Delete</button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <ContentList title="Interactions" items={content.interactions} onEdit={setInteractionDraft} onDelete={(item) => deleteItem(`/api/admin/content/interactions/${item.id}`, item.name)} />
            <ContentList title="Events / Animals" items={content.events.map((event) => ({ ...event, subtitle: categoriesById[event.category_id]?.name || "No category" }))} onEdit={setEventDraft} onDelete={(item) => deleteItem(`/api/admin/content/events/${item.id}`, item.name)} />
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="font-semibold text-white">Generated Cards</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {content.cards.map((card) => (
                <article className="rounded-md border border-slate-800 bg-slate-950 p-3" key={card.id}>
                  <div className="flex items-center gap-3">
                    {card.image_url ? <img alt="" className="h-12 w-12 rounded object-cover" src={buildApiUrl(card.image_url)} /> : null}
                    <h3 className="font-semibold text-white">{card.name}</h3>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {content.categories.map((category) => {
                      const resolved = card.resolves?.[category.id] || [];
                      return (
                        <div className="rounded border border-slate-800 bg-slate-900 p-2" key={category.id}>
                          <p className="text-xs font-semibold text-slate-300">{category.name}</p>
                          {resolved.length ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {resolved.map((entry) => (
                                <span className="inline-flex items-center gap-1 rounded bg-slate-800 px-2 py-1 text-xs text-slate-200" key={`${entry.tile_id}:${entry.event_id}`}>
                                  {entry.event_image_url ? <img alt="" className="h-5 w-5 rounded object-cover" src={buildApiUrl(entry.event_image_url)} /> : null}
                                  {entry.event_name}
                                </span>
                              ))}
                            </div>
                          ) : <p className="mt-2 text-xs text-slate-600">None</p>}
                        </div>
                      );
                    })}
                  </div>
                </article>
              ))}
              {content.cards.length === 0 ? <p className="text-sm text-slate-400">Create interaction types to generate cards.</p> : null}
            </div>
          </section>
        </div>
      </section>
    </>
  );
};

const ContentList = ({ title, items, onEdit, onDelete }) => (
  <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
    <h2 className="font-semibold text-white">{title}</h2>
    <div className="mt-3 space-y-2">
      {items.map((item) => (
        <article className="flex items-center gap-3 rounded-md border border-slate-800 bg-slate-950 p-2" key={item.id}>
          {imageUrl(item) ? <img alt="" className="h-12 w-12 rounded object-cover" src={imageUrl(item)} /> : null}
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-white">{item.name}</h3>
            {item.subtitle ? <p className="text-xs text-slate-500">{item.subtitle}</p> : null}
          </div>
          <button className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200" onClick={() => onEdit(item)} type="button">Edit</button>
          <button className="rounded border border-rose-500/50 px-2 py-1 text-xs text-rose-100" onClick={() => onDelete(item)} type="button">Delete</button>
        </article>
      ))}
      {items.length === 0 ? <p className="text-sm text-slate-400">No items yet.</p> : null}
    </div>
  </section>
);

export default AdminContentPage;
