import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BatteryMedium, Brain, CircleCheck, CircleX, Hand, Home, LoaderCircle, MapPin, Moon, Plus, Scale, Shell, Sun, Trash2 } from "lucide-react";
import AdminLevelEditor from "../components/AdminLevelEditor.jsx";
import AdminMapEditor from "../components/AdminMapEditor.jsx";
import HexTilePreview from "../components/HexTilePreview.jsx";
import CardPreview from "../components/CardPreview.jsx";
import PlayerBoardPreview from "../components/PlayerBoardPreview.jsx";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const adminSubnavItems = [
  { label: "Backoffice", to: "/admin" },
  { label: "Game content", to: "/admin/content" },
  { label: "Game analytics", to: "/admin/analytics" },
];

const emptyInteraction = { id: "", name: "", image_url: "" };
const emptyEvent = { id: "", name: "", category_id: "", image_url: "" };
const emptyTile = {
  id: "",
  name: "",
  event_id: "",
  priority: 0,
  shell_requirement_count: 0,
  interaction_ids: [],
  counter_attack_interaction_ids: [],
  success_effects: [],
  counter_attack_effects: [],
  failure_effects: [],
};
const emptySurpriseCard = { id: "", name: "", image_url: "", costs: [], effects: [] };
const emptySurpriseDeck = { id: "", name: "", card_ids: [] };
const emptyCourtshipCard = { id: "", name: "", image_url: "", interaction_ids: [] };
const emptyPlayerBoard = {
  id: "",
  name: "",
  initiates_event_ids: [],
  deck: [],
  default_max_cards_in_hand: 3,
  hand_size_upgrades: [],
  actions_per_control: 3,
  control_takes_per_night: 3,
  initial_ap: 5,
};

const successEffectOptions = [
  ["gain_energy", "Gain energy"],
  ["gain_neurons", "Gain neurons"],
  ["gain_seashells", "Gain seashells"],
  ["place_shelter_token", "Place shelter token"],
  ["draw_surprise_card", "Draw surprise card"],
];

const failureEffectOptions = [
  ["lose_energy", "Lose energy"],
  ["lose_neurons", "Lose neurons"],
  ["lose_seashells", "Lose seashells"],
  ["lose_ap", "Lose AP"],
  ["lose_half_ap", "Lose half AP"],
  ["lose_all_ap", "Lose all AP"],
  ["pulpita_move_previous", "Poulpita moves to previous node"],
  ["pulpita_move_free", "Poulpita must move for free"],
  ["keep_tile", "Keep tile"],
  ["remove_tile", "Remove tile"],
  ["move_tile_previous", "Move tile to previous node"],
  ["remove_preys", "Remove tiles by category"],
];
const noAmountEffectTypes = new Set(["place_shelter_token", "draw_surprise_card", "lose_half_ap", "lose_all_ap", "pulpita_move_previous", "pulpita_move_free", "keep_tile", "remove_tile", "move_tile_previous", "remove_preys"]);

const surpriseCostOptions = [
  ["play_cards", "Play cards"],
  ["pay_ap", "Pay AP"],
];
const surpriseEffectOptions = [
  ["gain_ap", "Gain AP"],
  ["gain_neurons", "Gain neurons"],
  ["advance_night", "Advance night"],
  ["gain_energy", "Gain energy"],
  ["lose_energy", "Lose energy"],
  ["remove_tiles_category_here", "Remove category here"],
  ["remove_tiles_category_adjacent", "Remove category adjacent"],
];

const contentTabs = [
  ["map", "Map"],
  ["levels", "Levels"],
  ["categories", "Categories"],
  ["interactions", "Interactions"],
  ["events", "Events/Animals"],
  ["tiles", "Tiles"],
  ["cards", "Cards"],
  ["action_costs", "Action Costs"],
  ["bot_settings", "Bot"],
  ["bot_simulations", "Bot Simulations"],
  ["surprise_cards", "Surprise Cards"],
  ["surprise_decks", "Surprise Decks"],
  ["courtship_cards", "Courtship Cards"],
  ["player_boards", "Player Boards"],
  ["tokens", "Tokens"],
  ["poulpita_panel", "Poulpita Panel"],
];

const imageUrl = (entry) => (entry?.image_url ? buildApiUrl(entry.image_url) : "");
const panel = "rounded-lg border border-cyan-200 bg-white/90 p-4 shadow-sm";
const input = "w-full rounded-md border border-cyan-200 bg-white px-3 py-2 text-slate-800 outline-none focus:border-teal-500";
const subtleButton = "rounded-md border border-cyan-300 bg-white px-3 py-2 text-sm text-teal-900 hover:bg-cyan-50";
const primaryButton = "rounded-md bg-teal-500 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-60";
const dangerButton = "rounded-md border border-rose-300 bg-white px-3 py-2 text-sm text-rose-700 hover:bg-rose-50";
const importSummaryLabels = {
  maps: "Maps",
  categories: "Categories",
  interactions: "Interactions",
  events: "Events/Animals",
  tiles: "Tiles",
  levels: "Levels",
  surprise_cards: "Surprise Cards",
  surprise_decks: "Surprise Decks",
  courtship_cards: "Courtship Cards",
  player_boards: "Player Boards",
  tokens: "Tokens",
  action_costs: "Action Costs",
  bot_settings: "Bot Settings",
  poulpita_panel: "Poulpita Panel",
};

const actionCostLabels = {
  gain_ap: "Gain AP",
  move: "Move",
  draw: "Draw action card",
  interact: "Interact",
  special_power: "Use special power",
};

const defaultActionCosts = {
  gain_ap: { ap_cost: 0, time_cost: 0, neuron_cost: 0 },
  move: { ap_cost: 1, time_cost: 1, neuron_cost: 0 },
  draw: { ap_cost: 1, time_cost: 1, neuron_cost: 0 },
  interact: { ap_cost: 2, time_cost: 2, neuron_cost: 0 },
  special_power: { ap_cost: 2, time_cost: 2, neuron_cost: 1 },
};

const botAbilityOptions = [
  ["agility", "Agility"],
  ["camouflage", "Camouflage"],
  ["force", "Force"],
  ["propulsion", "Propulsion"],
  ["intelligence", "Intelligence"],
];

const defaultBotSettings = {
  expected_ap_roll: 3,
  planning_depth_take_controls: 3,
  orchestrator_rollout_take_controls: 3,
  orchestrator_rollouts_per_plan: 3,
  orchestrator_sampling_temperature: 1,
  orchestrator_max_candidates: 8,
  max_plans: 3,
  min_energy_after_size_upgrade: 4,
  special_power_start_night: 4,
  weights: {
    efficiency: 35,
    confidence: 35,
    expected_gain: 30,
    tile_resolution: 14,
    compulsory_tile_resolution: 35,
    third_ability_penalty: 45,
    late_shelter_urgency: 8,
    information_gain: 6,
    immediate_backtrack_penalty: 24,
    unavailable_compulsory_penalty: 20,
  },
  resource_weights: {
    energy: 8,
    neurons: 5,
    seashells: 4,
    ap: 1,
    shelters: 18,
    surprise_cards: 6,
    removed_tiles: 3,
  },
  ability_colors: {
    agility: "#0ea5e9",
    camouflage: "#16a34a",
    force: "#dc2626",
    propulsion: "#7c3aed",
    intelligence: "#f59e0b",
  },
};

const botPlannerWeightLabels = {
  efficiency: "Efficiency",
  confidence: "Confidence",
  expected_gain: "Expected gain",
  tile_resolution: "Resolve a tile",
  compulsory_tile_resolution: "Resolve a compulsory tile",
  third_ability_penalty: "Third ability penalty",
  late_shelter_urgency: "Late-night shelter urgency",
  information_gain: "Unrevealed tile information gain",
  immediate_backtrack_penalty: "Immediate backtrack penalty",
  unavailable_compulsory_penalty: "Unavailable compulsory failure penalty",
};

const botResourceWeightLabels = {
  energy: "Energy",
  neurons: "Neurons",
  seashells: "Seashells",
  ap: "Action points",
  shelters: "Shelters",
  surprise_cards: "Surprise cards",
  removed_tiles: "Removed tiles",
};

const formatImportSummary = (result) => {
  const created = result?.content?.created || {};
  const updated = result?.content?.updated || {};
  const entries = [];
  if (result?.maps) {
    entries.push(`${importSummaryLabels.maps}: ${Number(result.maps.created || 0)} created, ${Number(result.maps.updated || 0)} updated`);
  }
  Object.entries(importSummaryLabels).forEach(([key, label]) => {
    if (key === "maps") return;
    if (created[key] === undefined && updated[key] === undefined) return;
    entries.push(`${label}: ${Number(created[key] || 0)} created, ${Number(updated[key] || 0)} updated`);
  });
  return entries.length ? `Imported content. ${entries.join("; ")}.` : "Imported content.";
};

const AdminContentPage = () => {
  const { token, user } = useStore();
  const [content, setContent] = useState({ categories: [], card_categories: [], interactions: [], events: [], tiles: [], levels: [], surprise_cards: [], surprise_decks: [], courtship_cards: [], player_boards: [], tokens: [], poulpita_panel: null, action_costs: defaultActionCosts, bot_settings: defaultBotSettings, cards: [] });
  const [categoryName, setCategoryName] = useState("");
  const [categoryCompulsory, setCategoryCompulsory] = useState(false);
  const [interactionDraft, setInteractionDraft] = useState(emptyInteraction);
  const [eventDraft, setEventDraft] = useState(emptyEvent);
  const [tileDraft, setTileDraft] = useState(emptyTile);
  const [surpriseCardDraft, setSurpriseCardDraft] = useState(emptySurpriseCard);
  const [surpriseDeckDraft, setSurpriseDeckDraft] = useState(emptySurpriseDeck);
  const [courtshipCardDraft, setCourtshipCardDraft] = useState(emptyCourtshipCard);
  const [playerBoardDraft, setPlayerBoardDraft] = useState(emptyPlayerBoard);
  const [poulpitaPanelDraft, setPoulpitaPanelDraft] = useState(null);
  const [poulpitaPanelPreviewUrl, setPoulpitaPanelPreviewUrl] = useState("");
  const [activeTab, setActiveTab] = useState(() => {
    const requestedTab = window.location.hash.replace(/^#/, "");
    return contentTabs.some(([id]) => id === requestedTab) ? requestedTab : "map";
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const interactionImageRef = useRef(null);
  const eventImageRef = useRef(null);
  const tokenImageRefs = useRef({});
  const surpriseCardImageRef = useRef(null);
  const courtshipCardImageRef = useRef(null);
  const poulpitaPanelImageRef = useRef(null);
  const importFileRef = useRef(null);

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

  const exportContentPackage = async () => {
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(buildApiUrl("/api/admin/content/package"), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Failed to export content.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `maviedepoulpe-admin-content-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setError(exportError.message || "Failed to export content.");
    } finally {
      setBusy(false);
    }
  };

  const importContentPackage = async (file) => {
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = JSON.parse(await file.text());
      const result = await request("/api/admin/content/package/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadContent();
      setNotice(formatImportSummary(result));
    } catch (importError) {
      setError(importError.message || "Failed to import content.");
    } finally {
      setBusy(false);
      if (importFileRef.current) importFileRef.current.value = "";
    }
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

  useEffect(() => {
    setPoulpitaPanelDraft(content.poulpita_panel || null);
  }, [content.poulpita_panel]);

  useEffect(() => () => {
    if (poulpitaPanelPreviewUrl) URL.revokeObjectURL(poulpitaPanelPreviewUrl);
  }, [poulpitaPanelPreviewUrl]);

  const resetInteraction = () => {
    setInteractionDraft(emptyInteraction);
    if (interactionImageRef.current) interactionImageRef.current.value = "";
  };
  const resetEvent = () => {
    setEventDraft(emptyEvent);
    if (eventImageRef.current) eventImageRef.current.value = "";
  };
  const resetTile = () => setTileDraft(emptyTile);
  const resetSurpriseCard = () => {
    setSurpriseCardDraft(emptySurpriseCard);
    if (surpriseCardImageRef.current) surpriseCardImageRef.current.value = "";
  };
  const resetSurpriseDeck = () => setSurpriseDeckDraft(emptySurpriseDeck);
  const resetCourtshipCard = () => {
    setCourtshipCardDraft(emptyCourtshipCard);
    if (courtshipCardImageRef.current) courtshipCardImageRef.current.value = "";
  };

  const saveCategory = async (category = null) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", category ? category.name : categoryName);
      form.set("compulsory_on_same_node", String(category ? Boolean(category.compulsory_on_same_node) : categoryCompulsory));
      await request(category ? `/api/admin/content/categories/${category.id}` : "/api/admin/content/categories", {
        method: category ? "PUT" : "POST",
        body: form,
      });
      setCategoryName("");
      setCategoryCompulsory(false);
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
      form.set("priority", String(Number(tileDraft.priority || 0)));
      form.set("shell_requirement_count", String(Math.max(0, Number(tileDraft.shell_requirement_count || 0))));
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

  const saveSurpriseCard = async () => {
    setBusy(true);
    setError("");
    try {
      const file = surpriseCardImageRef.current?.files?.[0] || null;
      const form = new FormData();
      form.set("name", surpriseCardDraft.name);
      form.set("costs_json", JSON.stringify(surpriseCardDraft.costs || []));
      form.set("effects_json", JSON.stringify(surpriseCardDraft.effects || []));
      if (file) form.set("image", file);
      await request(surpriseCardDraft.id ? `/api/admin/content/surprise-cards/${surpriseCardDraft.id}` : "/api/admin/content/surprise-cards", {
        method: surpriseCardDraft.id ? "PUT" : "POST",
        body: form,
      });
      resetSurpriseCard();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save surprise card.");
    } finally {
      setBusy(false);
    }
  };

  const saveSurpriseDeck = async () => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", surpriseDeckDraft.name);
      form.set("card_ids_json", JSON.stringify(surpriseDeckDraft.card_ids || []));
      await request(surpriseDeckDraft.id ? `/api/admin/content/surprise-decks/${surpriseDeckDraft.id}` : "/api/admin/content/surprise-decks", {
        method: surpriseDeckDraft.id ? "PUT" : "POST",
        body: form,
      });
      resetSurpriseDeck();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save surprise deck.");
    } finally {
      setBusy(false);
    }
  };

  const saveCourtshipCard = async () => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("name", courtshipCardDraft.name);
      form.set("interaction_ids_json", JSON.stringify(courtshipCardDraft.interaction_ids || []));
      const file = courtshipCardImageRef.current?.files?.[0] || null;
      if (file) form.set("image", file);
      await request(courtshipCardDraft.id ? `/api/admin/content/courtship-cards/${courtshipCardDraft.id}` : "/api/admin/content/courtship-cards", {
        method: courtshipCardDraft.id ? "PUT" : "POST",
        body: form,
      });
      resetCourtshipCard();
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save courtship card.");
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
      form.set("initial_ap", String(Math.max(0, Number(playerBoardDraft.initial_ap ?? 5))));
      await request(`/api/admin/content/player-boards/${playerBoardDraft.id}`, { method: "PUT", body: form });
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save player board.");
    } finally {
      setBusy(false);
    }
  };

  const saveActionCosts = async (actionCosts) => {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("action_costs_json", JSON.stringify(actionCosts || {}));
      await request("/api/admin/content/action-costs", { method: "PUT", body: form });
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save action costs.");
    } finally {
      setBusy(false);
    }
  };

  const saveBotSettings = async (botSettings) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.set("bot_settings_json", JSON.stringify(botSettings || {}));
      await request("/api/admin/content/bot-settings", { method: "PUT", body: form });
      setNotice("Bot settings saved.");
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save bot settings.");
    } finally {
      setBusy(false);
    }
  };

  const saveToken = async (tokenId, tokenConfig = {}) => {
    setBusy(true);
    setError("");
    try {
      const file = tokenImageRefs.current[tokenId]?.files?.[0] || null;
      const form = new FormData();
      if (file) form.set("image", file);
      if (tokenId === "octopus") {
        form.set("priority", String(Number(tokenConfig.priority || 0)));
        form.set("initiator_capability_ids_json", JSON.stringify(tokenConfig.initiator_capability_ids || []));
        form.set("interaction_ids_json", JSON.stringify(tokenConfig.interaction_ids || []));
        form.set("counter_attack_interaction_ids_json", JSON.stringify(tokenConfig.counter_attack_interaction_ids || []));
        form.set("success_effects_json", JSON.stringify(tokenConfig.success_effects || []));
        form.set("counter_attack_effects_json", JSON.stringify(tokenConfig.counter_attack_effects || []));
        form.set("failure_effects_json", JSON.stringify(tokenConfig.failure_effects || []));
      }
      await request(`/api/admin/content/tokens/${tokenId}`, { method: "PUT", body: form });
      if (tokenImageRefs.current[tokenId]) tokenImageRefs.current[tokenId].value = "";
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save token.");
    } finally {
      setBusy(false);
    }
  };

  const savePoulpitaPanel = async () => {
    if (!poulpitaPanelDraft) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("zones_json", JSON.stringify(poulpitaPanelDraft.zones || {}));
      form.set("ap_die_sides_json", JSON.stringify(poulpitaPanelDraft.ap_die_sides?.length ? poulpitaPanelDraft.ap_die_sides : [1, 2, 3, 4, 5, 6]));
      const sizeImageIndices = [];
      const serializedSizes = (poulpitaPanelDraft.sizes || []).map((size, index) => {
        const { _image_file, _preview_url, image_url, uses_previous_image, ...persistedSize } = size;
        if (_image_file) {
          sizeImageIndices.push(index);
          form.append("size_images", _image_file);
        }
        return persistedSize;
      });
      form.set("sizes_json", JSON.stringify(serializedSizes));
      form.set("size_image_indices_json", JSON.stringify(sizeImageIndices));
      if (poulpitaPanelDraft.image_width) form.set("image_width", String(poulpitaPanelDraft.image_width));
      if (poulpitaPanelDraft.image_height) form.set("image_height", String(poulpitaPanelDraft.image_height));
      const file = poulpitaPanelImageRef.current?.files?.[0] || null;
      if (file) form.set("image", file);
      await request("/api/admin/content/poulpita-panel", { method: "PUT", body: form });
      if (poulpitaPanelImageRef.current) poulpitaPanelImageRef.current.value = "";
      if (poulpitaPanelPreviewUrl) URL.revokeObjectURL(poulpitaPanelPreviewUrl);
      for (const size of poulpitaPanelDraft.sizes || []) {
        if (size._preview_url) URL.revokeObjectURL(size._preview_url);
      }
      setPoulpitaPanelPreviewUrl("");
      await loadContent();
    } catch (saveError) {
      setError(saveError.message || "Failed to save Poulpita panel.");
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
    setTileDraft((current) => ({
      ...current,
      [field]: [
        ...(current[field] || []),
        {
          type,
          amount: noAmountEffectTypes.has(type) ? null : 1,
          ...(type === "remove_preys" ? { category_id: content.categories?.[0]?.id || "" } : {}),
        },
      ],
    }));
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

  const addSurpriseCost = (type) => {
    setSurpriseCardDraft((current) => ({
      ...current,
      costs: [
        ...(current.costs || []),
        type === "play_cards"
          ? { type, interaction_ids: [content.interactions?.[0]?.id].filter(Boolean) }
          : { type, amount: 1, capability_id: "" },
      ],
    }));
  };

  const updateSurpriseCost = (index, patch) => {
    setSurpriseCardDraft((current) => ({
      ...current,
      costs: (current.costs || []).map((cost, costIndex) => (costIndex === index ? { ...cost, ...patch } : cost)),
    }));
  };

  const removeSurpriseCost = (index) => {
    setSurpriseCardDraft((current) => ({ ...current, costs: (current.costs || []).filter((_cost, costIndex) => costIndex !== index) }));
  };

  const addSurpriseEffect = (type) => {
    setSurpriseCardDraft((current) => ({
      ...current,
      effects: [
        ...(current.effects || []),
        {
          type,
          amount: ["gain_ap", "gain_neurons", "advance_night", "gain_energy", "lose_energy"].includes(type) ? 1 : undefined,
          capability_id: type === "gain_ap" ? "agility" : undefined,
          category_id: type.startsWith("remove_tiles_category") ? content.categories?.[0]?.id || "" : undefined,
        },
      ],
    }));
  };

  const updateSurpriseEffect = (index, patch) => {
    setSurpriseCardDraft((current) => ({
      ...current,
      effects: (current.effects || []).map((effect, effectIndex) => (effectIndex === index ? { ...effect, ...patch } : effect)),
    }));
  };

  const removeSurpriseEffect = (index) => {
    setSurpriseCardDraft((current) => ({ ...current, effects: (current.effects || []).filter((_effect, effectIndex) => effectIndex !== index) }));
  };

  const setSurpriseDeckCardCount = (cardId, count) => {
    setSurpriseDeckDraft((current) => {
      const cardIds = (current.card_ids || []).filter((id) => id !== cardId);
      for (let index = 0; index < Math.max(0, Number(count || 0)); index += 1) cardIds.push(cardId);
      return { ...current, card_ids: cardIds };
    });
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
      hand_size_upgrades: [...(current.hand_size_upgrades || []), { type: "hand_size", cost_resource: "neurons", cost: 1, hand_size_bonus: 1 }],
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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-teal-950">Game Content</h1>
            <p className="mt-1 text-sm text-teal-800">Design interaction symbols, event tiles, counter-attacks, effects, and generated cards.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className={subtleButton} disabled={busy} onClick={exportContentPackage} type="button">Export JSON</button>
            <label className={`${subtleButton} cursor-pointer ${busy ? "opacity-60" : ""}`}>
              Import JSON
              <input
                ref={importFileRef}
                className="hidden"
                disabled={busy}
                type="file"
                accept="application/json,.json"
                onChange={(event) => void importContentPackage(event.target.files?.[0] || null)}
              />
            </label>
          </div>
        </div>
      </div>

      {error ? <p className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
      {notice ? <p className="mb-4 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-800">{notice}</p> : null}

      <nav className="mb-4 flex flex-wrap gap-2">
        {contentTabs.map(([id, label]) => (
          <button className={`rounded-md px-3 py-2 text-sm font-medium ${activeTab === id ? "bg-teal-500 text-white" : "border border-cyan-300 bg-white text-teal-900 hover:bg-cyan-50"}`} key={id} onClick={() => { setActiveTab(id); window.history.replaceState(null, "", `#${id}`); }} type="button">
            {label}
          </button>
        ))}
      </nav>

      {activeTab === "map" ? <AdminMapEditor busy={busy} request={request} setBusy={setBusy} setError={setError} /> : null}

      {activeTab === "levels" ? <AdminLevelEditor busy={busy} content={content} onReload={loadContent} request={request} setBusy={setBusy} setError={setError} /> : null}

      {activeTab === "categories" ? (
        <CategoryEditor
          busy={busy}
          categoryCompulsory={categoryCompulsory}
          categoryName={categoryName}
          content={content}
          deleteItem={deleteItem}
          saveCategory={saveCategory}
          setCategoryCompulsory={setCategoryCompulsory}
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

      {activeTab === "action_costs" ? (
        <ActionCostEditor
          actionCosts={content.action_costs || defaultActionCosts}
          busy={busy}
          onSave={saveActionCosts}
        />
      ) : null}

      {activeTab === "bot_settings" ? (
        <BotSettingsEditor
          botSettings={content.bot_settings || defaultBotSettings}
          busy={busy}
          onSave={saveBotSettings}
        />
      ) : null}

      {activeTab === "surprise_cards" ? (
        <SurpriseCardEditor
          busy={busy}
          categories={content.categories}
          deleteItem={deleteItem}
          draft={surpriseCardDraft}
          imageRef={surpriseCardImageRef}
          interactions={content.interactions}
          onAddCost={addSurpriseCost}
          onAddEffect={addSurpriseEffect}
          onRemoveCost={removeSurpriseCost}
          onRemoveEffect={removeSurpriseEffect}
          onUpdateCost={updateSurpriseCost}
          onUpdateEffect={updateSurpriseEffect}
          reset={resetSurpriseCard}
          save={saveSurpriseCard}
          setDraft={setSurpriseCardDraft}
          surpriseCards={content.surprise_cards || []}
        />
      ) : null}

      {activeTab === "surprise_decks" ? (
        <SurpriseDeckEditor
          busy={busy}
          deleteItem={deleteItem}
          draft={surpriseDeckDraft}
          onSetCardCount={setSurpriseDeckCardCount}
          reset={resetSurpriseDeck}
          save={saveSurpriseDeck}
          setDraft={setSurpriseDeckDraft}
          surpriseCards={content.surprise_cards || []}
          surpriseDecks={content.surprise_decks || []}
        />
      ) : null}

      {activeTab === "bot_simulations" ? (
        <BotSimulationsAdmin levels={content.levels || []} request={request} />
      ) : null}

      {activeTab === "courtship_cards" ? (
        <CourtshipCardEditor
          busy={busy}
          cards={content.courtship_cards || []}
          deleteItem={deleteItem}
          draft={courtshipCardDraft}
          imageRef={courtshipCardImageRef}
          interactions={content.interactions || []}
          reset={resetCourtshipCard}
          save={saveCourtshipCard}
          setDraft={setCourtshipCardDraft}
        />
      ) : null}

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

      {activeTab === "tokens" ? (
        <TokenEditor
          busy={busy}
          content={content}
          tokenImageRefs={tokenImageRefs}
          tokens={content.tokens || []}
          onSave={saveToken}
        />
      ) : null}

      {activeTab === "poulpita_panel" && poulpitaPanelDraft ? (
        <PoulpitaPanelEditor
          busy={busy}
          draft={poulpitaPanelDraft}
          imageRef={poulpitaPanelImageRef}
          previewUrl={poulpitaPanelPreviewUrl}
          save={savePoulpitaPanel}
          setDraft={setPoulpitaPanelDraft}
          setPreviewUrl={setPoulpitaPanelPreviewUrl}
          tokens={content.tokens || []}
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

const CategoryEditor = ({ busy, categoryCompulsory, categoryName, content, deleteItem, saveCategory, setCategoryCompulsory, setCategoryName, setContent }) => (
  <section className={panel}>
    <h2 className="font-semibold text-teal-950">Categories</h2>
    <p className="mt-1 text-xs text-slate-500">Counter-attack is special and does not appear here.</p>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <input className={input} value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="Category name" />
      <label className="flex items-center gap-2 rounded-md border border-cyan-200 bg-white px-3 py-2 text-sm text-teal-950">
        <input checked={categoryCompulsory} onChange={(event) => setCategoryCompulsory(event.target.checked)} type="checkbox" />
        Compulsory on same node
      </label>
      <button className={primaryButton} disabled={busy} onClick={() => saveCategory()} type="button">Add</button>
    </div>
    <div className="mt-3 space-y-2">
      {content.categories.map((category) => (
        <div className="flex items-center gap-2 rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={category.id}>
          <input className="min-w-0 flex-1 bg-transparent text-sm text-teal-950 outline-none" value={category.name} onChange={(event) => setContent((current) => ({ ...current, categories: current.categories.map((item) => item.id === category.id ? { ...item, name: event.target.value } : item) }))} />
          <label className="flex items-center gap-1 text-xs text-teal-900">
            <input checked={Boolean(category.compulsory_on_same_node)} onChange={(event) => setContent((current) => ({ ...current, categories: current.categories.map((item) => item.id === category.id ? { ...item, compulsory_on_same_node: event.target.checked } : item) }))} type="checkbox" />
            Compulsory
          </label>
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
        <label className="block text-sm">
          <span className="text-slate-600">Priority</span>
          <input
            className={`${input} mt-1`}
            min="0"
            step="1"
            type="number"
            value={tileDraft.priority ?? 0}
            onChange={(event) => setTileDraft((current) => ({ ...current, priority: Number(event.target.value || 0) }))}
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-600">Poulpita shells required</span>
          <input
            className={`${input} mt-1`}
            min="0"
            step="1"
            type="number"
            value={tileDraft.shell_requirement_count ?? 0}
            onChange={(event) => setTileDraft((current) => ({ ...current, shell_requirement_count: Math.max(0, Number(event.target.value || 0)) }))}
          />
        </label>
        <InteractionChecklist title="Required to succeed" field="interaction_ids" interactions={content.interactions} selected={tileDraft.interaction_ids} onToggle={toggleTileInteraction} />
        <InteractionChecklist title="Optional counter-attack" field="counter_attack_interaction_ids" interactions={content.interactions} selected={tileDraft.counter_attack_interaction_ids} onToggle={toggleTileInteraction} />
        <EffectEditor title="Success effects" field="success_effects" effects={tileDraft.success_effects} options={successEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
        <EffectEditor title="Counter-attack effects" field="counter_attack_effects" effects={tileDraft.counter_attack_effects} options={successEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
        <EffectEditor categories={content.categories} title="Failure effects" field="failure_effects" effects={tileDraft.failure_effects} options={failureEffectOptions} onAdd={addEffect} onUpdate={updateEffect} onRemove={removeEffect} />
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
        <CardPreview card={card} categories={cardCategories} key={card.id} />
      ))}
      {content.cards.length === 0 ? <p className="text-sm text-slate-500">Create interaction types to generate cards.</p> : null}
    </div>
  </section>
);

const ActionCostEditor = ({ actionCosts, onSave, busy }) => {
  const [draft, setDraft] = useState({ ...defaultActionCosts, ...(actionCosts || {}) });

  useEffect(() => {
    setDraft({ ...defaultActionCosts, ...(actionCosts || {}) });
  }, [actionCosts]);

  const updateCost = (actionId, field, value) => {
    setDraft((current) => ({
      ...current,
      [actionId]: {
        ...(current[actionId] || defaultActionCosts[actionId]),
        [field]: Math.max(0, Number(value || 0)),
      },
    }));
  };

  return (
    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-teal-950">Action Costs</h2>
          <p className="mt-1 text-xs text-slate-500">Time cost is measured in 15-minute night-track steps.</p>
        </div>
        <button className={primaryButton} disabled={busy} onClick={() => onSave(draft)} type="button">Save action costs</button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {Object.entries(actionCostLabels).map(([actionId, label]) => (
          <article className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3" key={actionId}>
            <h3 className="text-sm font-semibold text-teal-950">{label}</h3>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <label className="text-xs text-slate-600">
                AP cost
                <input className={`${input} mt-1`} min="0" type="number" value={Number(draft[actionId]?.ap_cost || 0)} onChange={(event) => updateCost(actionId, "ap_cost", event.target.value)} />
              </label>
              <label className="text-xs text-slate-600">
                Time steps
                <input className={`${input} mt-1`} min="0" type="number" value={Number(draft[actionId]?.time_cost || 0)} onChange={(event) => updateCost(actionId, "time_cost", event.target.value)} />
              </label>
              <label className="text-xs text-slate-600">
                Neurons
                <input className={`${input} mt-1`} min="0" type="number" value={Number(draft[actionId]?.neuron_cost || 0)} onChange={(event) => updateCost(actionId, "neuron_cost", event.target.value)} />
              </label>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
};

const mergeBotSettings = (settings = {}) => ({
  ...defaultBotSettings,
  ...(settings || {}),
  weights: { ...defaultBotSettings.weights, ...((settings || {}).weights || {}) },
  resource_weights: { ...defaultBotSettings.resource_weights, ...((settings || {}).resource_weights || {}) },
  ability_colors: { ...defaultBotSettings.ability_colors, ...((settings || {}).ability_colors || {}) },
});

const BotSettingsEditor = ({ botSettings, onSave, busy }) => {
  const [draft, setDraft] = useState(mergeBotSettings(botSettings));

  useEffect(() => {
    setDraft(mergeBotSettings(botSettings));
  }, [botSettings]);

  const updateNested = (section, key, value) => {
    setDraft((current) => ({
      ...current,
      [section]: {
        ...(current[section] || {}),
        [key]: value,
      },
    }));
  };

  return (
    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-teal-950">Bot Planning</h2>
          <p className="mt-1 text-xs text-slate-500">These values affect bot plan evaluation. Expected AP is derived from the die configured in Poulpita Panel.</p>
        </div>
        <button className={primaryButton} disabled={busy} onClick={() => onSave(draft)} type="button">Save bot settings</button>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Planning depth</span>
          <span className="mt-1 block text-xs text-slate-500">How many take-control windows bots estimate. Default is 3.</span>
          <input
            className={`${input} mt-3`}
            max="8"
            min="1"
            step="1"
            type="number"
            value={Number(draft.planning_depth_take_controls || 3)}
            onChange={(event) => setDraft((current) => ({ ...current, planning_depth_take_controls: Math.max(1, Math.min(20, Number(event.target.value || 3))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Special powers from night</span>
          <span className="mt-1 block text-xs text-slate-500">Bots consider ability powers from this night onward. Default is 4.</span>
          <input
            className={`${input} mt-3`}
            max="20"
            min="1"
            step="1"
            type="number"
            value={Number(draft.special_power_start_night || 4)}
            onChange={(event) => setDraft((current) => ({ ...current, special_power_start_night: Math.max(1, Math.min(20, Number(event.target.value || 4))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Orchestrator horizon</span>
          <span className="mt-1 block text-xs text-slate-500">Simulate through this many future initiative windows. Default is 3.</span>
          <input
            className={`${input} mt-3`}
            max="8"
            min="1"
            step="1"
            type="number"
            value={Number(draft.orchestrator_rollout_take_controls || 3)}
            onChange={(event) => setDraft((current) => ({ ...current, orchestrator_rollout_take_controls: Math.max(1, Math.min(8, Number(event.target.value || 3))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Rollouts per plan</span>
          <span className="mt-1 block text-xs text-slate-500">Number of weighted continuations sampled for every root plan.</span>
          <input
            className={`${input} mt-3`}
            max="12"
            min="1"
            step="1"
            type="number"
            value={Number(draft.orchestrator_rollouts_per_plan || 3)}
            onChange={(event) => setDraft((current) => ({ ...current, orchestrator_rollouts_per_plan: Math.max(1, Math.min(12, Number(event.target.value || 3))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Sampling temperature</span>
          <span className="mt-1 block text-xs text-slate-500">Lower values are greedier; higher values explore more near-optimal plans.</span>
          <input
            className={`${input} mt-3`}
            max="5"
            min="0.1"
            step="0.1"
            type="number"
            value={Number(draft.orchestrator_sampling_temperature || 1)}
            onChange={(event) => setDraft((current) => ({ ...current, orchestrator_sampling_temperature: Math.max(0.1, Math.min(5, Number(event.target.value || 1))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Max local candidates</span>
          <span className="mt-1 block text-xs text-slate-500">Bounds the legal actions evaluated at each simulated decision.</span>
          <input
            className={`${input} mt-3`}
            max="20"
            min="2"
            step="1"
            type="number"
            value={Number(draft.orchestrator_max_candidates || 8)}
            onChange={(event) => setDraft((current) => ({ ...current, orchestrator_max_candidates: Math.max(2, Math.min(20, Number(event.target.value || 8))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Max plans per bot</span>
          <span className="mt-1 block text-xs text-slate-500">Upper bound per proposer after Pareto pruning. Default is 3.</span>
          <input
            className={`${input} mt-3`}
            max="16"
            min="3"
            step="1"
            type="number"
            value={Number(draft.max_plans || 3)}
            onChange={(event) => setDraft((current) => ({ ...current, max_plans: Math.max(1, Math.min(16, Number(event.target.value || 3))) }))}
          />
        </label>
        <label className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3 text-sm">
          <span className="font-semibold text-teal-950">Energy kept after growth</span>
          <span className="mt-1 block text-xs text-slate-500">Bots suggest size growth only if this much energy remains. Default is 4.</span>
          <input
            className={`${input} mt-3`}
            max="31"
            min="1"
            step="1"
            type="number"
            value={Number(draft.min_energy_after_size_upgrade || 4)}
            onChange={(event) => setDraft((current) => ({ ...current, min_energy_after_size_upgrade: Math.max(1, Math.min(31, Number(event.target.value || 4))) }))}
          />
        </label>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="rounded-md border border-cyan-100 bg-white p-3">
          <h3 className="text-sm font-semibold text-teal-950">Pareto scoring weights</h3>
          <div className="mt-3 space-y-2">
            {Object.entries(botPlannerWeightLabels).map(([key, label]) => (
              <label className="grid grid-cols-[1fr_5rem] items-center gap-2 text-xs" key={key}>
                <span className="text-slate-600">{label}</span>
                <input
                  className={input}
                  min="0"
                  step="1"
                  type="number"
                  value={Number(draft.weights?.[key] ?? defaultBotSettings.weights[key])}
                  onChange={(event) => updateNested("weights", key, Math.max(0, Number(event.target.value || 0)))}
                />
              </label>
            ))}
          </div>
        </div>
        <div className="rounded-md border border-cyan-100 bg-white p-3">
          <h3 className="text-sm font-semibold text-teal-950">Expected-gain resource weights</h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            {Object.entries(botResourceWeightLabels).map(([key, label]) => (
              <label className="grid grid-cols-[1fr_5rem] items-center gap-2 text-xs" key={key}>
                <span className="text-slate-600">{label}</span>
                <input
                  className={input}
                  step="0.5"
                  type="number"
                  value={Number(draft.resource_weights?.[key] ?? defaultBotSettings.resource_weights[key])}
                  onChange={(event) => updateNested("resource_weights", key, Number(event.target.value || 0))}
                />
              </label>
            ))}
          </div>
        </div>
        <div className="rounded-md border border-cyan-100 bg-white p-3">
          <h3 className="text-sm font-semibold text-teal-950">Ability colors</h3>
          <div className="mt-3 space-y-2">
            {botAbilityOptions.map(([abilityId, label]) => (
              <label className="grid grid-cols-[1fr_5rem_2.5rem] items-center gap-2 text-xs" key={abilityId}>
                <span className="text-slate-600">{label}</span>
                <input
                  className="h-9 w-full rounded border border-cyan-200 bg-white p-1"
                  type="color"
                  value={draft.ability_colors?.[abilityId] || defaultBotSettings.ability_colors[abilityId]}
                  onChange={(event) => updateNested("ability_colors", abilityId, event.target.value)}
                />
                <span className="h-7 w-7 rounded-full border border-cyan-200" style={{ backgroundColor: draft.ability_colors?.[abilityId] || defaultBotSettings.ability_colors[abilityId] }} />
              </label>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

const abilityOptions = [
  ["", "Any focused ability"],
  ["agility", "Agility"],
  ["camouflage", "Camouflage"],
  ["force", "Force"],
  ["propulsion", "Propulsion"],
  ["intelligence", "Intelligence"],
];

const SurpriseCardEditor = ({
  busy,
  categories,
  deleteItem,
  draft,
  imageRef,
  interactions,
  onAddCost,
  onAddEffect,
  onRemoveCost,
  onRemoveEffect,
  onUpdateCost,
  onUpdateEffect,
  reset,
  save,
  setDraft,
  surpriseCards,
}) => (
  <section className="grid gap-4 xl:grid-cols-[26rem_1fr]">
    <EditorPanel title="Surprise Card">
      <label className="block text-sm">
        <span className="text-slate-600">Name</span>
        <input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
      </label>
      <label className="mt-3 block text-sm">
        <span className="text-slate-600">Image</span>
        <input ref={imageRef} className={`${input} mt-1 text-sm`} type="file" accept="image/png,image/jpeg,image/webp" />
      </label>
      {draft.image_url ? <img alt="" className="mt-3 h-36 rounded border border-cyan-100 object-contain" src={imageUrl(draft)} /> : null}

      <div className="mt-4 rounded-md border border-cyan-100 bg-white p-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-teal-950">Optional costs</h3>
          <select className="rounded border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs" defaultValue="" onChange={(event) => { if (event.target.value) onAddCost(event.target.value); event.target.value = ""; }}>
            <option value="">Add cost</option>
            {surpriseCostOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="mt-2 space-y-2">
          {(draft.costs || []).map((cost, index) => (
            <div className="rounded bg-cyan-50 p-2" key={index}>
              <div className="flex items-center gap-2">
                <select className="min-w-0 flex-1 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={cost.type} onChange={(event) => onUpdateCost(index, { type: event.target.value })}>
                  {surpriseCostOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemoveCost(index)} type="button">Remove</button>
              </div>
              {cost.type === "play_cards" ? (
                <div className="mt-2 grid grid-cols-2 gap-1">
                  {interactions.map((interaction) => (
                    <label className="flex items-center gap-1 text-xs" key={interaction.id}>
                      <input
                        checked={(cost.interaction_ids || []).includes(interaction.id)}
                        onChange={(event) => {
                          const selected = new Set(cost.interaction_ids || []);
                          if (event.target.checked) selected.add(interaction.id);
                          else selected.delete(interaction.id);
                          onUpdateCost(index, { interaction_ids: Array.from(selected) });
                        }}
                        type="checkbox"
                      />
                      {interaction.name}
                    </label>
                  ))}
                </div>
              ) : null}
              {cost.type === "pay_ap" ? (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <input className="rounded border border-cyan-200 bg-white px-2 py-1 text-xs" min="1" type="number" value={cost.amount || 1} onChange={(event) => onUpdateCost(index, { amount: Number(event.target.value) })} />
                  <select className="rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={cost.capability_id || ""} onChange={(event) => onUpdateCost(index, { capability_id: event.target.value })}>
                    {abilityOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
              ) : null}
            </div>
          ))}
          {(draft.costs || []).length === 0 ? <p className="text-xs text-slate-500">No cost: effects happen automatically.</p> : null}
        </div>
      </div>

      <div className="mt-4 rounded-md border border-cyan-100 bg-white p-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-teal-950">Effects</h3>
          <select className="rounded border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs" defaultValue="" onChange={(event) => { if (event.target.value) onAddEffect(event.target.value); event.target.value = ""; }}>
            <option value="">Add effect</option>
            {surpriseEffectOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="mt-2 space-y-2">
          {(draft.effects || []).map((effect, index) => (
            <div className="flex flex-wrap items-center gap-2 rounded bg-cyan-50 p-2" key={index}>
              <select className="min-w-0 flex-1 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={effect.type} onChange={(event) => onUpdateEffect(index, { type: event.target.value })}>
                {surpriseEffectOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
              {["gain_ap", "gain_neurons", "advance_night", "gain_energy", "lose_energy"].includes(effect.type) ? <input className="w-16 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" min="1" type="number" value={effect.amount || 1} onChange={(event) => onUpdateEffect(index, { amount: Number(event.target.value) })} /> : null}
              {effect.type === "gain_ap" ? (
                <select className="w-32 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={effect.capability_id || "agility"} onChange={(event) => onUpdateEffect(index, { capability_id: event.target.value })}>
                  {abilityOptions.filter(([value]) => value).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              ) : null}
              {effect.type?.startsWith("remove_tiles_category") ? (
                <select className="w-36 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={effect.category_id || ""} onChange={(event) => onUpdateEffect(index, { category_id: event.target.value })}>
                  <option value="">Category</option>
                  {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
                </select>
              ) : null}
              <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemoveEffect(index)} type="button">Remove</button>
            </div>
          ))}
          {(draft.effects || []).length === 0 ? <p className="text-xs text-slate-500">No effects.</p> : null}
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button className={primaryButton} disabled={busy} onClick={save} type="button">{draft.id ? "Update" : "Create"}</button>
        <button className={subtleButton} onClick={reset} type="button">Clear</button>
      </div>
    </EditorPanel>

    <section className={panel}>
      <h2 className="font-semibold text-teal-950">Surprise Cards</h2>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {surpriseCards.map((card) => (
          <article className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3" key={card.id}>
            <div className="flex gap-3">
              {imageUrl(card) ? (
                <img alt="" className="h-20 w-14 rounded object-cover" src={imageUrl(card)} />
              ) : (
                <div className="flex h-20 w-14 shrink-0 items-center justify-center rounded border border-dashed border-cyan-300 bg-white text-[10px] font-semibold uppercase text-cyan-700">No image</div>
              )}
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-semibold text-teal-950">{card.name}</h3>
                <p className="text-xs text-slate-500">{(card.costs || []).length} costs - {(card.effects || []).length} effects</p>
                <div className="mt-2 flex gap-2">
                  <button className={subtleButton} onClick={() => setDraft({ ...emptySurpriseCard, ...card })} type="button">Edit</button>
                  <button className={dangerButton} disabled={busy} onClick={() => deleteItem(`/api/admin/content/surprise-cards/${card.id}`, card.name)} type="button">Delete</button>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  </section>
);

const SurpriseDeckEditor = ({ busy, deleteItem, draft, onSetCardCount, reset, save, setDraft, surpriseCards, surpriseDecks }) => {
  const counts = (draft.card_ids || []).reduce((acc, cardId) => ({ ...acc, [cardId]: Number(acc[cardId] || 0) + 1 }), {});
  return (
    <section className="grid gap-4 xl:grid-cols-[26rem_1fr]">
      <EditorPanel title="Surprise Deck">
        <label className="block text-sm">
          <span className="text-slate-600">Name</span>
          <input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
        </label>
        <div className="mt-3 space-y-2">
          {surpriseCards.map((card) => (
            <label className="flex items-center gap-2 rounded bg-cyan-50 p-2 text-sm" key={card.id}>
              {imageUrl(card) ? (
                <img alt="" className="h-10 w-7 rounded object-cover" src={imageUrl(card)} />
              ) : (
                <span className="flex h-10 w-7 shrink-0 items-center justify-center rounded border border-dashed border-cyan-300 bg-white text-[8px] font-semibold uppercase text-cyan-700">No img</span>
              )}
              <span className="min-w-0 flex-1 truncate">{card.name}</span>
              <input className="w-16 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" min="0" type="number" value={counts[card.id] || 0} onChange={(event) => onSetCardCount(card.id, Number(event.target.value))} />
            </label>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          <button className={primaryButton} disabled={busy} onClick={save} type="button">{draft.id ? "Update" : "Create"}</button>
          <button className={subtleButton} onClick={reset} type="button">Clear</button>
        </div>
      </EditorPanel>
      <section className={panel}>
        <h2 className="font-semibold text-teal-950">Surprise Decks</h2>
        <div className="mt-3 space-y-2">
          {surpriseDecks.map((deck) => (
            <div className="flex items-center gap-2 rounded-md border border-cyan-100 bg-cyan-50/70 p-2" key={deck.id}>
              <button className="min-w-0 flex-1 text-left" onClick={() => setDraft({ ...emptySurpriseDeck, ...deck })} type="button">
                <span className="block truncate text-sm font-semibold text-teal-950">{deck.name}</span>
                <span className="text-xs text-slate-500">{(deck.card_ids || []).length} cards</span>
              </button>
              <button className={dangerButton} disabled={busy} onClick={() => deleteItem(`/api/admin/content/surprise-decks/${deck.id}`, deck.name)} type="button">Delete</button>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
};

const CourtshipCardEditor = ({ busy, cards, deleteItem, draft, imageRef, interactions, reset, save, setDraft }) => {
  const addSymbol = () => {
    const interactionId = interactions[0]?.id || "";
    if (interactionId) setDraft((current) => ({ ...current, interaction_ids: [...(current.interaction_ids || []), interactionId] }));
  };
  return (
    <section className="grid gap-4 lg:grid-cols-[24rem_1fr]">
      <div className={panel}>
        <div className="flex items-center justify-between gap-2"><h2 className="font-semibold text-teal-950">Courtship card</h2><button className={subtleButton} onClick={reset} type="button">New</button></div>
        <label className="mt-4 block text-sm text-slate-600">Name<input className={`${input} mt-1`} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
        <label className="mt-3 block text-sm text-slate-600">Image<input accept="image/*" className="mt-1 block w-full text-sm" ref={imageRef} type="file" /></label>
        <div className="mt-4">
          <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-teal-950">Required symbols</h3><button className={subtleButton} onClick={addSymbol} type="button">Add symbol</button></div>
          <div className="mt-2 space-y-2">
            {(draft.interaction_ids || []).map((interactionId, index) => (
              <div className="flex gap-2" key={`${index}-${interactionId}`}>
                <select className={input} value={interactionId} onChange={(event) => setDraft((current) => ({ ...current, interaction_ids: (current.interaction_ids || []).map((value, itemIndex) => itemIndex === index ? event.target.value : value) }))}>{interactions.map((interaction) => <option key={interaction.id} value={interaction.id}>{interaction.name}</option>)}</select>
                <button className={dangerButton} onClick={() => setDraft((current) => ({ ...current, interaction_ids: (current.interaction_ids || []).filter((_value, itemIndex) => itemIndex !== index) }))} type="button">Remove</button>
              </div>
            ))}
          </div>
        </div>
        <button className={`${primaryButton} mt-4 w-full`} disabled={busy || !draft.name || !(draft.interaction_ids || []).length} onClick={save} type="button">{draft.id ? "Update" : "Create"} card</button>
      </div>
      <div className={panel}>
        <h2 className="font-semibold text-teal-950">Courtship cards</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {cards.map((card) => <article className="rounded-md border border-cyan-100 bg-cyan-50/60 p-3" key={card.id}><div className="flex gap-3">{imageUrl(card) ? <img alt="" className="h-20 w-14 rounded object-cover" src={imageUrl(card)} /> : <div className="h-20 w-14 rounded bg-slate-100" />}<div className="min-w-0 flex-1"><h3 className="font-semibold text-teal-950">{card.name}</h3><p className="mt-1 text-xs text-slate-600">{(card.interaction_ids || []).map((id) => interactions.find((entry) => entry.id === id)?.name || id).join(", ")}</p></div></div><div className="mt-3 flex gap-2"><button className={subtleButton} onClick={() => setDraft(card)} type="button">Edit</button><button className={dangerButton} onClick={() => deleteItem(`/api/admin/content/courtship-cards/${card.id}`, card.name)} type="button">Delete</button></div></article>)}
        </div>
      </div>
    </section>
  );
};

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
  const updateUpgradeCardCount = (index, field, interactionId, count) => {
    const upgrade = draft.hand_size_upgrades?.[index] || {};
    const entries = (upgrade[field] || []).filter((entry) => entry.interaction_id !== interactionId);
    if (count > 0) entries.push({ interaction_id: interactionId, count });
    onUpdateUpgrade(index, { [field]: entries });
  };
  const updatePowerfulCard = (index, cardIndex, patch) => {
    const upgrade = draft.hand_size_upgrades?.[index] || {};
    const cards = [...(upgrade.add_cards || [])];
    cards[cardIndex] = { ...(cards[cardIndex] || { interaction_ids: ["", ""], count: 1 }), ...patch };
    onUpdateUpgrade(index, { add_cards: cards });
  };
  const removePowerfulCard = (index, cardIndex) => {
    const upgrade = draft.hand_size_upgrades?.[index] || {};
    onUpdateUpgrade(index, { add_cards: (upgrade.add_cards || []).filter((_, entryIndex) => entryIndex !== cardIndex) });
  };
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
              <label className="block text-sm">
                <span className="text-slate-600">Initial AP</span>
                <input className={`${input} mt-1`} min="0" type="number" value={Number(draft.initial_ap ?? 5)} onChange={(event) => setDraft((current) => ({ ...current, initial_ap: Math.max(0, Number(event.target.value || 0)) }))} />
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
                  <h3 className="text-sm font-semibold text-teal-950">Upgrades</h3>
                  <button className={subtleButton} onClick={onAddUpgrade} type="button">Add</button>
                </div>
                <div className="mt-2 space-y-2">
                  {(draft.hand_size_upgrades || []).map((upgrade, index) => (
                    <div className="space-y-2 rounded bg-cyan-50 p-2" key={index}>
                      <div className="grid grid-cols-[1fr_4rem_auto] gap-1">
                        <select
                          className="rounded border border-cyan-200 bg-white px-2 py-1 text-xs"
                          value={upgrade.type || "hand_size"}
                          onChange={(event) => onUpdateUpgrade(index, event.target.value === "deck_exchange"
                            ? { type: "deck_exchange", cost_resource: "neurons", cost: 1, remove_cards: [], add_cards: [{ interaction_ids: [interactions[0]?.id || "", interactions[1]?.id || interactions[0]?.id || ""], count: 1 }] }
                            : { type: "hand_size", cost_resource: "neurons", cost: 1, hand_size_bonus: 1 })}
                        >
                          <option value="hand_size">Hand size</option>
                          <option value="deck_exchange">Deck exchange</option>
                        </select>
                        <input className="rounded border border-cyan-200 py-1 text-xs" min="1" type="number" value={upgrade.cost || 1} onChange={(event) => onUpdateUpgrade(index, { cost: Number(event.target.value) })} />
                        <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemoveUpgrade(index)} type="button">Remove</button>
                      </div>
                      {(upgrade.type || "hand_size") === "hand_size" ? (
                        <div className="grid grid-cols-[1fr_4rem] gap-1">
                          <select className="rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={upgrade.cost_resource || "neurons"} onChange={(event) => onUpdateUpgrade(index, { cost_resource: event.target.value })}>
                            <option value="neurons">Neurons</option>
                            <option value="energy">Energy</option>
                          </select>
                          <input className="rounded border border-cyan-200 py-1 text-xs" min="1" type="number" value={upgrade.hand_size_bonus || 1} onChange={(event) => onUpdateUpgrade(index, { hand_size_bonus: Number(event.target.value) })} title="Hand size bonus" />
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <div>
                            <p className="text-[0.65rem] font-semibold uppercase text-slate-500">Remove from deck</p>
                            <div className="mt-1 grid grid-cols-2 gap-1">
                              {interactions.map((interaction) => {
                                const removeCount = Number((upgrade.remove_cards || []).find((entry) => entry.interaction_id === interaction.id)?.count || 0);
                                const maxCount = Number(deckByInteraction[interaction.id] || 0);
                                return (
                                  <label className="flex items-center justify-between gap-1 text-[0.65rem] text-slate-700" key={interaction.id}>
                                    <span className="truncate">{interaction.name}</span>
                                    <input className="w-12 rounded border border-cyan-200 px-1 py-0.5" max={maxCount} min="0" type="number" value={removeCount} onChange={(event) => updateUpgradeCardCount(index, "remove_cards", interaction.id, Number(event.target.value))} />
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                          <div>
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[0.65rem] font-semibold uppercase text-slate-500">Add powerful cards</p>
                              <button className="rounded border border-cyan-200 bg-white px-2 py-1 text-[0.65rem] text-teal-800" onClick={() => onUpdateUpgrade(index, { add_cards: [...(upgrade.add_cards || []), { interaction_ids: [interactions[0]?.id || "", interactions[1]?.id || interactions[0]?.id || ""], count: 1 }] })} type="button">Add card</button>
                            </div>
                            <div className="mt-1 space-y-1">
                              {(upgrade.add_cards || []).map((card, cardIndex) => (
                                <div className="grid grid-cols-[1fr_1fr_3rem_auto] gap-1" key={cardIndex}>
                                  {[0, 1].map((slot) => (
                                    <select className="rounded border border-cyan-200 bg-white px-1 py-1 text-[0.65rem]" key={slot} value={card.interaction_ids?.[slot] || ""} onChange={(event) => {
                                      const ids = [...(card.interaction_ids || ["", ""])];
                                      ids[slot] = event.target.value;
                                      updatePowerfulCard(index, cardIndex, { interaction_ids: ids });
                                    }}>
                                      <option value="">Action</option>
                                      {interactions.map((interaction) => <option key={interaction.id} value={interaction.id}>{interaction.name}</option>)}
                                    </select>
                                  ))}
                                  <input className="rounded border border-cyan-200 px-1 py-1 text-[0.65rem]" min="1" type="number" value={card.count || 1} onChange={(event) => updatePowerfulCard(index, cardIndex, { count: Number(event.target.value) })} />
                                  <button className="rounded border border-rose-200 bg-white px-2 py-1 text-[0.65rem] text-rose-700" onClick={() => removePowerfulCard(index, cardIndex)} type="button">X</button>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  {(draft.hand_size_upgrades || []).length === 0 ? <p className="text-xs text-slate-500">No upgrades.</p> : null}
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

const EffectEditor = ({ title, field, effects = [], options, categories = [], onAdd, onUpdate, onRemove }) => (
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
        const needsCategory = effect.type === "remove_preys";
        return (
          <div className="flex items-center gap-2 rounded bg-cyan-50 p-2" key={`${effect.type}:${index}`}>
            <select
              className="min-w-0 flex-1 rounded border border-cyan-200 bg-white px-2 py-1 text-xs"
              value={effect.type}
              onChange={(event) => {
                const nextType = event.target.value;
                onUpdate(field, index, {
                  type: nextType,
                  amount: noAmountEffectTypes.has(nextType) ? null : effect.amount || 1,
                  category_id: nextType === "remove_preys" ? effect.category_id || categories[0]?.id || "" : undefined,
                });
              }}
            >
              {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            {needsAmount ? <input className="w-16 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" min="1" type="number" value={effect.amount || 1} onChange={(event) => onUpdate(field, index, { amount: Number(event.target.value) })} /> : null}
            {needsCategory ? (
              <select className="w-32 rounded border border-cyan-200 bg-white px-2 py-1 text-xs" value={effect.category_id || ""} onChange={(event) => onUpdate(field, index, { category_id: event.target.value })}>
                <option value="">Category</option>
                {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
              </select>
            ) : null}
            <button className="rounded border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700" onClick={() => onRemove(field, index)} type="button">Remove</button>
          </div>
        );
      })}
      {effects.length === 0 ? <p className="text-xs text-slate-400">No effects.</p> : null}
    </div>
  </div>
);

const TokenMark = ({ token, label, className = "" }) => {
  const url = imageUrl(token);
  return (
    <span className={`inline-flex h-7 w-7 items-center justify-center overflow-hidden rounded-full border border-teal-300 bg-white text-[0.55rem] font-bold text-teal-900 shadow-sm ${className}`} title={label || token?.name}>
      {url ? <img alt="" className="h-full w-full object-cover" src={url} /> : (label || token?.name || "?").slice(0, 2)}
    </span>
  );
};

const TokenEditor = ({ tokens, content, tokenImageRefs, onSave, busy }) => {
  const [drafts, setDrafts] = useState({});

  useEffect(() => {
    setDrafts(Object.fromEntries((tokens || []).map((token) => [token.id, {
      priority: Number(token.priority || 0),
      initiator_capability_ids: token.initiator_capability_ids || [],
      interaction_ids: token.interaction_ids || [],
      counter_attack_interaction_ids: token.counter_attack_interaction_ids || [],
      success_effects: token.success_effects || [],
      counter_attack_effects: token.counter_attack_effects || [],
      failure_effects: token.failure_effects || [],
    }])));
  }, [tokens]);

  const setTokenDraft = (tokenId, updater) => {
    setDrafts((current) => {
      const previous = current[tokenId] || {};
      return { ...current, [tokenId]: typeof updater === "function" ? updater(previous) : { ...previous, ...updater } };
    });
  };

  const toggleInteraction = (tokenId, field, interactionId) => {
    setTokenDraft(tokenId, (current) => {
      const selected = new Set(current[field] || []);
      if (selected.has(interactionId)) selected.delete(interactionId);
      else selected.add(interactionId);
      return { ...current, [field]: Array.from(selected) };
    });
  };

  const toggleInitiator = (tokenId, capabilityId) => {
    setTokenDraft(tokenId, (current) => {
      const selected = new Set(current.initiator_capability_ids || []);
      if (selected.has(capabilityId)) selected.delete(capabilityId);
      else selected.add(capabilityId);
      return { ...current, initiator_capability_ids: Array.from(selected) };
    });
  };

  const addEffect = (tokenId, field, type) => {
    setTokenDraft(tokenId, (current) => ({
      ...current,
      [field]: [
        ...(current[field] || []),
        {
          type,
          amount: noAmountEffectTypes.has(type) ? null : 1,
          category_id: type === "remove_preys" ? content.categories?.[0]?.id || "" : undefined,
        },
      ],
    }));
  };

  const updateEffect = (tokenId, field, index, patch) => {
    setTokenDraft(tokenId, (current) => ({
      ...current,
      [field]: (current[field] || []).map((effect, effectIndex) => (effectIndex === index ? { ...effect, ...patch } : effect)),
    }));
  };

  const removeEffect = (tokenId, field, index) => {
    setTokenDraft(tokenId, (current) => ({
      ...current,
      [field]: (current[field] || []).filter((_, effectIndex) => effectIndex !== index),
    }));
  };

  return (
    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {tokens.map((token) => {
        const draft = drafts[token.id] || {};
        return (
          <article className={panel} key={token.id}>
            <div className="flex items-center gap-3">
              <TokenMark token={token} />
              <div>
                <h2 className="font-semibold text-teal-950">{token.name}</h2>
                <p className="text-xs text-slate-500">{token.id}</p>
              </div>
            </div>
            <input ref={(node) => { tokenImageRefs.current[token.id] = node; }} className={`${input} mt-4 text-sm`} type="file" accept="image/png,image/jpeg,image/webp" />
            {token.id === "octopus" ? (
              <div className="mt-4 space-y-3">
                <label className="block text-sm">
                  <span className="text-slate-600">Priority</span>
                  <input className={`${input} mt-1`} min="0" step="1" type="number" value={draft.priority ?? 0} onChange={(event) => setTokenDraft(token.id, { priority: Number(event.target.value || 0) })} />
                </label>
                <div className="rounded-md border border-cyan-100 bg-cyan-50/70 p-3">
                  <h3 className="text-sm font-semibold text-teal-950">Can initiate interaction</h3>
                  <div className="mt-2 space-y-2">
                    {(content.player_boards || []).map((board) => (
                      <label className="flex items-center gap-2 text-sm text-slate-700" key={board.id}>
                        <input checked={(draft.initiator_capability_ids || []).includes(board.id)} onChange={() => toggleInitiator(token.id, board.id)} type="checkbox" />
                        <span className="min-w-0 truncate">{board.name || board.id}</span>
                      </label>
                    ))}
                    {(content.player_boards || []).length === 0 ? <p className="text-xs text-slate-500">Create player boards first.</p> : null}
                  </div>
                </div>
                <InteractionChecklist title="Required to succeed" field="interaction_ids" interactions={content.interactions || []} selected={draft.interaction_ids || []} onToggle={(field, interactionId) => toggleInteraction(token.id, field, interactionId)} />
                <InteractionChecklist title="Optional counter-attack" field="counter_attack_interaction_ids" interactions={content.interactions || []} selected={draft.counter_attack_interaction_ids || []} onToggle={(field, interactionId) => toggleInteraction(token.id, field, interactionId)} />
                <EffectEditor title="Success effects" field="success_effects" effects={draft.success_effects || []} options={successEffectOptions} onAdd={(field, type) => addEffect(token.id, field, type)} onUpdate={(field, index, patch) => updateEffect(token.id, field, index, patch)} onRemove={(field, index) => removeEffect(token.id, field, index)} />
                <EffectEditor title="Counter-attack effects" field="counter_attack_effects" effects={draft.counter_attack_effects || []} options={successEffectOptions} onAdd={(field, type) => addEffect(token.id, field, type)} onUpdate={(field, index, patch) => updateEffect(token.id, field, index, patch)} onRemove={(field, index) => removeEffect(token.id, field, index)} />
                <EffectEditor categories={content.categories || []} title="Failure effects" field="failure_effects" effects={draft.failure_effects || []} options={failureEffectOptions} onAdd={(field, type) => addEffect(token.id, field, type)} onUpdate={(field, index, patch) => updateEffect(token.id, field, index, patch)} onRemove={(field, index) => removeEffect(token.id, field, index)} />
              </div>
            ) : null}
            <button className={`${primaryButton} mt-3`} disabled={busy} onClick={() => onSave(token.id, draft)} type="button">Save token</button>
          </article>
        );
      })}
    </section>
  );
};

const panelZoneLabels = { neurons: "Neurons", seashells: "Shells" };

const PoulpitaPanelEditor = ({ draft, setDraft, imageRef, previewUrl, setPreviewUrl, tokens, save, busy }) => {
  const [selectedZoneId, setSelectedZoneId] = useState("neurons");
  const [dragStart, setDragStart] = useState(null);
  const tokenById = Object.fromEntries((tokens || []).map((token) => [token.id, token]));
  const containerUrl = previewUrl || imageUrl(draft);
  const aspectRatio = draft.image_width && draft.image_height ? `${draft.image_width} / ${draft.image_height}` : "4 / 3";

  const setZone = (zoneId, zone) => {
    setDraft((current) => ({ ...current, zones: { ...(current.zones || {}), [zoneId]: zone } }));
  };

  const pointFromEvent = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    };
  };

  const beginDraw = (event) => {
    if (!containerUrl) return;
    const point = pointFromEvent(event);
    setDragStart(point);
    setZone(selectedZoneId, { x: point.x, y: point.y, width: 0.01, height: 0.01 });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const updateDraw = (event) => {
    if (!dragStart) return;
    const point = pointFromEvent(event);
    setZone(selectedZoneId, {
      x: Math.min(dragStart.x, point.x),
      y: Math.min(dragStart.y, point.y),
      width: Math.max(0.01, Math.abs(point.x - dragStart.x)),
      height: Math.max(0.01, Math.abs(point.y - dragStart.y)),
    });
  };

  const endDraw = () => setDragStart(null);

  const onImageChange = (file) => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (!file) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    const image = new Image();
    image.onload = () => {
      setDraft((current) => ({ ...current, image_width: image.naturalWidth, image_height: image.naturalHeight }));
    };
    image.src = url;
  };

  const sampleCounts = { neurons: 6, seashells: 4 };
  const dieSides = draft.ap_die_sides?.length ? draft.ap_die_sides : [1, 2, 3, 4, 5, 6];
  const updateDieSide = (index, value) => {
    setDraft((current) => ({
      ...current,
      ap_die_sides: (current.ap_die_sides?.length ? current.ap_die_sides : [1, 2, 3, 4, 5, 6])
        .map((side, sideIndex) => sideIndex === index ? Math.max(0, Math.min(99, Number(value || 0))) : side),
    }));
  };
  const addDieSide = () => {
    setDraft((current) => ({
      ...current,
      ap_die_sides: [...(current.ap_die_sides?.length ? current.ap_die_sides : [1, 2, 3, 4, 5, 6]), 1].slice(0, 32),
    }));
  };
  const removeDieSide = (index) => {
    if (dieSides.length <= 1) return;
    setDraft((current) => ({ ...current, ap_die_sides: (current.ap_die_sides || []).filter((_side, sideIndex) => sideIndex !== index) }));
  };
  const sizes = draft.sizes?.length ? draft.sizes : [{ amount: 1, unit: "kg", energy_cost: 0 }];
  const updateSize = (index, patch) => {
    setDraft((current) => ({
      ...current,
      sizes: (current.sizes || [{ amount: 1, unit: "kg", energy_cost: 0 }]).map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch, energy_cost: entryIndex === 0 ? 0 : patch.energy_cost ?? entry.energy_cost } : entry),
    }));
  };
  const addSize = () => {
    setDraft((current) => ({ ...current, sizes: [...(current.sizes || [{ amount: 1, unit: "kg", energy_cost: 0 }]), { amount: 1, unit: "kg", energy_cost: 1, image_filename: null }] }));
  };
  const removeSize = (index) => {
    if (index === 0) return;
    setDraft((current) => {
      const removed = (current.sizes || [])[index];
      if (removed?._preview_url) URL.revokeObjectURL(removed._preview_url);
      return { ...current, sizes: (current.sizes || []).filter((_entry, entryIndex) => entryIndex !== index) };
    });
  };
  const updateSizeImage = (index, file) => {
    setDraft((current) => {
      const nextSizes = [...(current.sizes || [])];
      const previousPreview = nextSizes[index]?._preview_url;
      if (previousPreview) URL.revokeObjectURL(previousPreview);
      nextSizes[index] = {
        ...nextSizes[index],
        _image_file: file || null,
        _preview_url: file ? URL.createObjectURL(file) : "",
      };
      return { ...current, sizes: nextSizes };
    });
  };
  const sizePreviewUrl = (index) => {
    for (let candidate = index; candidate >= 0; candidate -= 1) {
      const size = sizes[candidate];
      const url = size?._preview_url || imageUrl(size);
      if (url) return url;
    }
    return "";
  };
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className={panel}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-teal-950">Poulpita Panel Layout</h2>
            <p className="mt-1 text-xs text-slate-500">Select a zone, then drag over the container image to define where those tokens stack.</p>
          </div>
          <div className="flex gap-2">
            {Object.entries(panelZoneLabels).map(([zoneId, label]) => (
              <button className={`rounded-md px-3 py-2 text-xs font-semibold ${selectedZoneId === zoneId ? "bg-teal-500 text-white" : "border border-cyan-300 bg-white text-teal-900"}`} key={zoneId} onClick={() => setSelectedZoneId(zoneId)} type="button">
                {label}
              </button>
            ))}
          </div>
        </div>
        <div
          className="relative mt-4 mx-auto overflow-hidden rounded-lg border border-cyan-200 bg-cyan-50"
          onPointerDown={beginDraw}
          onPointerMove={updateDraw}
          onPointerUp={endDraw}
          onPointerCancel={endDraw}
          style={{ aspectRatio, maxWidth: draft.image_width || 720 }}
        >
          {containerUrl ? <img alt="Poulpita panel" className="absolute inset-0 h-full w-full select-none object-contain" draggable={false} src={containerUrl} /> : <div className="flex h-full min-h-[22rem] items-center justify-center text-sm text-slate-500">Upload a container image to define token zones.</div>}
          {Object.entries(draft.zones || {}).map(([zoneId, zone]) => (
            <div
              className={`absolute border-2 ${selectedZoneId === zoneId ? "border-teal-500 bg-teal-300/25" : "border-cyan-500 bg-cyan-200/20"}`}
              key={zoneId}
              style={{ left: `${zone.x * 100}%`, top: `${zone.y * 100}%`, width: `${zone.width * 100}%`, height: `${zone.height * 100}%` }}
            >
              <span className="absolute left-1 top-1 rounded bg-white/90 px-1.5 py-0.5 text-[0.62rem] font-semibold text-teal-950">{panelZoneLabels[zoneId]}</span>
              <div className="flex h-full flex-wrap content-start gap-1 p-5">
                {Array.from({ length: sampleCounts[zoneId] || 0 }).map((_, index) => (
                  <TokenMark className="h-5 w-5" key={index} label={panelZoneLabels[zoneId]} token={tokenById[zoneId === "neurons" ? "neuron" : "seashell"]} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <aside className={panel}>
        <h2 className="font-semibold text-teal-950">Container Image</h2>
        <input ref={imageRef} className={`${input} mt-3 text-sm`} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => onImageChange(event.target.files?.[0] || null)} />
        <div className="mt-5 border-t border-cyan-100 pt-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-teal-950">AP die sides</h3>
              <p className="mt-0.5 text-[0.65rem] text-slate-500">Each entry is one equally likely side. Repeat a value to make it more likely.</p>
            </div>
            <button aria-label="Add die side" className={subtleButton} disabled={dieSides.length >= 32} onClick={addDieSide} title="Add die side" type="button">
              <Plus size={15} />
            </button>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {dieSides.map((side, index) => (
              <div className="flex items-center gap-1 rounded border border-cyan-100 bg-cyan-50 p-1.5" key={index}>
                <span className="w-10 text-[0.65rem] font-semibold text-slate-500">Side {index + 1}</span>
                <input aria-label={`Die side ${index + 1} value`} className={`${input} min-w-0 py-1 text-xs`} max="99" min="0" onChange={(event) => updateDieSide(index, event.target.value)} step="1" type="number" value={side} />
                <button aria-label={`Remove die side ${index + 1}`} className="rounded p-1 text-rose-600 hover:bg-rose-50 disabled:opacity-30" disabled={dieSides.length <= 1} onClick={() => removeDieSide(index)} title="Remove die side" type="button">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-teal-950">Size ladder</h3>
            <button className={subtleButton} onClick={addSize} type="button">Add size</button>
          </div>
          <div className="mt-2 space-y-2">
            {sizes.map((size, index) => (
              <div className="rounded border border-cyan-100 bg-cyan-50 p-2" key={index}>
                <div className="mb-2 flex items-center gap-2">
                  <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded border border-cyan-200 bg-white">
                    {sizePreviewUrl(index) ? <img alt={`Poulpita size ${index + 1}`} className="h-full w-full object-contain" src={sizePreviewUrl(index)} /> : <span className="text-[0.65rem] text-rose-600">Image required</span>}
                  </div>
                  <label className="min-w-0 flex-1 text-xs text-slate-600">
                    Poulpita image
                    <input className={`${input} mt-1 py-1 text-xs`} accept="image/png,image/jpeg,image/webp" onChange={(event) => updateSizeImage(index, event.target.files?.[0] || null)} type="file" />
                    <span className="mt-1 block text-[0.62rem] text-slate-500">{index === 0 ? "Required for the initial size." : "Leave empty to use the previous size image."}</span>
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-xs text-slate-600">
                    Amount
                    <input className={`${input} mt-1 py-1 text-xs`} min="0.01" step="0.01" type="number" value={size.amount ?? size.kg ?? 1} onChange={(event) => updateSize(index, { amount: Number(event.target.value || 0) })} />
                  </label>
                  <label className="text-xs text-slate-600">
                    Energy cost
                    <input className={`${input} mt-1 py-1 text-xs`} disabled={index === 0} min="0" step="1" type="number" value={index === 0 ? 0 : size.energy_cost} onChange={(event) => updateSize(index, { energy_cost: Number(event.target.value || 0) })} />
                  </label>
                </div>
                <label className="mt-2 block text-xs text-slate-600">
                  Unit
                  <select className={`${input} mt-1 py-1 text-xs`} value={size.unit || "kg"} onChange={(event) => updateSize(index, { unit: event.target.value })}>
                    <option value="mg">mg</option>
                    <option value="g">g</option>
                    <option value="kg">kg</option>
                  </select>
                </label>
                {index === 0 ? <p className="mt-1 text-[0.65rem] text-slate-500">Initial size has no energy cost.</p> : <button className={`${dangerButton} mt-2 py-1 text-xs`} onClick={() => removeSize(index)} type="button">Remove</button>}
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4 space-y-3 text-xs text-slate-600">
          {Object.entries(draft.zones || {}).map(([zoneId, zone]) => (
            <div className="rounded border border-cyan-100 bg-cyan-50 p-2" key={zoneId}>
              <strong className="text-teal-950">{panelZoneLabels[zoneId]}</strong>
              <p>x {Math.round(zone.x * 100)}%, y {Math.round(zone.y * 100)}%, w {Math.round(zone.width * 100)}%, h {Math.round(zone.height * 100)}%</p>
            </div>
          ))}
        </div>
        <button className={`${primaryButton} mt-4 w-full`} disabled={busy || !sizePreviewUrl(0)} onClick={save} type="button">Save panel layout</button>
      </aside>
    </section>
  );
};

const BotSimulationsAdmin = ({ levels, request }) => {
  const [replays, setReplays] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState({
    level_id: "",
    game_count: 1,
    max_steps: 2000,
    seed: "",
    simulation_mode: "fast",
  });

  useEffect(() => {
    if (!draft.level_id && levels.length) {
      setDraft((current) => ({ ...current, level_id: levels[0].id }));
    }
  }, [draft.level_id, levels]);

  const loadReplays = async () => {
    try {
      const payload = await request("/api/admin/bot-simulations");
      setReplays(payload.replays || []);
      setError("");
    } catch (loadError) {
      setError(loadError.message || "Failed to load bot simulations.");
    }
  };

  useEffect(() => {
    void loadReplays();
  }, []);

  const hasActiveSimulations = replays.some((replay) => ["queued", "running"].includes(replay.status));

  useEffect(() => {
    if (!hasActiveSimulations) return undefined;
    const timer = window.setInterval(() => void loadReplays(), 1000);
    return () => window.clearInterval(timer);
  }, [hasActiveSimulations]);

  const runBatch = async () => {
    if (!draft.level_id) return;
    setRunning(true);
    setError("");
    setNotice("");
    try {
      const payload = await request("/api/admin/bot-simulations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...draft,
          game_count: Number(draft.game_count || 1),
          max_steps: Number(draft.max_steps || 2000),
          seed: draft.seed === "" ? null : Number(draft.seed),
        }),
      });
      const started = payload.replays || [];
      setReplays((current) => {
        const startedIds = new Set(started.map((entry) => entry.id));
        return [...started, ...current.filter((entry) => !startedIds.has(entry.id))];
      });
      setNotice(`${started.length} simulation${started.length === 1 ? "" : "s"} started.`);
    } catch (runError) {
      setError(runError.message || "Bot simulation failed.");
    } finally {
      setRunning(false);
    }
  };

  const deleteReplay = async (replay) => {
    if (!window.confirm(`Delete replay ${replay.id}?`)) return;
    try {
      await request(`/api/admin/bot-simulations/${replay.id}`, { method: "DELETE" });
      setReplays((current) => current.filter((entry) => entry.id !== replay.id));
    } catch (deleteError) {
      setError(deleteError.message || "Failed to delete replay.");
    }
  };

  return (
    <section className="grid gap-4 xl:grid-cols-[22rem_1fr]">
      <aside className={panel}>
        <h2 className="font-semibold text-teal-950">Run backend simulations</h2>
        <div className="mt-4 space-y-3">
          <label className="block text-sm text-slate-600">
            Level
            <select className={`${input} mt-1`} disabled={running} value={draft.level_id} onChange={(event) => setDraft((current) => ({ ...current, level_id: event.target.value }))}>
              {levels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
            </select>
          </label>
          <label className="block text-sm text-slate-600">
            Number of games
            <input className={`${input} mt-1`} disabled={running} max="100" min="1" type="number" value={draft.game_count} onChange={(event) => setDraft((current) => ({ ...current, game_count: Math.max(1, Math.min(100, Number(event.target.value || 1))) }))} />
          </label>
          <label className="block text-sm text-slate-600">
            Maximum steps per game
            <input className={`${input} mt-1`} disabled={running} max="10000" min="10" type="number" value={draft.max_steps} onChange={(event) => setDraft((current) => ({ ...current, max_steps: Math.max(10, Math.min(10000, Number(event.target.value || 2000))) }))} />
          </label>
          <label className="block text-sm text-slate-600">
            Decision mode
            <select className={`${input} mt-1`} disabled={running} value={draft.simulation_mode} onChange={(event) => setDraft((current) => ({ ...current, simulation_mode: event.target.value }))}>
              <option value="fast">Fast immediate heuristic</option>
              <option value="full">Full orchestrator rollouts</option>
            </select>
          </label>
          <label className="block text-sm text-slate-600">
            Base seed (optional)
            <input className={`${input} mt-1`} disabled={running} min="0" type="number" value={draft.seed} onChange={(event) => setDraft((current) => ({ ...current, seed: event.target.value }))} />
          </label>
        </div>
        <button className={`${primaryButton} mt-4 w-full`} disabled={running || !draft.level_id} onClick={() => void runBatch()} type="button">
          {running ? "Simulating..." : "Run simulations"}
        </button>
        {notice ? <p className="mt-3 rounded border border-teal-200 bg-teal-50 p-2 text-sm text-teal-800">{notice}</p> : null}
        {error ? <p className="mt-3 rounded border border-rose-200 bg-rose-50 p-2 text-sm text-rose-700">{error}</p> : null}
      </aside>

      <div className={panel}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold text-teal-950">Saved replays</h2>
          <button className={subtleButton} disabled={running} onClick={() => void loadReplays()} type="button">Refresh</button>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[58rem] text-left text-sm">
            <thead className="border-b border-cyan-200 text-xs uppercase text-slate-500">
              <tr><th className="p-2">Created</th><th className="p-2">Level</th><th className="p-2">Status</th><th className="p-2">Progress</th><th className="p-2">State</th><th className="p-2">Seed</th><th className="p-2" /></tr>
            </thead>
            <tbody>
              {replays.map((replay) => {
                const progress = replay.progress || {};
                const active = ["queued", "running"].includes(replay.status);
                const statusClasses = replay.status === "completed"
                  ? (replay.outcome === "won" ? "bg-emerald-100 text-emerald-800" : replay.outcome === "lost" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800")
                  : replay.status === "failed" ? "bg-rose-100 text-rose-800" : "bg-cyan-100 text-cyan-800";
                const StatusIcon = replay.status === "completed" ? CircleCheck : replay.status === "failed" ? CircleX : LoaderCircle;
                const PhaseIcon = progress.phase === "day" ? Sun : Moon;
                return (
                  <tr className="border-b border-cyan-100 align-middle" key={replay.id}>
                    <td className="p-2 text-xs text-slate-500">{new Date(replay.created_at).toLocaleString()}</td>
                    <td className="p-2 font-medium text-teal-950">{replay.level_name}</td>
                    <td className="p-2">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-semibold ${statusClasses}`}>
                        <StatusIcon className={active ? "animate-spin" : ""} size={13} />
                        {replay.status === "completed" ? replay.outcome : replay.status}
                      </span>
                    </td>
                    <td className="p-2">
                      <div className="min-w-40">
                        <div className="flex items-center justify-between gap-2 text-xs text-slate-600">
                          <span className="inline-flex items-center gap-1"><PhaseIcon size={13} />{progress.phase_label || "Waiting"}</span>
                          <span>{Number(progress.step ?? replay.steps ?? 0)} / {Number(progress.max_steps || replay.steps || 0)}</span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-cyan-100">
                          <div className={`h-full rounded-full ${replay.status === "failed" ? "bg-rose-400" : "bg-teal-500"}`} style={{ width: `${Number(progress.percent ?? (replay.status === "completed" ? 100 : 0))}%` }} />
                        </div>
                        {progress.phase?.startsWith("night") ? <p className="mt-1 text-[11px] text-slate-500">Clock {Number(progress.night_time_spent || 0)} / {Number(progress.night_time_total || 24)}</p> : null}
                        {progress.last_action ? <p className="mt-1 max-w-52 truncate text-[11px] capitalize text-slate-500" title={progress.last_action}>{progress.last_action}</p> : null}
                      </div>
                    </td>
                    <td className="p-2">
                      <div className="flex max-w-64 flex-wrap gap-1 text-xs text-slate-700">
                        <span className="inline-flex items-center gap-1 rounded bg-rose-50 px-1.5 py-1" title="Energy"><BatteryMedium size={13} />{Number(progress.energy ?? replay.final_energy ?? 0)}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-violet-50 px-1.5 py-1" title="Neurons"><Brain size={13} />{Number(progress.neurons || 0)}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-1" title="Shells carried by Poulpita"><Shell size={13} />{Number(progress.seashells || 0)}</span>
                        <span className="inline-flex items-center gap-0.5 rounded bg-emerald-50 px-1.5 py-1" title="Shells stored in shelters"><Home size={13} /><Shell size={10} />{Number(progress.shelter_seashells || 0)}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-sky-50 px-1.5 py-1" title="Poulpita size"><Scale size={13} />{progress.size_label || `Size ${Number(progress.size_index || 0) + 1}`}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-fuchsia-50 px-1.5 py-1" title="Remaining initiatives"><Hand size={13} />{Number(progress.remaining_initiatives || 0)}/{Number(progress.total_initiatives || 0)}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-1" title="Secured shelters / shelters"><Home size={13} />{Number(progress.secured_shelters || 0)}/{Number(progress.shelter_tokens || 0)}</span>
                        <span className="inline-flex items-center gap-1 rounded bg-cyan-50 px-1.5 py-1" title="Current node"><MapPin size={13} />{progress.node_id || "-"}</span>
                      </div>
                    </td>
                    <td className="p-2 text-xs text-slate-600">{replay.seed}</td>
                    <td className="p-2">
                      <div className="flex justify-end gap-2">
                        {replay.status === "completed" ? <Link className={primaryButton} to={`/admin/replays/${replay.id}`}>Replay</Link> : null}
                        <button className={dangerButton} disabled={active} onClick={() => void deleteReplay(replay)} type="button">Delete</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!replays.length ? <p className="py-8 text-center text-sm text-slate-500">No simulations saved.</p> : null}
        </div>
      </div>
    </section>
  );
};

const TileList = ({ content, eventsById, categoriesById, interactionsById, setTileDraft, deleteItem, busy }) => (
  <div className="grid gap-3 md:grid-cols-2">
    {content.tiles.map((tile) => {
      const event = eventsById[tile.event_id];
      return (
        <article className="rounded-md border border-cyan-200 bg-white p-3 shadow-sm" key={tile.id}>
          <HexTilePreview className="max-w-[13rem]" event={event} interactionsById={interactionsById} tile={tile} />
          <h3 className="mt-3 truncate font-semibold text-teal-950">{tile.name}</h3>
          <p className="text-xs text-slate-500">{event?.name || "Missing event"} - {categoriesById[event?.category_id]?.name || "No category"}</p>
          <p className="mt-1 text-xs text-slate-600">Priority: {Number(tile.priority || 0)}</p>
          <p className="mt-3 text-xs text-slate-600">
            Success: {(tile.interaction_ids || []).length ? (tile.interaction_ids || []).map((id) => interactionsById[id]?.name || id).join(", ") : "No cards"}
            {Number(tile.shell_requirement_count || 0) > 0 ? ` + ${tile.shell_requirement_count} shell${Number(tile.shell_requirement_count || 0) === 1 ? "" : "s"}` : ""}
          </p>
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
