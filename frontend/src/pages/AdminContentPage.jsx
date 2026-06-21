import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AdminLevelEditor from "../components/AdminLevelEditor.jsx";
import AdminMapEditor from "../components/AdminMapEditor.jsx";
import HexTilePreview from "../components/HexTilePreview.jsx";
import PlayerBoardPreview from "../components/PlayerBoardPreview.jsx";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const adminSubnavItems = [
  { label: "Backoffice", to: "/admin" },
  { label: "Game content", to: "/admin/content" },
];

const emptyInteraction = { id: "", name: "", image_url: "" };
const emptyEvent = { id: "", name: "", category_id: "", image_url: "" };
const emptyTile = {
  id: "",
  name: "",
  event_id: "",
  interaction_ids: [],
  counter_attack_interaction_ids: [],
  success_effects: [],
  counter_attack_effects: [],
  failure_effects: [],
};
const emptyPlayerBoard = {
  id: "",
  name: "",
  initiates_event_ids: [],
  deck: [],
  default_max_cards_in_hand: 3,
  hand_size_upgrades: [],
  actions_per_control: 3,
  control_takes_per_night: 3,
};

const successEffectOptions = [
  ["gain_energy", "Gain energy"],
  ["gain_neurons", "Gain neurons"],
  ["gain_seashells", "Gain seashells"],
];

const failureEffectOptions = [
  ["lose_energy", "Lose energy"],
  ["lose_neurons", "Lose neurons"],
  ["lose_seashells", "Lose seashells"],
  ["lose_ap", "Lose AP"],
  ["half_ap", "Lose half AP"],
  ["all_ap", "Lose all AP"],
  ["stay_node", "Poulpita remains on same node"],
  ["move_node_free", "Poulpita must move for free"],
  ["keep_tile", "Keep tile"],
  ["remove_tile", "Remove tile"],
];
const noAmountEffectTypes = new Set(["half_ap", "all_ap", "stay_node", "move_node_free", "keep_tile", "remove_tile"]);

const contentTabs = [
  ["map", "Map"],
  ["levels", "Levels"],
  ["categories", "Categories"],
  ["interactions", "Interactions"],
  ["events", "Events/Animals"],
  ["tiles", "Tiles"],
  ["cards", "Cards"],
  ["player_boards", "Player Boards"],
];

const imageUrl = (entry) => (entry?.image_url ? buildApiUrl(entry.image_url) : "");
const panel = "rounded-lg border border-cyan-200 bg-white/90 p-4 shadow-sm";
const input = "w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800 outline-none focus:border-teal-500";
const subtleButton = "rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50";
const primaryButton = "rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-60";
const dangerButton = "rounded-md border border-rose-300 bg-white px-3 py-2 text-sm text-rose-700 hover:bg-rose-50";

const AdminContentPage = () => {
  const { token, user } = useStore();
  const [content, setContent] = useState({ categories: [], card_categories: [], interactions: [], events: [], tiles: [], levels: [], player_boards: [], cards: [] });
  const [categoryName, setCategoryName] = useState("");
  const [interactionDraft, setInteractionDraft] = useState(emptyInteraction);
  const [eventDraft, setEventDraft] = useState(emptyEvent);
  const [tileDraft, setTileDraft] = useState(emptyTile);
  const [playerBoardDraft, setPlayerBoardDraft] = useState(emptyPlayerBoard);
  const [activeTab, setActiveTab] = useState("map");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const interactionImageRef = useRef(null);
  const eventImageRef = useRef(null);

  const categoriesById = useMemo(() => Object.fromEntries(content.categories.map((category) => [category.id, category])), [content.categories]);
  const eventsById = useMemo(() => Object.fromEntries(content.events.map((event) => [event.id, event])), [content.events]);
  const interactionsById = useMemo(() => Object.fromEntries(content.interactions.map((interaction) => [interaction.id, interaction])), [content.interactions]);
  const cardCategories = content.card_categories?.length ? content.card_categories : content.categories;

  const request = async (path, options = {}) => {
    const response = await fetch(buildApiUrl(path), {
      ...options,
      headers: { Authorization: `Bearer ${token}`, ...(options.headers || {}) },
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

  useEffect(() => {
    if (!playerBoardDraft.id && content.player_boards?.length) {
      setPlayerBoardDraft({ ...emptyPlayerBoard, ...content.player_boards[0] });
    }
  }, [content.player_boards, playerBoardDraft.id]);

  const resetInteraction = () => {
    setInteractionDraft(emptyInteraction);
    if (interactionImageRef.current) interactionImageRef.current.value = "";
  };
  const resetEvent = () => {
    setEventDraft(emptyEvent);
    if (eventImageRef.current) eventImageRef.current.value = "";
  };
  const resetTile = () => setTileDraft(emptyTile);

  const saveCategory = async (category = null) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", category ? category.name : categoryName);
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
      await request(interactionDraft.id ? `/api/admin/content/interactions/${interactionDraft.id}` : "/api/admin/content/interactions", {
        method: interactionDraft.id ? "PUT" : "POST",
        body: form,
      });
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
      form.set("interaction_ids_json", JSON.stringify(tileDraft.interaction_ids || []));
      form.set("counter_attack_interaction_ids_json", JSON.stringify(tileDraft.counter_attack_interaction_ids || []));
      form.set("success_effects_json", JSON.stringify(tileDraft.success_effects || []));
      form.set("counter_attack_effects_json", JSON.stringify(tileDraft.counter_attack_effects || []));
      form.set("failure_effects_json", JSON.stringify(tileDraft.failure_effects || []));
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

  const savePlayerBoard = async () => {
    if (!playerBoardDraft.id) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", playerBoardDraft.name);
      form.set("initiates_event_ids_json", JSON.stringify(playerBoardDraft.initiates_event_ids || []));
      form.set("deck_json", JSON.stringify((playerBoardDraft.deck || []).filter((entry) => Number(entry.count || 0) > 0)));
      form.set("default_max_cards_in_hand", String(playerBoardDraft.default_max_cards_in_hand || 3));
      form.set("hand_size_upgrades_json", JSON.stringify(playerBoardDraft.hand_size_upgrades || []));
      form.set("actions_per_control", String(playerBoardDraft.actions_per_control || 3));
      form.set("control_takes_per_night", String(playerBoardDraft.control_takes_per_night || 3));
      await request(`/api/admin/content/player-boards/${playerBoardDraft.id}`, { method: "PUT", body: form });
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save player board.");
    } finally {
      setBusy(false);
    }
  };

  const toggleTileInteraction = (field, interactionId) => {
    setTileDraft((current) => {
      const selected = new Set(current[field] || []);
      if (selected.has(interactionId)) selected.delete(interactionId);
      else selected.add(interactionId);
      return { ...current, [field]: Array.from(selected) };
    });
  };

  const addEffect = (field, type) => {
    setTileDraft((current) => ({ ...current, [field]: [...(current[field] || []), { type, amount: noAmountEffectTypes.has(type) ? null : 1 }] }));
  };

  const updateEffect = (field, index, patch) => {
    setTileDraft((current) => ({
      ...current,
      [field]: (current[field] || []).map((effect, effectIndex) => (effectIndex === index ? { ...effect, ...patch } : effect)),
    }));
  };

  const removeEffect = (field, index) => {
    setTileDraft((current) => ({ ...current, [field]: (current[field] || []).filter((_effect, effectIndex) => effectIndex !== index) }));
  };

  const togglePlayerBoardInitiation = (eventId) => {
    setPlayerBoardDraft((current) => {
      const selected = new Set(current.initiates_event_ids || []);
      if (selected.has(eventId)) selected.delete(eventId);
      else selected.add(eventId);
      return { ...current, initiates_event_ids: Array.from(selected) };
    });
  };

  const setDeckCount = (interactionId, count) => {
    setPlayerBoardDraft((current) => {
      const nextDeck = (current.deck || []).filter((entry) => entry.interaction_id !== interactionId);
      if (count > 0) nextDeck.push({ interaction_id: interactionId, count });
      return { ...current, deck: nextDeck };
    });
  };

  const addUpgrade = () => {
    setPlayerBoardDraft((current) => ({
      ...current,
      hand_size_upgrades: [...(current.hand_size_upgrades || []), { cost_resource: "energy", cost: 1, hand_size_bonus: 1 }],
    }));
  };

  const updateUpgrade = (index, patch) => {
    setPlayerBoardDraft((current) => ({
      ...current,
      hand_size_upgrades: (current.hand_size_upgrades || []).map((upgrade, upgradeIndex) => (upgradeIndex === index ? { ...upgrade, ...patch } : upgrade)),
    }));
  };

  const removeUpgrade = (index) => {
    setPlayerBoardDraft((current) => ({
      ...current,
      hand_size_upgrades: (current.hand_size_upgrades || []).filter((_upgrade, upgradeIndex) => upgradeIndex !== index),
    }));
  };

  if (!user?.is_admin) {
    return (
      <div className={panel}>
        <h1 className="text-2xl font-semibold text-teal-950">Admin</h1>
        <p className="mt-2 text-slate-600">Admin access is required.</p>
        <Link className="mt-5 inline-block rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white" to="/lobby">Back to lobby</Link>
      </div>
    );
  }

  return (
    <div className="-m-4 min-h-screen bg-gradient-to-b from-cyan-50 via-teal-50 to-white p-4 text-slate-800">
      <PageSubnavigation items={adminSubnavItems} />
      <div className="mb-5">
        <h1 className="text-2xl font-semibold text-teal-950">Game Content</h1>
        <p className="mt-1 text-sm text-teal-800">Design interaction symbols, event tiles, counter-attacks, effects, and generated cards.</p>
      </div>

      {error ? <p className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <nav className="mb-4 flex flex-wrap gap-2">
        {contentTabs.map(([id, label]) => (
          <button className={`rounded-md px-3 py-2 text-sm font-medium ${activeTab === id ? "bg-teal-500 text-white" : "border border-cyan-300 bg-white text-teal-900 hover:bg-cyan-50"}`} key={id} onClick={() => setActiveTab(id)} type="button">
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "map" ? <AdminMapEditor busy={busy} request={request} setBusy={setBusy} setError={setError} /> : null}

      {activeTab === "levels" ? <AdminLevelEditor busy={busy} content={content} onReload={loadContent} request={request} setBusy={setBusy} setError={setError} /> : null}

      {activeTab === "categories" ? (
        <CategoryEditor
          busy={busy}
          categoryName={categoryName}
          content={content}
          deleteItem={deleteItem}
          saveCategory={saveCategory}
          setCategoryName={setCategoryName}
          setContent={setContent}
        />
      ) : null}

      {activeTab === "interactions" ? (
        <section className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <InteractionEditor busy={busy} draft={interactionDraft} imageRef={interactionImageRef} reset={resetInteraction} save={saveInteraction} setDraft={setInteractionDraft} />
          <ContentList title="Interactions" items={content.interactions} onEdit={setInteractionDraft} onDelete={(item) => deleteItem(`/api/admin/content/interactions/${item.id}`, item.name)} />
        </section>
      ) : null}

      {activeTab === "events" ? (
        <section className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <EventEditor busy={busy} categories={content.categories} draft={eventDraft} imageRef={eventImageRef} reset={resetEvent} save={saveEvent} setDraft={setEventDraft} />
          <ContentList title="Events / Animals" items={content.events.map((event) => ({ ...event, subtitle: categoriesById[event.category_id]?.name || "No category" }))} onEdit={setEventDraft} onDelete={(item) => deleteItem(`/api/admin/content/events/${item.id}`, item.name)} />
        </section>
      ) : null}

      {activeTab === "tiles" ? (
        <TileEditor
          busy={busy}
          categoriesById={categoriesById}
          content={content}
          deleteItem={deleteItem}
          eventsById={eventsById}
          interactionsById={interactionsById}
          saveTile={saveTile}
          setTileDraft={setTileDraft}
          tileDraft={tileDraft}
          toggleTileInteraction={toggleTileInteraction}
          addEffect={addEffect}
          updateEffect={updateEffect}
          removeEffect={removeEffect}
        />
      ) : null}

      {activeTab === "cards" ? <CardsView cardCategories={cardCategories} content={content} /> : null}

      {activeTab === "player_boards" ? (
        <PlayerBoardEditor
          boards={content.player_boards || []}
          events={content.events}
          interactions={content.interactions}
          eventsById={eventsById}
          interactionsById={interactionsById}
          draft={playerBoardDraft}
          setDraft={setPlayerBoardDraft}
          onSave={savePlayerBoard}
          busy={busy}
          onToggleInitiation={togglePlayerBoardInitiation}
          onSetDeckCount={setDeckCount}
          onAddUpgrade={addUpgrade}
          onUpdateUpgrade={updateUpgrade}
          onRemoveUpgrade={removeUpgrade}
        />
      ) : null}
    </div>
  );
};

const EditorPanel = ({ title, children }) => (
  <div className={panel}>
    <h2 className="font-semibold text-teal-950">{title}</h2>
    <div className="mt-3">{children}</div>
  </div>
);

const CategoryEditor = ({ busy, categoryName, content, deleteItem, saveCategory, setCategoryName, setContent }) => (
  <section className={panel}>
    <h2 className="font-semibold text-teal-950">Categories</h2>
    <p className="mt-1 text-xs text-slate-500">Counter-attack is special and does not appear here.</p>
    <div className="mt-3 flex gap-2">
      <input className={input} value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="Category name" />
      <button className={primaryButton} disabled={busy} onClick={() => saveCategory()} type="button">Add</button>
    </div>
    <div className="mt-3 space-y-2">
      {content.categories.map((category) => (
        <div className="flex items-center gap-2 rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={category.id}>
          <input className="min-w-0 flex-1 bg-transparent text-sm text-teal-950 outline-none" value={category.name} onChange={(event) => setContent((current) => ({ ...current, categories: current.categories.map((item) => item.id === category.id ? { ...item, name: event.target.value } : item) }))} />
          <button className={subtleButton} disabled={busy} onClick={() => saveCategory(category)} type="button">Save</button>
          <button className={dangerButton} disabled={busy} onClick={() => deleteItem(`/api/admin/content/categories/${category.id}`, category.name)} type="button">Delete</button>
        </div>
      ))}
    </div>
  </section>
);

const InteractionEditor = ({ busy, draft, imageRef, reset, save, setDraft }) => (
  <EditorPanel title="Interaction Type">
    <label className="block text-sm">
      <span className="text-slate-600">Name</span>
      <input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Charge" />
    </label>
    <label className="mt-3 block text-sm">
      <span className="text-slate-600">Card symbol</span>
      <input ref={imageRef} className={`${input} mt-1 text-sm`} type="file" accept="image/png,image/jpeg,image/webp" />
    </label>
    <div className="mt-3 flex gap-2">
      <button className={primaryButton} disabled={busy} onClick={save} type="button">{draft.id ? "Update" : "Create"}</button>
      <button className={subtleButton} onClick={reset} type="button">Clear</button>
    </div>
  </EditorPanel>
);

const EventEditor = ({ busy, categories, draft, imageRef, reset, save, setDraft }) => (
  <EditorPanel title="Event / Animal">
    <label className="block text-sm">
      <span className="text-slate-600">Name</span>
      <input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Crab" />
    </label>
    <label className="mt-3 block text-sm">
      <span className="text-slate-600">Category</span>
      <select className={`${input} mt-1`} value={draft.category_id} onChange={(event) => setDraft((current) => ({ ...current, category_id: event.target.value }))}>
        <option value="">Select category</option>
        {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
      </select>
    </label>
    <label className="mt-3 block text-sm">
      <span className="text-slate-600">Tile image</span>
      <input ref={imageRef} className={`${input} mt-1 text-sm`} type="file" accept="image/png,image/jpeg,image/webp" />
    </label>
    <div className="mt-3 flex gap-2">
      <button className={primaryButton} disabled={busy} onClick={save} type="button">{draft.id ? "Update" : "Create"}</button>
      <button className={subtleButton} onClick={reset} type="button">Clear</button>
    </div>
  </EditorPanel>
);

const TileEditor = ({ addEffect, busy, categoriesById, content, deleteItem, eventsById, interactionsById, removeEffect, saveTile, setTileDraft, tileDraft, toggleTileInteraction, updateEffect }) => (
  <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-semibold text-teal-950">Tiles</h2>
      <button className={subtleButton} onClick={() => setTileDraft(emptyTile)} type="button">New tile</button>
    </div>
    <div className="mt-4 grid gap-4 xl:grid-cols-[22rem_18rem_1fr]">
      <div className="space-y-3">
        <input className={input} value={tileDraft.name} onChange={(event) => setTileDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Tile name" />
        <select className={input} value={tileDraft.event_id} onChange={(event) => setTileDraft((current) => ({ ...current, event_id: event.target.value }))}>
          <option value="">Select event</option>
          {content.events.map((event) => <option key={event.id} value={event.id}>{event.name}</option>)}
        </select>
        <InteractionChecklist title="Required to succeed" field="interaction_ids" interactions={content.interactions} selected={tileDraft.interaction_ids} onToggle={toggleTileInteraction} />
        <InteractionChecklist title="Optional counter-attack" field="counter_attack_interaction_ids" interactions={content.interactions} selected={tileDraft.counter_attack_interaction_ids} onToggle={toggleTileInteraction} />
        <EffectEditor title="Success effects" field="success_effects" effects={tileDraft.success_effects} options={successEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
        <EffectEditor title="Counter-attack effects" field="counter_attack_effects" effects={tileDraft.counter_attack_effects} options={successEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
        <EffectEditor title="Failure effects" field="failure_effects" effects={tileDraft.failure_effects} options={failureEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
        <button className="w-full rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-60" disabled={busy} onClick={saveTile} type="button">{tileDraft.id ? "Update tile" : "Create tile"}</button>
      </div>
      <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
        <h3 className="mb-3 text-sm font-semibold text-teal-950">Tile preview</h3>
        <HexTilePreview event={eventsById[tileDraft.event_id]} interactionsById={interactionsById} tile={tileDraft} />
      </div>
      <TileList content={content} eventsById={eventsById} categoriesById={categoriesById} interactionsById={interactionsById} setTileDraft={setTileDraft} deleteItem={deleteItem} busy={busy} />
    </div>
  </section>
);

const CardsView = ({ cardCategories, content }) => (
  <section className={panel}>
    <h2 className="font-semibold text-teal-950">Generated Cards</h2>
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      {content.cards.map((card) => (
        <article className="rounded-md border border-cyan-200 bg-white p-3 shadow-sm" key={card.id}>
          <div className="flex items-center gap-3">
            {card.image_url ? <img alt="" className="h-12 w-12 rounded object-cover" src={buildApiUrl(card.image_url)} /> : null}
            <h3 className="font-semibold text-teal-950">{card.name}</h3>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {cardCategories.map((category) => {
              const resolved = card.resolves?.[category.id] || [];
              return (
                <div className={`rounded border p-2 ${category.special ? "border-fuchsia-200 bg-fuchsia-50" : "border-cyan-100 bg-cyan-50"}`} key={category.id}>
                  <p className="text-xs font-semibold text-teal-900">{category.name}</p>
                  {resolved.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {resolved.map((entry) => (
                        <span className="inline-flex items-center gap-1 rounded bg-white px-2 py-1 text-xs text-slate-700 shadow-sm" key={`${entry.tile_id}:${entry.event_id}:${entry.requirement_type}`}>
                          {entry.event_image_url ? <img alt="" className="h-5 w-5 rounded object-cover" src={buildApiUrl(entry.event_image_url)} /> : null}
                          {entry.event_name}
                        </span>
                      ))}
                    </div>
                  ) : <p className="mt-2 text-xs text-slate-400">None</p>}
                </div>
              );
            })}
          </div>
        </article>
      ))}
      {content.cards.length === 0 ? <p className="text-sm text-slate-500">Create interaction types to generate cards.</p> : null}
    </div>
  </section>
);

const PlayerBoardEditor = ({
  boards,
  events,
  interactions,
  eventsById,
  interactionsById,
  draft,
  setDraft,
  onSave,
  busy,
  onToggleInitiation,
  onSetDeckCount,
  onAddUpgrade,
  onUpdateUpgrade,
  onRemoveUpgrade,
}) => {
  const deckByInteraction = Object.fromEntries((draft.deck || []).map((entry) => [entry.interaction_id, Number(entry.count || 0)]));
  return (
    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-teal-950">Player Boards</h2>
          <p className="mt-1 text-xs text-slate-500">There are always exactly five boards. Configure their decks and limits here.</p>
        </div>
        <select className="rounded-md border border-cyan-200 bg-white px-3 py-2 text-sm text-slate-800" value={draft.id} onChange={(event) => setDraft({ ...emptyPlayerBoard, ...(boards.find((board) => board.id === event.target.value) || {}) })}>
          {boards.map((board) => <option key={board.id} value={board.id}>{board.name}</option>)}
        </select>
      </div>

      {draft.id ? (
        <div className="mt-4 grid gap-2 xl:grid-rows-2">
          <div className="grid gap-4 xl:grid-cols-4">
            <div className="space-y-3">
              <label className="block text-sm">
                <span className="text-slate-600">Board name</span>
                <input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Default max cards in hand</span>
                <input className={`${input} mt-1`} min="1" type="number" value={draft.default_max_cards_in_hand || 3} onChange={(event) => setDraft((current) => ({ ...current, default_max_cards_in_hand: Number(event.target.value) }))} />
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Actions per control</span>
                <input className={`${input} mt-1`} min="1" type="number" value={draft.actions_per_control || 3} onChange={(event) => setDraft((current) => ({ ...current, actions_per_control: Number(event.target.value) }))} />
              </label>
              <label className="block text-sm">
                <span className="text-slate-600">Control takes per night</span>
                <input className={`${input} mt-1`} min="1" type="number" value={draft.control_takes_per_night || 3} onChange={(event) => setDraft((current) => ({ ...current, control_takes_per_night: Number(event.target.value) }))} />
              </label>
              <button className={primaryButton} disabled={busy} onClick={onSave} type="button">Save player board</button>
            </div>
              <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
                <h3 className="text-sm font-semibold text-teal-950">Can initiate</h3>
                <div className="mt-2 space-y-2">
                  {events.map((event) => (
                    <label className="flex items-center gap-2 text-sm text-slate-700" key={event.id}>
                      <input checked={(draft.initiates_event_ids || []).includes(event.id)} onChange={() => onToggleInitiation(event.id)} type="checkbox" />
                      {imageUrl(event) ? <img alt="" className="h-7 w-7 rounded object-cover" src={imageUrl(event)} /> : null}
                      <span className="min-w-0 truncate">{event.name}</span>
                    </label>
                  ))}
                  {events.length === 0 ? <p className="text-xs text-slate-500">Create events or animals first.</p> : null}
                </div>
              </div>

              <div className="rounded-md border border-cyan-100 bg-white p-3">
                <h3 className="text-sm font-semibold text-teal-950">Deck</h3>
                <div className="mt-2 space-y-2">
                  {interactions.map((interaction) => (
                    <label className="flex items-center justify-between gap-3 text-sm text-slate-700" key={interaction.id}>
                      <span className="min-w-0 flex-1 truncate">{interaction.name}</span>
                      <input className="w-20 rounded border border-cyan-200 px-2 py-1 text-sm" min="0" type="number" value={deckByInteraction[interaction.id] || 0} onChange={(event) => onSetDeckCount(interaction.id, Number(event.target.value))} />
                    </label>
                  ))}
                </div>
              </div>

              <div className="rounded-md border border-cyan-100 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-teal-950">Hand upgrades</h3>
                  <button className={subtleButton} onClick={onAddUpgrade} type="button">Add</button>
                </div>
                <div className="mt-2 space-y-2">
                  {(draft.hand_size_upgrades || []).map((upgrade, index) => (
                    <div className="grid grid-cols-[1fr_1.5rem_1.5rem_auto] gap-1 rounded bg-cyan-50 p-2" key={index}>
                      <select className="rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={upgrade.cost_resource || "energy"} onChange={(event) => onUpdateUpgrade(index, { cost_resource: event.target.value })}>
                        <option value="energy">Energy</option>
                        <option value="neurons">Neurons</option>
                      </select>
                      <input className="rounded border border-cyan-200 py-1 text-xs" min="1" type="number" value={upgrade.cost || 1} onChange={(event) => onUpdateUpgrade(index, { cost: Number(event.target.value) })} />
                      <input className="rounded border border-cyan-200 py-1 text-xs" min="1" type="number" value={upgrade.hand_size_bonus || 1} onChange={(event) => onUpdateUpgrade(index, { hand_size_bonus: Number(event.target.value) })} />
                      <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemoveUpgrade(index)} type="button">Remove</button>
                    </div>
                  ))}
                  {(draft.hand_size_upgrades || []).length === 0 ? <p className="text-xs text-slate-500">No hand-size upgrades.</p> : null}
                </div>
              </div>
          </div>
          <div className="xl:grid-cols-[18rem_22rem] space-y-3">
            <PlayerBoardPreview board={draft} eventsById={eventsById} interactionsById={interactionsById} />
          </div>
        </div>
      ) : null}
    </section>
  );
};

const InteractionChecklist = ({ title, field, interactions, selected = [], onToggle }) => (
  <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
    <p className="mb-2 text-sm font-medium text-teal-950">{title}</p>
    <div className="space-y-2">
      {interactions.map((interaction) => (
        <label className="flex items-center gap-2 text-sm text-slate-700" key={interaction.id}>
          <input checked={selected.includes(interaction.id)} onChange={() => onToggle(field, interaction.id)} type="checkbox" />
          {interaction.name}
        </label>
      ))}
      {interactions.length === 0 ? <p className="text-xs text-slate-500">Create interactions first.</p> : null}
    </div>
  </div>
);

const EffectEditor = ({ title, field, effects = [], options, onAdd, onUpdate, onRemove }) => (
  <div className="rounded-md border border-cyan-100 bg-white p-3">
    <div className="flex items-center justify-between gap-2">
      <p className="text-sm font-medium text-teal-950">{title}</p>
      <select className="rounded border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs text-slate-700" onChange={(event) => { if (event.target.value) onAdd(field, event.target.value); event.target.value = ""; }} defaultValue="">
        <option value="">Add effect</option>
        {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </div>
    <div className="mt-2 space-y-2">
      {effects.map((effect, index) => {
        const needsAmount = !noAmountEffectTypes.has(effect.type);
        return (
          <div className="flex items-center gap-2 rounded bg-cyan-50 p-2" key={`${effect.type}:${index}`}>
            <select className="min-w-0 flex-1 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={effect.type} onChange={(event) => onUpdate(field, index, { type: event.target.value, amount: noAmountEffectTypes.has(event.target.value) ? null : effect.amount || 1 })}>
              {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            {needsAmount ? <input className="w-16 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" min="1" type="number" value={effect.amount || 1} onChange={(event) => onUpdate(field, index, { amount: Number(event.target.value) })} /> : null}
            <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemove(field, index)} type="button">Remove</button>
          </div>
        );
      })}
      {effects.length === 0 ? <p className="text-xs text-slate-400">No effects.</p> : null}
    </div>
  </div>
);

const TileList = ({ content, eventsById, categoriesById, interactionsById, setTileDraft, deleteItem, busy }) => (
  <div className="grid gap-3 md:grid-cols-2">
    {content.tiles.map((tile) => {
      const event = eventsById[tile.event_id];
      return (
        <article className="rounded-md border border-cyan-200 bg-white p-3 shadow-sm" key={tile.id}>
          <HexTilePreview className="max-w-[13rem]" event={event} interactionsById={interactionsById} tile={tile} />
          <h3 className="mt-3 truncate font-semibold text-teal-950">{tile.name}</h3>
          <p className="text-xs text-slate-500">{event?.name || "Missing event"} - {categoriesById[event?.category_id]?.name || "No category"}</p>
          <p className="mt-3 text-xs text-slate-600">Success: {(tile.interaction_ids || []).map((id) => interactionsById[id]?.name || id).join(", ")}</p>
          <p className="mt-1 text-xs text-slate-600">Counter: {(tile.counter_attack_interaction_ids || []).map((id) => interactionsById[id]?.name || id).join(", ") || "None"}</p>
          <div className="mt-3 flex gap-2">
            <button className={subtleButton} onClick={() => setTileDraft({ ...emptyTile, ...tile })} type="button">Edit</button>
            <button className={dangerButton} disabled={busy} onClick={() => deleteItem(`/api/admin/content/tiles/${tile.id}`, tile.name)} type="button">Delete</button>
          </div>
        </article>
      );
    })}
  </div>
);

const ContentList = ({ title, items, onEdit, onDelete }) => (
  <section className={panel}>
    <h2 className="font-semibold text-teal-950">{title}</h2>
    <div className="mt-3 space-y-2">
      {items.map((item) => (
        <article className="flex items-center gap-3 rounded-md border border-cyan-100 bg-white p-2 shadow-sm" key={item.id}>
          {imageUrl(item) ? <img alt="" className="h-12 w-12 rounded object-cover" src={imageUrl(item)} /> : null}
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-teal-950">{item.name}</h3>
            {item.subtitle ? <p className="text-xs text-slate-500">{item.subtitle}</p> : null}
          </div>
          <button className={subtleButton} onClick={() => onEdit(item)} type="button">Edit</button>
          <button className={dangerButton} onClick={() => onDelete(item)} type="button">Delete</button>
        </article>
      ))}
      {items.length === 0 ? <p className="text-sm text-slate-500">No items yet.</p> : null}
    </div>
  </section>
);

export default AdminContentPage;
