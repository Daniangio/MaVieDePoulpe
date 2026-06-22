import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import BoardView from "../components/BoardView";
import HexTilePreview from "../components/HexTilePreview.jsx";
import { useStore } from "../store.js";
import type { CapabilityProjection, CardProjection, CommandRejection, GameProjection, NodeId } from "../types/game";
import { buildApiUrl, buildWsUrl } from "../utils/connection.js";

const makeCommandId = () =>
  globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `cmd_${Date.now()}_${Math.random()}`;

const phaseLabel = (projection: GameProjection | null) => {
  if (!projection) return "Loading";
  if (projection.phase === "setup") return "Setup";
  if (projection.phase === "game_over") return "Game over";
  return `Night ${projection.day_index || 1}`;
};

const CapabilityBoard = ({
  capability,
  active,
  focused,
  compact,
  pending,
  projection,
  moveMode,
  onFocus,
  onTakeControl,
  onCollect,
  onDraw,
  onMoveMode,
}: {
  capability: CapabilityProjection;
  active: boolean;
  focused: boolean;
  compact?: boolean;
  pending: boolean;
  projection: GameProjection | null;
  moveMode: boolean;
  onFocus?: () => void;
  onTakeControl?: () => void;
  onCollect?: () => void;
  onDraw?: () => void;
  onMoveMode?: () => void;
}) => {
  const initiableEvents = (capability.initiates_event_ids || [])
    .map((eventId) => projection?.tile_catalog?.events?.[eventId])
    .filter(Boolean);
  return (
  <article
    className={[
      "group relative min-w-0 rounded-md border bg-slate-900 text-slate-100 shadow-xl transition",
      active ? "border-teal-300" : focused ? "border-amber-300" : "border-slate-700",
      compact ? "h-full p-2 hover:z-40 hover:h-52 hover:bg-slate-900" : "h-full p-3",
    ].join(" ")}
    onDoubleClick={onFocus}
  >
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <h3 className="truncate text-sm font-semibold text-white">{capability.name}</h3>
        <p className="text-xs text-slate-400">{active ? "Controls Poulpita" : focused ? "In focus" : "Waiting"}</p>
      </div>
      <div className="rounded bg-slate-800 px-2 py-1 text-xs font-semibold text-black-100">{capability.pa} AP</div>
    </div>
    <div className={compact ? "mt-2 grid grid-cols-[1fr_auto] gap-2" : "mt-3 grid grid-cols-[1fr_7rem] gap-3"}>
      <div className={compact ? "grid grid-cols-2 gap-2 text-xs" : "grid grid-cols-3 gap-2 text-xs"}>
        <div className="rounded bg-slate-800 p-2">
          <span className="block text-slate-400">Control</span>
          <strong>
            {capability.control_takes_this_night}/{capability.max_control_takes_per_night}
          </strong>
        </div>
        <div className="rounded bg-slate-800 p-2">
          <span className="block text-slate-400">Actions</span>
          <strong>
            {capability.actions_taken_this_control}/{capability.max_actions_per_control}
          </strong>
        </div>
        {!compact ? (
        <div className="rounded bg-slate-800 p-2">
          <span className="block text-slate-400">Focus</span>
          <strong>{focused ? "Yes" : "No"}</strong>
        </div>
        ) : null}
      </div>
      <div className={`rounded bg-slate-800 p-2 ${compact ? "hidden w-16 group-hover:block" : ""}`}>
        <span className="block text-xs text-slate-400">Can initiate</span>
        <div className="mt-2 flex flex-wrap gap-1">
          {initiableEvents.map((event: any) => {
            const imageUrl = event.image_url ? buildApiUrl(event.image_url) : "";
            return (
              <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded border border-slate-700 bg-slate-900 text-[0.55rem]" key={event.id} title={event.name}>
                {imageUrl ? <img alt="" className="h-full w-full object-cover" src={imageUrl} /> : event.name?.slice(0, 2)}
              </span>
            );
          })}
          {initiableEvents.length === 0 ? <span className="text-xs text-slate-500">None</span> : null}
        </div>
      </div>
    </div>
    {compact ? <p className="mt-2 hidden text-xs text-slate-400 group-hover:block">Double-click to focus this board.</p> : null}
    {!compact ? (
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="rounded bg-teal-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50"
          disabled={pending || active}
          onClick={onTakeControl}
          type="button"
        >
          Take control
        </button>
        <button
          className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-50"
          disabled={pending || !active}
          onClick={onCollect}
          type="button"
        >
          Collect AP
        </button>
        <button
          className={[
            "rounded border px-3 py-2 text-xs text-slate-100 disabled:opacity-50",
            moveMode ? "border-amber-300 bg-amber-950" : "border-slate-600 hover:bg-slate-800",
          ].join(" ")}
          disabled={pending || !active || capability.pa < 1}
          onClick={onMoveMode}
          type="button"
        >
          Move
        </button>
        <button
          className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-50"
          disabled={pending || !active || capability.pa < 1 || Number(capability.hand?.length || 0) >= Number(capability.current_max_cards_in_hand || 3)}
          onClick={onDraw}
          type="button"
        >
          Draw
        </button>
      </div>
    ) : null}
  </article>
  );
};

const CardButton = ({
  card,
  projection,
  disabled,
  selected,
  onClick,
}: {
  card: CardProjection;
  projection: GameProjection;
  disabled?: boolean;
  selected?: boolean;
  onClick?: () => void;
}) => {
  const interaction = projection.tile_catalog?.interactions?.[card.interaction_id];
  const imageUrl = interaction?.image_url ? buildApiUrl(interaction.image_url) : "";
  return (
    <button
      className={[
        "flex h-24 w-20 flex-col items-center justify-between rounded-md border bg-slate-800 p-2 text-xs text-white transition disabled:opacity-50",
        selected ? "border-amber-300 ring-2 ring-amber-200" : "border-cyan-700 hover:border-cyan-300",
      ].join(" ")}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {imageUrl ? <img alt="" className="h-10 w-10 rounded object-cover" src={imageUrl} /> : <span className="flex h-10 w-10 items-center justify-center rounded bg-slate-700">{interaction?.name?.slice(0, 2) || "?"}</span>}
      <span className="line-clamp-2 text-center">{interaction?.name || card.interaction_id}</span>
    </button>
  );
};

const InteractionPanel = ({
  projection,
  selectedCapability,
  pending,
  selectedTileInstanceId,
  selectedCardIds,
  visualState,
  onToggleCard,
  onInitiate,
  onResolve,
  onFail,
  onClose,
}: {
  projection: GameProjection;
  selectedCapability: CapabilityProjection | null;
  pending: boolean;
  selectedTileInstanceId: string | null;
  selectedCardIds: string[];
  visualState: "open" | "success" | "failure" | "closing";
  onToggleCard: (cardId: string) => void;
  onInitiate: () => void;
  onResolve: () => void;
  onFail: () => void;
  onClose: () => void;
}) => {
  const activeInteraction = projection.interaction;
  const inspectedTileInstance = selectedTileInstanceId
    ? Object.values(projection.tiles || {}).flat().find((tileInstance: any) => tileInstance.instance_id === selectedTileInstanceId)
    : null;
  const tileInstance = activeInteraction || inspectedTileInstance;
  if (!tileInstance) return null;
  const tile = projection.tile_catalog?.tiles?.[tileInstance.tile_id] || {};
  const event = tile.event || projection.tile_catalog?.events?.[tile.event_id];
  const interactionsById = projection.tile_catalog?.interactions || {};
  const activePlayedCards = activeInteraction?.played_cards || [];
  const selectedCapabilityId = selectedCapability?.id;
  const activeOwnedPlayedCards = activePlayedCards.filter((card: CardProjection) => card.capability_id === selectedCapabilityId);
  const lockedPlayedCards = activePlayedCards.filter((card: CardProjection) => card.capability_id !== selectedCapabilityId);
  const selectableCards = [...activeOwnedPlayedCards, ...(selectedCapability?.hand || [])];
  const selectableCardMap = new Map(selectableCards.map((card: CardProjection) => [card.card_id, card]));
  const selectedCards = selectedCardIds
    .map((cardId) => selectableCardMap.get(cardId))
    .filter(Boolean) as CardProjection[];
  const playedInteractions = [...lockedPlayedCards, ...selectedCards].map((card: CardProjection) => card.interaction_id);
  const missingSuccess = [...(tile.interaction_ids || [])];
  playedInteractions.forEach((interactionId: string) => {
    const index = missingSuccess.indexOf(interactionId);
    if (index >= 0) missingSuccess.splice(index, 1);
  });
  const missingCounter = [...(tile.counter_attack_interaction_ids || [])];
  playedInteractions.forEach((interactionId: string) => {
    const index = missingCounter.indexOf(interactionId);
    if (index >= 0) missingCounter.splice(index, 1);
  });
  const canResolve = missingSuccess.length === 0;
  const canInitiate = !activeInteraction && projection.active_capability_id === selectedCapability?.id;
  const panelTone = visualState === "success"
    ? "border-emerald-400 shadow-emerald-500/40 scale-95 opacity-80"
    : visualState === "failure"
      ? "border-rose-400 shadow-rose-500/40 scale-95 opacity-80"
      : visualState === "closing"
        ? "border-cyan-700 scale-90 opacity-0"
        : "border-cyan-700 scale-100 opacity-100";
  const MissingIcons = ({ ids }: { ids: string[] }) => (
    <div className="mt-2 flex flex-wrap gap-1">
      {ids.map((interactionId, index) => {
        const interaction = interactionsById[interactionId];
        const imageUrl = interaction?.image_url ? buildApiUrl(interaction.image_url) : "";
        return (
          <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full border border-amber-300 bg-slate-950 text-[0.55rem] text-white" key={`${interactionId}:${index}`} title={interaction?.name || interactionId}>
            {imageUrl ? <img alt="" className="h-full w-full object-cover" src={imageUrl} /> : interaction?.name?.slice(0, 2) || "?"}
          </span>
        );
      })}
      {ids.length === 0 ? <span className="text-xs text-teal-200">Ready</span> : null}
    </div>
  );
  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-slate-950/45 p-3">
      <section className={`grid max-h-full w-[min(54rem,calc(100%-1rem))] gap-3 overflow-auto rounded-lg border bg-slate-900 p-3 shadow-2xl transition-all duration-300 md:grid-cols-[16rem_1fr] ${panelTone}`}>
        <div>
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold text-white">{activeInteraction ? "Interaction" : "Tile detail"}</h2>
            {!activeInteraction ? <button className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" onClick={onClose} type="button">Close</button> : null}
          </div>
            <div className="mt-3 rounded-md border border-slate-700 bg-slate-950 p-3">
              <HexTilePreview className="max-w-[15rem]" event={event} interactionsById={interactionsById} tile={tile} />
            <p className="mt-2 text-center font-semibold text-white">{tile.name || tileInstance.tile_id}</p>
            <p className="mt-1 text-center text-xs text-slate-400">Node {activeInteraction?.node_id || projection.poulpita.node_id || "-"}</p>
          </div>
          <div className="mt-3 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">Missing for success</p>
            <MissingIcons ids={missingSuccess} />
            {(tile.counter_attack_interaction_ids || []).length ? (
              <>
                <p className="mt-3 font-semibold text-slate-200">Missing for counter-attack</p>
                <MissingIcons ids={missingCounter} />
              </>
            ) : null}
          </div>
        </div>
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-white">Selected cards</h3>
            <div className="mt-2 flex min-h-28 flex-wrap gap-2 rounded-md border border-dashed border-slate-700 bg-slate-950 p-2">
              {lockedPlayedCards.map((card: CardProjection) => (
                <CardButton
                  card={card}
                  disabled
                  key={card.card_id}
                  projection={projection}
                />
              ))}
              {selectedCards.map((card) => <CardButton card={card} key={card.card_id} onClick={() => onToggleCard(card.card_id)} projection={projection} selected />)}
              {lockedPlayedCards.length + selectedCards.length === 0 ? <p className="m-auto text-sm text-slate-500">Select cards from the focused hand.</p> : null}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Focused hand</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {selectableCards.map((card: CardProjection) => (
                <CardButton
                  card={card}
                  disabled={pending || projection.active_capability_id !== selectedCapability?.id}
                  key={card.card_id}
                  onClick={() => onToggleCard(card.card_id)}
                  projection={projection}
                  selected={selectedCardIds.includes(card.card_id)}
                />
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            {activeInteraction ? (
              <>
                <button className="rounded border border-rose-500 px-3 py-2 text-sm text-rose-100 hover:bg-rose-950 disabled:opacity-50" disabled={pending} onClick={onFail} type="button">Fail</button>
                <button className="rounded bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending} onClick={onResolve} type="button">{canResolve ? "Confirm interaction" : "Confirm cards"}</button>
              </>
            ) : (
              <button className="rounded bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending || !canInitiate} onClick={onInitiate} type="button">Initiate interaction</button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

const GameRoomPage = () => {
  const { roomId } = useParams();
  const { token, user } = useStore();
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [levels, setLevels] = useState<Array<any>>([]);
  const [focusedCapabilityId, setFocusedCapabilityId] = useState<string | null>(null);
  const [moveMode, setMoveMode] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [selectedTileInstanceId, setSelectedTileInstanceId] = useState<string | null>(null);
  const [selectedCardIds, setSelectedCardIds] = useState<string[]>([]);
  const [interactionPanelState, setInteractionPanelState] = useState<"open" | "success" | "failure" | "closing">("open");

  const capabilityMap = projection?.capabilities || {};
  const capabilities = useMemo(() => {
    if (!projection) return [];
    if (projection.player_boards?.length) return projection.player_boards;
    return (projection.capability_order || Object.keys(capabilityMap))
      .map((id) => capabilityMap[id])
      .filter(Boolean);
  }, [capabilityMap, projection]);
  const selectedCapabilityId = focusedCapabilityId || projection?.focused_capability_id || capabilities[0]?.id || "";
  const selectedCapability = selectedCapabilityId ? capabilityMap[selectedCapabilityId] : null;
  const otherCapabilities = capabilities.filter((capability) => capability.id !== selectedCapabilityId);

  useEffect(() => {
    if (projection && !focusedCapabilityId) {
      setFocusedCapabilityId(projection.focused_capability_id || projection.capability_order?.[0] || null);
    }
  }, [focusedCapabilityId, projection]);

  useEffect(() => {
    if (!projection?.interaction) return;
    setSelectedTileInstanceId(projection.interaction.tile_instance_id || null);
    setInteractionPanelState("open");
    const activeCapabilityId = projection.active_capability_id;
    const activePlayedCardIds = (projection.interaction.played_cards || [])
      .filter((card: CardProjection) => card.capability_id === activeCapabilityId)
      .map((card: CardProjection) => card.card_id);
    setSelectedCardIds(activePlayedCardIds);
  }, [projection?.active_capability_id, projection?.interaction?.tile_instance_id, projection?.version]);

  const latestEvent = useMemo(() => {
    const events = projection?.events || [];
    return events.length ? events[events.length - 1] : null;
  }, [projection?.events]);

  const loadProjection = async () => {
    if (!token || !roomId) return;
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/state`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load game state.");
      setProjection(payload);
      setError("");
    } catch (loadError: any) {
      setError(loadError.message || "Failed to load game state.");
    }
  };

  useEffect(() => {
    void loadProjection();
  }, [roomId, token]);

  useEffect(() => {
    const loadLevels = async () => {
      if (!token) return;
      try {
        const response = await fetch(buildApiUrl("/api/game/levels"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Failed to load levels.");
        setLevels(payload.levels || []);
      } catch (loadError: any) {
        setError(loadError.message || "Failed to load levels.");
      }
    };
    void loadLevels();
  }, [token]);

  useEffect(() => {
    if (!token || !roomId) return undefined;
    const socket = new WebSocket(buildWsUrl(`/api/game/rooms/${roomId}/ws`, { token }));
    socketRef.current = socket;
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message?.type === "state_projection") {
          setProjection(message.payload);
          setError("");
        }
      } catch (_error) {
        setError("Received an invalid room update.");
      }
    };
    socket.onerror = () => setError("Room websocket is unavailable; HTTP commands will still work.");
    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;
    };
    return () => {
      socketRef.current = null;
      socket.close(1000, "leaving room");
    };
  }, [roomId, token]);

  const submitCommand = async (type: string, payload: Record<string, unknown> = {}) => {
    if (!token || !roomId || pending) return null;
    setPending(true);
    setFeedback("");
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/commands`), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          command_id: makeCommandId(),
          room_id: roomId,
          actor_user_id: user?.id,
          actor_seat_id: "goldfish",
          expected_version: projection?.version ?? 0,
          type,
          payload,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || "Command failed.");
      if (result.ok === false) {
        const rejection = result as CommandRejection;
        setFeedback(rejection.message || rejection.reason || "Command rejected.");
        if (rejection.projection) setProjection(rejection.projection);
        return result;
      }
      if (result.projection) setProjection(result.projection);
      return result;
    } catch (commandError: any) {
      setError(commandError.message || "Command failed.");
      return null;
    } finally {
      setPending(false);
    }
  };

  const startGoldfishGame = () => {
    void submitCommand("start_goldfish_game");
  };

  const selectLevel = (levelId: string) => {
    setMoveMode(false);
    void submitCommand("select_level", { level_id: levelId });
  };

  const takeControl = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("take_control", { capability_id: selectedCapabilityId });
  };

  const collectActionPoints = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("collect_action_points", { capability_id: selectedCapabilityId });
  };

  const drawActionCard = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("draw_action_card", { capability_id: selectedCapabilityId });
  };

  const movePoulpita = (targetNodeId: NodeId) => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("move_poulpita", {
      capability_id: selectedCapabilityId,
      target_node_id: targetNodeId,
    });
  };

  const inspectTile = (tileInstanceId: string) => {
    setMoveMode(false);
    setSelectedTileInstanceId(tileInstanceId);
    setSelectedCardIds([]);
    setInteractionPanelState("open");
  };

  const toggleDraftCard = (cardId: string) => {
    setSelectedCardIds((cardIds) => cardIds.includes(cardId) ? cardIds.filter((id) => id !== cardId) : [...cardIds, cardId]);
  };

  const closeInteractionPanel = () => {
    setInteractionPanelState("closing");
    window.setTimeout(() => {
      setSelectedTileInstanceId(null);
      setSelectedCardIds([]);
      setInteractionPanelState("open");
    }, 260);
  };

  const initiateInteraction = async () => {
    if (!selectedCapabilityId || !selectedTileInstanceId) return;
    setMoveMode(false);
    const result = await submitCommand("start_interaction", {
      capability_id: selectedCapabilityId,
      tile_instance_id: selectedTileInstanceId,
      card_ids: selectedCardIds,
    });
    if (result?.ok !== false) setInteractionPanelState("open");
  };

  const confirmInteraction = async () => {
    if (!selectedCapabilityId) return;
    const result = await submitCommand("resolve_interaction", {
      capability_id: selectedCapabilityId,
      card_ids: selectedCardIds,
    });
    const eventType = result?.events?.[0]?.type;
    if (eventType === "interaction_resolved") {
      setInteractionPanelState("success");
      window.setTimeout(() => {
        setSelectedTileInstanceId(null);
        setSelectedCardIds([]);
        setInteractionPanelState("open");
      }, 420);
    }
  };

  const failInteraction = async () => {
    const result = await submitCommand("fail_interaction");
    if (result?.ok !== false) {
      setInteractionPanelState("failure");
      window.setTimeout(() => {
        setSelectedTileInstanceId(null);
        setSelectedCardIds([]);
        setInteractionPanelState("open");
      }, 420);
    }
  };

  const endGame = async () => {
    if (!token || !roomId || pending) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/end`), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to end room.");
      navigate(`/games/${roomId}/post-game`);
    } catch (endError: any) {
      setError(endError.message || "Failed to end room.");
      setPending(false);
    }
  };

  return (
    <main className="h-screen overflow-hidden bg-slate-950 text-slate-100">
      <header className="flex h-[5vh] min-h-10 items-center justify-between border-b border-slate-800 bg-slate-900 px-4">
        <div className="min-w-0 text-sm">
          <span className="font-semibold text-white">Ma vie de poulpe</span>
          <span className="ml-3 text-slate-400">v{projection?.version ?? "-"} - {phaseLabel(projection)}</span>
        </div>
        <div className="flex items-center gap-2">
          {projection?.phase === "setup" ? (
            <>
              <select
                className="h-8 rounded border border-slate-700 bg-slate-950 px-2 text-xs text-white"
                disabled={pending || !levels.length}
                onChange={(event) => selectLevel(event.target.value)}
                value={projection.selected_level_id || projection.level_id || ""}
              >
                {levels.map((level) => (
                  <option key={level.id} value={level.id}>
                    {level.name}
                  </option>
                ))}
              </select>
              <button className="rounded bg-teal-400 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending} onClick={startGoldfishGame} type="button">
                Start
              </button>
            </>
          ) : null}
          <button className="rounded border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50" disabled={pending} onClick={endGame} type="button">
            End game
          </button>
        </div>
      </header>

      <section className="relative z-30 grid h-[15vh] grid-cols-4 gap-2 overflow-visible border-b border-slate-800 bg-slate-950 px-4 py-1">
        {otherCapabilities.map((capability) => (
          <CapabilityBoard
            active={projection?.active_capability_id === capability.id}
            capability={capability}
            compact
            focused={false}
            key={capability.id}
            moveMode={moveMode}
            onFocus={() => {
              setFocusedCapabilityId(capability.id);
              setMoveMode(false);
            }}
            pending={pending}
            projection={projection}
          />
        ))}
      </section>

      {feedback || error ? (
        <div className="pointer-events-none fixed left-1/2 top-[22vh] z-50 w-[min(42rem,calc(100vw-2rem))] -translate-x-1/2">
          {feedback ? <p className="rounded-md border border-amber-500/50 bg-amber-950/95 px-3 py-2 text-sm text-amber-100">{feedback}</p> : null}
          {error ? <p className="mt-2 rounded-md border border-rose-500/50 bg-rose-950/95 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
        </div>
      ) : null}

      <section className="grid h-[50vh] grid-cols-[minmax(0,75%)_minmax(14rem,25%)] overflow-hidden">
        <div className="relative min-w-0 overflow-hidden border-r border-slate-800">
          {projection ? (
            <>
              <BoardView moveMode={moveMode} onInspectTile={inspectTile} onMove={movePoulpita} pending={pending} projection={projection} />
              <InteractionPanel
                onFail={failInteraction}
                onClose={closeInteractionPanel}
                onInitiate={initiateInteraction}
                onResolve={confirmInteraction}
                onToggleCard={toggleDraftCard}
                pending={pending}
                projection={projection}
                selectedCardIds={selectedCardIds}
                selectedCapability={selectedCapability}
                selectedTileInstanceId={selectedTileInstanceId}
                visualState={interactionPanelState}
              />
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">Loading room state.</div>
          )}
        </div>
        <aside className="flex h-full flex-col gap-3 overflow-hidden bg-slate-900 p-4">
          <div>
            <p className="text-xs uppercase text-slate-500">Poulpita</p>
            <h2 className="mt-1 text-xl font-semibold text-white">{phaseLabel(projection)}</h2>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Node</span>
              <strong>{projection?.poulpita.node_id || "-"}</strong>
            </div>
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Time</span>
              <strong>{projection?.night_time_spent ?? 0}/24</strong>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Energy</span>
              <strong>{projection?.poulpita.energy ?? 0}</strong>
            </div>
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Neurons</span>
              <strong>{projection?.poulpita.neurons ?? 0}</strong>
            </div>
            <div className="rounded bg-slate-800 p-3">
              <span className="block text-slate-400">Shells</span>
              <strong>{projection?.poulpita.seashells ?? 0}</strong>
            </div>
          </div>
          <div className="rounded bg-slate-800 p-3 text-xs text-slate-300">
            <span className="block text-slate-400">Initiative</span>
            <p className="mt-1">{projection?.active_capability_id ? capabilityMap[projection.active_capability_id]?.name : "No capability controls Poulpita."}</p>
          </div>
          {latestEvent ? <p className="mt-auto text-xs text-slate-500">Latest: {String(latestEvent.type || "event")}</p> : null}
        </aside>
      </section>

      <section className="grid h-[30vh] grid-cols-[minmax(18rem,28rem)_1fr] gap-2 overflow-hidden border-t border-slate-800 bg-slate-950 p-1">
        {selectedCapability ? (
          <CapabilityBoard
            active={projection?.active_capability_id === selectedCapability.id}
            capability={selectedCapability}
            focused
            moveMode={moveMode}
            onCollect={collectActionPoints}
            onDraw={drawActionCard}
            onMoveMode={() => setMoveMode((value) => !value)}
            onTakeControl={takeControl}
            pending={pending}
            projection={projection}
          />
        ) : (
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-sm text-slate-400">No focused player board.</div>
        )}
        <div className="grid h-full grid-cols-[1fr_12rem] gap-3 overflow-hidden">
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
            <h3 className="text-sm font-semibold text-white">Player hand</h3>
            <div className="mt-3 flex h-[calc(100%-2rem)] flex-wrap content-start gap-2 overflow-auto rounded border border-dashed border-slate-700 p-2">
              {(selectedCapability?.hand || []).map((card) => (
                <CardButton
                  card={card}
                  disabled={pending || !(projection?.interaction || selectedTileInstanceId) || projection?.active_capability_id !== selectedCapability?.id}
                  key={card.card_id}
                  onClick={() => (projection?.interaction || selectedTileInstanceId) ? toggleDraftCard(card.card_id) : undefined}
                  projection={projection as GameProjection}
                  selected={selectedCardIds.includes(card.card_id)}
                />
              ))}
              {(selectedCapability?.hand || []).length === 0 ? <p className="m-auto text-sm text-slate-500">No cards in hand.</p> : null}
            </div>
          </div>
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-xs text-slate-400">
            <h3 className="text-sm font-semibold text-white">Action track</h3>
            <p className="mt-2">{selectedCapability?.actions_taken_this_control ?? 0} actions this control.</p>
            {moveMode ? <p className="mt-2 text-amber-200">Click an adjacent map node.</p> : null}
          </div>
        </div>
      </section>
    </main>
  );
};

export default GameRoomPage;
