import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, CirclePlus, Hand, Moon, MoveRight, RefreshCw, Sparkles, Swords, X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import BoardView from "../components/BoardView.js";
import CardPreview from "../components/CardPreview.jsx";
import HexTilePreview from "../components/HexTilePreview.jsx";
import { useStore } from "../store.js";
import type { BotPlanStatus, BotPlanSummary, CapabilityProjection, CardProjection, CommandRejection, GameProjection, NodeId } from "../types/game";
import { buildApiUrl, buildWsUrl } from "../utils/connection.js";

const makeCommandId = () =>
  globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `cmd_${Date.now()}_${Math.random()}`;

const phaseLabel = (projection: GameProjection | null) => {
  if (!projection) return "Loading";
  if (projection.phase === "setup") return "Setup";
  if (projection.phase === "game_over") return "Game over";
  if (projection.phase === "day") return `Day ${projection.day_index || 1}`;
  return `Night ${projection.day_index || 1}`;
};

const TimeTracker = ({ projection }: { projection: GameProjection | null }) => {
  const spent = Math.max(0, Number(projection?.night_time_spent || 0));
  const total = Math.max(1, Number(projection?.night_time_total || 24));
  const visibleTotal = Math.max(total, spent);
  const visibleHours = Math.ceil(visibleTotal / 4);
  const shelterAt = Math.max(0, Number(projection?.night_shelter_available_at || 16));
  return (
    <div className="shrink-0 rounded bg-slate-800 p-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Night clock</span>
        <strong>{Math.floor(spent / 4)}h {(spent % 4) * 15}m</strong>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-1.5">
        {Array.from({ length: visibleHours }).map((_, hourIndex) => (
          <div className="flex items-center gap-1" key={hourIndex}>
            <span className="w-4 text-right text-[0.58rem] font-semibold text-slate-400">{hourIndex + 1}h</span>
            <div className="flex gap-0.5">
              {Array.from({ length: 4 }).map((__, quarterIndex) => {
                const index = hourIndex * 4 + quarterIndex;
                if (index >= visibleTotal) return null;
                return (
                  <span
                    aria-hidden="true"
                    className={[
                      "h-2.5 w-2.5 shrink-0 rounded-[2px] border",
                      index < spent ? (index >= total ? "border-rose-400 bg-rose-400" : "border-cyan-300 bg-cyan-300") : "border-slate-600 bg-slate-900",
                      index + 1 === shelterAt ? "ring-1 ring-amber-300" : "",
                    ].join(" ")}
                    key={index}
                    title={`${hourIndex + 1}h ${quarterIndex * 15}m`}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {spent > total ? <p className="mt-1 text-[0.65rem] text-rose-200">Overtime: {spent - total} extra AP spent.</p> : null}
    </div>
  );
};

const EnergyBar = ({ energy, maximum = 32 }: { energy: number; maximum?: number }) => {
  const maxEnergy = Math.max(1, Math.min(32, Number(maximum || 32)));
  const current = Math.max(0, Math.min(maxEnergy, Number(energy || 0)));
  return (
    <div className="shrink-0 rounded bg-slate-800 p-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Energy</span>
        <strong>{current}/{maxEnergy}</strong>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-0.5">
        {Array.from({ length: maxEnergy }).map((_, index) => (
          <span
            aria-hidden="true"
            className={["h-2.5 w-2.5 shrink-0 rounded-[2px] border", index < current ? "border-emerald-300 bg-emerald-300" : "border-slate-600 bg-slate-900"].join(" ")}
            key={index}
          />
        ))}
      </div>
    </div>
  );
};

const shelterData = (entry: any) => {
  if (typeof entry === "number") return { count: Math.max(0, Number(entry || 0)), seashells: 0, secure: false };
  return {
    count: Math.max(0, Number(entry?.count || 0)),
    seashells: Math.max(0, Number(entry?.seashells || 0)),
    secure: Boolean(entry?.secure) || Number(entry?.seashells || 0) >= 3,
  };
};

const hasNightEndBlocker = (projection: GameProjection | null, nodeId: string) =>
  (projection?.tiles?.[nodeId] || []).some((instance: any) => {
    const tile = projection?.tile_catalog?.tiles?.[instance.tile_id];
    if (
      instance.token_type === "octopus" ||
      ["octopus", "__octopus_token__"].includes(String(instance.tile_id || "")) ||
      tile?.token_type === "octopus"
    ) {
      return true;
    }
    const event = tile?.event || projection?.tile_catalog?.events?.[tile?.event_id];
    const category = projection?.tile_catalog?.categories?.[event?.category_id];
    return Boolean(category?.compulsory_on_same_node);
  });

const DotTrack = ({
  current,
  total,
  label,
  mode = "used",
}: {
  current: number;
  total: number;
  label: string;
  mode?: "available" | "used";
}) => {
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeCurrent = Math.max(0, Number(current) || 0);
  return (
    <div>
      <span className="block text-[0.62rem] uppercase text-slate-400">{label}</span>
      <div className="mt-1 flex flex-wrap gap-1">
        {Array.from({ length: safeTotal }).map((_, index) => {
          const filled = mode === "available" ? index < safeCurrent : index < safeCurrent;
          return (
            <span
              aria-hidden="true"
              className={[
                "h-2.5 w-2.5 rounded-full border",
                filled ? "border-teal-300 bg-teal-300" : "border-slate-500 bg-transparent",
              ].join(" ")}
              key={index}
            />
          );
        })}
        {safeTotal === 0 ? <span className="text-xs text-slate-500">-</span> : null}
      </div>
    </div>
  );
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
  onSpecialPower,
  onEndNight,
  onEndDay,
  onBuyUpgrade,
  showActions = true,
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
  onSpecialPower?: () => void;
  onEndNight?: () => void;
  onEndDay?: () => void;
  onBuyUpgrade?: (upgradeIndex: number) => void;
  showActions?: boolean;
}) => {
  const initiableEvents = (capability.initiates_event_ids || [])
    .map((eventId) => projection?.tile_catalog?.events?.[eventId])
    .filter(Boolean);
  const availableControls = Math.max(0, Number(capability.max_control_takes_per_night || 0) - Number(capability.control_takes_this_night || 0));
  const availableActions = active
    ? Math.max(0, Number(capability.max_actions_per_control || 0) - Number(capability.actions_taken_this_control || 0))
    : Number(capability.max_actions_per_control || 0);
  const handCount = Number(capability.hand?.length || 0);
  const handLimit = Number(capability.current_max_cards_in_hand || 3);
  const canSeeHand = focused || capability.id === "intelligence";
  const cardCategories = projection?.tile_catalog?.card_categories || [];
  const cardsByInteraction = projection?.tile_catalog?.cards || {};
  const actionPoints = Math.max(0, Number(capability.pa || 0));
  const isNightAction = projection?.phase === "night_action";
  const isNight = projection?.phase === "night_idle" || projection?.phase === "night_action";
  const currentNodeId = projection?.poulpita?.node_id || "";
  const canEndNight =
    focused &&
    active &&
    projection?.phase === "night_action" &&
    Boolean(currentNodeId) &&
    shelterData(projection?.shelters?.[currentNodeId]).count > 0 &&
    Number(projection?.night_time_spent || 0) >= Number(projection?.night_shelter_available_at || 16) &&
    !hasNightEndBlocker(projection, currentNodeId);
  const purchasedUpgrades = new Set((capability.purchased_hand_size_upgrade_indices || []).map((index) => Number(index)));
  const sharedNeurons = Number(projection?.poulpita?.neurons || 0);
  const ArticleTag = compact ? "button" : "article";
  const controllerType = capability.controller_type || "human";
  const controllerLabel = controllerType === "bot" ? "Bot" : controllerType === "shared" ? "Shared" : "Human";
  const boardColor = projection ? abilityColor(projection, capability.id) : "#0891b2";
  return (
  <ArticleTag
    className={[
      "group/board relative min-w-0 overflow-auto rounded-md border-2 bg-slate-900 text-left text-slate-100 shadow-xl transition",
      compact ? "cursor-pointer hover:z-50 hover:bg-slate-800 hover:shadow-cyan-500/20 focus:outline-none focus:ring-2 focus:ring-cyan-300" : "",
      active ? "ring-2 ring-teal-200" : focused ? "ring-2 ring-amber-200" : "",
      compact ? "h-full p-1" : "h-full p-2",
    ].join(" ")}
    onClick={compact ? onFocus : undefined}
    style={{ borderColor: boardColor }}
    type={compact ? "button" : undefined}
  >
    <div className="flex items-start justify-between gap-1">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-white">{capability.name}</h3>
          <span
            className={[
              "shrink-0 rounded-full border px-1.5 py-0.5 text-[0.55rem] font-bold uppercase tracking-wide",
              controllerType === "bot"
                ? "border-cyan-300 bg-cyan-950 text-cyan-100"
                : controllerType === "shared"
                  ? "border-violet-300 bg-violet-950 text-violet-100"
                  : "border-amber-300 bg-amber-950 text-amber-100",
            ].join(" ")}
          >
            {controllerLabel}
          </span>
          {active ? (
            <span className="shrink-0 rounded-full border border-teal-200 bg-teal-300 px-2 py-0.5 text-[0.6rem] font-bold uppercase tracking-wide text-teal-950">
              Initiative
            </span>
          ) : null}
        </div>
        <p className="text-xs text-slate-400">{active ? "Controls Poulpita" : focused ? "In focus" : "Waiting"}</p>
      </div>
      <div className="rounded bg-slate-800 px-2 py-1 text-xs font-semibold text-slate-100">
        <DotTrack current={actionPoints} label="AP" mode="available" total={actionPoints} />
      </div>
    </div>
    <div className={compact ? "mt-2 grid grid-cols-[minmax(0,1fr)_4.5rem] gap-2" : "mt-3 grid grid-cols-[1fr_8rem] gap-3"}>
      <div className={compact ? "grid grid-cols-3 gap-1 text-xs" : "grid grid-cols-3 gap-1 text-xs"}>
        <div className={compact ? "rounded bg-slate-800 p-1.5" : "rounded bg-slate-800 p-1"}>
          <DotTrack current={availableControls} label="Controls" mode="available" total={capability.max_control_takes_per_night} />
        </div>
        <div className={compact ? "rounded bg-slate-800 p-1.5" : "rounded bg-slate-800 p-1"}>
          <DotTrack current={availableActions} label="Actions" mode="available" total={capability.max_actions_per_control} />
        </div>
        <div className={compact ? "rounded bg-slate-800 p-1.5" : "rounded bg-slate-800 p-1"}>
          {compact ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {(capability.hand || []).slice(0, 6).map((card) => {
                const options = cardInteractionOptions(card);
                const generatedCard = cardsByInteraction[card.interaction_id] || cardsByInteraction[options[0]];
                const imageUrl = generatedCard?.image_url ? buildApiUrl(generatedCard.image_url) : "";
                return (
                  <span className={`${canSeeHand ? "border-cyan-300 bg-cyan-50" : "border-slate-500 bg-[linear-gradient(135deg,#0f766e_0_45%,#164e63_45%_55%,#0f766e_55%)]"} flex h-5 w-3.5 items-center justify-center overflow-hidden rounded-sm border text-[0.45rem] text-teal-900`} key={card.card_id} title={canSeeHand ? options.map((id: string) => projection?.tile_catalog?.interactions?.[id]?.name || id).join(" / ") : "Hidden card"}>
                    {canSeeHand && imageUrl ? <img alt="" className="h-full w-full object-cover" src={imageUrl} /> : canSeeHand ? (options.length > 1 ? "2" : generatedCard?.name?.slice(0, 1) || "?") : null}
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
      <div className={compact ? "rounded bg-slate-800 p-1.5" : "rounded bg-slate-800 p-2"}>
        <span className="block text-xs text-slate-400">{projection?.phase === "day" && !compact ? "Upgrades" : "Can initiate"}</span>
        <div className={compact ? "mt-1 flex flex-wrap gap-1" : "mt-2 flex flex-wrap gap-1"}>
          {projection?.phase === "day" && !compact ? (
            (capability.hand_size_upgrades || []).map((upgrade, index) => {
              const bought = purchasedUpgrades.has(index);
              const cost = Number(upgrade.cost || 0);
              const isDeckExchange = upgrade.type === "deck_exchange";
              return (
                <button
                  className={[
                    "rounded border px-2 py-1 text-left text-[0.65rem] leading-tight",
                    bought ? "border-slate-600 bg-slate-900 text-slate-500" : "border-cyan-300 bg-slate-950 text-cyan-100 hover:bg-cyan-950",
                  ].join(" ")}
                  disabled={pending || bought || sharedNeurons < cost}
                  key={index}
                  onClick={() => onBuyUpgrade?.(index)}
                  type="button"
                >
                  {isDeckExchange ? "Improve deck" : `+${Number(upgrade.hand_size_bonus || 1)} hand`}
                  <span className="block text-[0.58rem] text-slate-400">{bought ? "Bought" : `${cost} neurons`}</span>
                </button>
              );
            })
          ) : initiableEvents.map((event: any) => {
            const imageUrl = event.image_url ? buildApiUrl(event.image_url) : "";
            return (
              <span className={`${compact ? "h-5 w-5" : "h-7 w-7"} flex items-center justify-center overflow-hidden rounded border border-slate-700 bg-slate-900 text-[0.55rem]`} key={event.id} title={event.name}>
                {imageUrl ? <img alt="" className="h-full w-full object-cover" src={imageUrl} /> : event.name?.slice(0, 2)}
              </span>
            );
          })}
          {projection?.phase === "day" && !compact && (capability.hand_size_upgrades || []).length === 0 ? <span className="text-xs text-slate-500">No upgrades</span> : null}
          {!(projection?.phase === "day" && !compact) && initiableEvents.length === 0 ? <span className="text-xs text-slate-500">None</span> : null}
        </div>
      </div>
    </div>
    {!compact && showActions ? (
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="rounded bg-teal-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50"
          disabled={pending || active || !isNight}
          onClick={onTakeControl}
          type="button"
        >
          Take control
        </button>
        <button
          className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-50"
          disabled={pending || !active || !isNightAction}
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
          disabled={pending || !active || !isNightAction || capability.pa < 1}
          onClick={onMoveMode}
          type="button"
        >
          Move
        </button>
        <button
          className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-50"
          disabled={pending || !active || !isNightAction || capability.pa < 1}
          onClick={onDraw}
          type="button"
        >
          Draw
        </button>
        {projection?.phase === "day" ? (
          <button
            className="rounded border border-cyan-300 px-3 py-2 text-xs text-cyan-100 hover:bg-cyan-950 disabled:opacity-50"
            disabled={pending}
            onClick={onEndDay}
            type="button"
          >
            End day
          </button>
        ) : (
          <button
            className="rounded border border-cyan-300 px-3 py-2 text-xs text-cyan-100 hover:bg-cyan-950 disabled:opacity-50"
            disabled={pending || !canEndNight}
            onClick={onEndNight}
            type="button"
          >
            End night
          </button>
        )}
      </div>
    ) : null}
  </ArticleTag>
  );
};

const ActionPanel = ({
  capability,
  active,
  moveMode,
  onCollect,
  onDraw,
  onEndDay,
  onEndNight,
  onMoveMode,
  onSpecialPower,
  onTakeControl,
  pending,
  projection,
}: {
  capability: CapabilityProjection | null;
  active: boolean;
  moveMode: boolean;
  onCollect: () => void;
  onDraw: () => void;
  onEndDay: () => void;
  onEndNight: () => void;
  onMoveMode: () => void;
  onSpecialPower: () => void;
  onTakeControl: () => void;
  pending: boolean;
  projection: GameProjection | null;
}) => {
  if (!capability) return <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-sm text-slate-500">No actions.</div>;
  const isNightAction = projection?.phase === "night_action";
  const isNight = projection?.phase === "night_idle" || projection?.phase === "night_action";
  const currentNodeId = projection?.poulpita?.node_id || "";
  const actionCosts = projection?.tile_catalog?.action_costs || {};
  const actionCost = (actionId: string, defaultAp: number, defaultTime: number, defaultNeurons = 0) => ({
    ap: Number(actionCosts[actionId]?.ap_cost ?? defaultAp),
    time: Number(actionCosts[actionId]?.time_cost ?? defaultTime),
    neurons: Number(actionCosts[actionId]?.neuron_cost ?? defaultNeurons),
  });
  const gainCost = actionCost("gain_ap", 0, 0);
  const moveCost = actionCost("move", 1, 1);
  const drawCost = actionCost("draw", 1, 1);
  const specialCost = actionCost("special_power", 2, 2, 1);
  const canAfford = (cost: { ap: number; neurons: number }) => Number(capability.pa || 0) >= cost.ap && Number(projection?.poulpita?.neurons || 0) >= cost.neurons;
  const canEndNight =
    active &&
    projection?.phase === "night_action" &&
    Boolean(currentNodeId) &&
    shelterData(projection?.shelters?.[currentNodeId]).count > 0 &&
    Number(projection?.night_time_spent || 0) >= Number(projection?.night_shelter_available_at || 16) &&
    !hasNightEndBlocker(projection, currentNodeId);
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto rounded-md border border-slate-800 bg-slate-900 p-2">
      <h3 className="text-sm font-semibold text-white">Actions</h3>
      <div className="grid grid-cols-2 gap-1.5">
        <button className="rounded bg-teal-400 px-1.5 py-2 text-[0.68rem] font-semibold leading-tight text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending || active || !isNight} onClick={onTakeControl} type="button">
          Take control
        </button>
        <button className="rounded border border-slate-600 px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 hover:bg-slate-800 disabled:opacity-50" disabled={pending || !active || !isNightAction || !canAfford(gainCost)} onClick={onCollect} type="button">
          Collect AP ({gainCost.ap} AP)
        </button>
        <button
          className={["rounded border px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 disabled:opacity-50", moveMode ? "border-amber-300 bg-amber-950" : "border-slate-600 hover:bg-slate-800"].join(" ")}
          disabled={pending || !active || !isNightAction || !canAfford(moveCost)}
          onClick={onMoveMode}
          type="button"
        >
          Move ({moveCost.ap} AP)
        </button>
        <button className="rounded border border-slate-600 px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 hover:bg-slate-800 disabled:opacity-50" disabled={pending || !active || !isNightAction || !canAfford(drawCost)} onClick={onDraw} type="button">
          Draw ({drawCost.ap} AP)
        </button>
        <button className="rounded border border-fuchsia-500 px-1.5 py-2 text-[0.68rem] leading-tight text-fuchsia-100 hover:bg-fuchsia-950 disabled:opacity-50" disabled={pending || !active || !isNightAction || !canAfford(specialCost)} onClick={onSpecialPower} type="button">
          Special ({specialCost.ap} AP, {specialCost.neurons} N)
        </button>
        {projection?.phase === "day" ? (
          <button className="rounded border border-cyan-300 px-1.5 py-2 text-[0.68rem] leading-tight text-cyan-100 hover:bg-cyan-950 disabled:opacity-50" disabled={pending} onClick={onEndDay} type="button">
            End day
          </button>
        ) : (
          <button className="rounded border border-cyan-300 px-1.5 py-2 text-[0.68rem] leading-tight text-cyan-100 hover:bg-cyan-950 disabled:opacity-50" disabled={pending || !canEndNight} onClick={onEndNight} type="button">
            End night
          </button>
        )}
      </div>
    </div>
  );
};

const CardButton = ({
  card,
  projection,
  disabled,
  selected,
  showPreview = false,
  onClick,
}: {
  card: CardProjection;
  projection: GameProjection;
  disabled?: boolean;
  selected?: boolean;
  showPreview?: boolean;
  onClick?: () => void;
}) => {
  const options = cardInteractionOptions(card);
  const interactions = options.map((interactionId) => projection.tile_catalog?.interactions?.[interactionId]).filter(Boolean);
  const interaction = interactions[0] || projection.tile_catalog?.interactions?.[card.interaction_id];
  const generatedCard = projection.tile_catalog?.cards?.[card.interaction_id] || projection.tile_catalog?.cards?.[options[0]];
  const cardCategories = projection.tile_catalog?.card_categories || [];
  const imageUrl = interaction?.image_url ? buildApiUrl(interaction.image_url) : "";
  const [previewPosition, setPreviewPosition] = useState<{ left: number; top: number } | null>(null);
  const openPreview = (element: HTMLElement) => {
    if (!showPreview || !generatedCard) return;
    const rect = element.getBoundingClientRect();
    const width = 320;
    const margin = 12;
    const left = Math.min(window.innerWidth - width - margin, Math.max(margin, rect.left + rect.width / 2 - width / 2));
    const top = rect.top > 360 ? rect.top - margin : rect.bottom + margin;
    setPreviewPosition({ left, top });
  };
  return (
    <span
      className="relative inline-block"
      onMouseEnter={(event) => openPreview(event.currentTarget)}
      onMouseLeave={() => setPreviewPosition(null)}
      onFocus={(event) => openPreview(event.currentTarget)}
      onBlur={() => setPreviewPosition(null)}
    >
      <button
        className={[
          "flex h-20 w-16 flex-col items-center justify-between rounded-md border bg-slate-800 p-1.5 text-[0.65rem] text-white transition disabled:opacity-50",
          selected ? "border-amber-300 ring-2 ring-amber-200" : "border-cyan-700 hover:border-cyan-300",
        ].join(" ")}
        disabled={disabled}
        onClick={onClick}
        type="button"
      >
        {imageUrl ? <img alt="" className="h-8 w-8 rounded object-cover" src={imageUrl} /> : <span className="flex h-8 w-8 items-center justify-center rounded bg-slate-700">{interaction?.name?.slice(0, 2) || "?"}</span>}
        <span className="line-clamp-2 text-center">{interactions.length > 1 ? interactions.map((entry: any) => entry.name).join(" / ") : interaction?.name || card.interaction_id}</span>
      </button>
      {showPreview && generatedCard && previewPosition
        ? createPortal(
            <div
              className="pointer-events-none fixed z-[9999] w-80"
              style={{ left: previewPosition.left, top: previewPosition.top, transform: previewPosition.top > window.innerHeight / 2 ? "translateY(-100%)" : undefined }}
            >
              <CardPreview card={generatedCard} categories={cardCategories} />
            </div>,
            document.body,
          )
        : null}
    </span>
  );
};

const contentImageUrl = (entry: any) => (entry?.image_url ? buildApiUrl(entry.image_url) : "");

const cardInteractionOptions = (card: any) => {
  const options = Array.isArray(card?.interaction_ids) ? card.interaction_ids.filter(Boolean) : [];
  if (card?.interaction_id && !options.includes(card.interaction_id)) options.unshift(card.interaction_id);
  return options;
};

const chooseCardInteractionForTile = (card: any, tile: any, alreadyPlayed: string[]) => {
  const options = cardInteractionOptions(card);
  if (!options.length) return card?.interaction_id || "";
  for (const requiredIds of [tile?.interaction_ids || [], tile?.counter_attack_interaction_ids || []]) {
    const remaining = [...requiredIds];
    alreadyPlayed.forEach((interactionId) => {
      const index = remaining.indexOf(interactionId);
      if (index >= 0) remaining.splice(index, 1);
    });
    const match = options.find((interactionId) => remaining.includes(interactionId));
    if (match) return match;
  }
  return options[0];
};

const ResourceToken = ({ token, label }: { token?: any; label: string }) => {
  const url = contentImageUrl(token);
  return (
    <span className="inline-flex h-5 w-5 items-center justify-center overflow-hidden rounded-full border border-teal-300 bg-white text-[0.48rem] font-bold text-teal-950 shadow-sm" title={label}>
      {url ? <img alt="" className="h-full w-full object-cover" src={url} /> : label.slice(0, 2)}
    </span>
  );
};

const formatSize = (size: any) => `${Number(size?.amount ?? size?.kg ?? 0).toLocaleString()} ${size?.unit || "kg"}`;

const SizeBar = ({
  canBuy,
  currentSize,
  nextCost,
  nextSize,
  onBuy,
  pending,
  sizeIndex,
  totalSizes,
  upgradedToday,
}: {
  canBuy: boolean;
  currentSize: any;
  nextCost: number;
  nextSize: any;
  onBuy: () => void;
  pending: boolean;
  sizeIndex: number;
  totalSizes: number;
  upgradedToday: boolean;
}) => (
  <div className="mb-1.5 shrink-0 rounded border border-slate-700 p-2">
    <div className="flex items-center justify-between gap-2">
      <div>
        <span className="block text-[0.62rem] uppercase text-slate-400">Size</span>
        <strong className="text-slate-100">{formatSize(currentSize)}</strong>
      </div>
      <button
        className="rounded border border-cyan-300 px-2 py-1 text-[0.68rem] font-semibold text-black-100 hover:bg-cyan-950 disabled:opacity-50"
        disabled={pending || !canBuy}
        onClick={onBuy}
        type="button"
      >
        {nextSize ? `Grow: ${nextCost} energy` : "Max size"}
      </button>
    </div>
    <div className="mt-2 flex gap-1">
      {Array.from({ length: Math.max(1, totalSizes) }).map((_, index) => (
        <span
          aria-hidden="true"
          className={["h-2 flex-1 rounded", index <= sizeIndex ? "bg-cyan-300" : "bg-slate-700"].join(" ")}
          key={index}
        />
      ))}
    </div>
    {upgradedToday ? <p className="mt-1 text-[0.62rem] text-slate-400">Already grown today.</p> : nextSize ? <p className="mt-1 text-[0.62rem] text-slate-400">Next: {formatSize(nextSize)}</p> : null}
  </div>
);

const ObjectivesPanel = ({ projection }: { projection: GameProjection | null }) => {
  const objectives = projection?.objectives || [];
  return (
    <div className="shrink-0 rounded bg-slate-800 p-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Objectives</span>
        <strong>{objectives.filter((objective: any) => objective.completed).length}/{objectives.length}</strong>
      </div>
      <div className="mt-1.5 max-h-20 space-y-1 overflow-auto pr-1">
        {objectives.map((objective: any) => (
          <div className="flex items-center gap-1.5 rounded border border-slate-700 px-2 py-0.5 text-[0.68rem]" key={objective.id}>
            <span className={["h-2.5 w-2.5 shrink-0 rounded-full border", objective.completed ? "border-teal-300 bg-teal-300" : "border-slate-500 bg-transparent"].join(" ")} />
            <span className={["min-w-0 truncate", objective.completed ? "text-teal-100" : "text-slate-300"].join(" ")} title={objective.label || objective.type}>
              {objective.label || objective.type}
              {objective.type === "increase_size" ? ` (${objective.current || 0}/${objective.target || 1})` : ""}
            </span>
          </div>
        ))}
        {objectives.length === 0 ? <p className="text-xs text-slate-500">No level objectives.</p> : null}
      </div>
    </div>
  );
};

const PoulpitaResourcePanel = ({
  onBuySize,
  onMoveShellToShelter,
  pending,
  projection,
}: {
  onBuySize: () => void;
  onMoveShellToShelter: () => void;
  pending: boolean;
  projection: GameProjection | null;
}) => {
  const panel = projection?.tile_catalog?.poulpita_panel || {};
  const tokens = projection?.tile_catalog?.tokens || {};
  const containerUrl = contentImageUrl(panel);
  const zones = panel.zones || {};
  const aspectRatio = panel.image_width && panel.image_height ? `${panel.image_width} / ${panel.image_height}` : "4 / 3";
  const sizes = panel.sizes || [{ amount: 1, unit: "kg", energy_cost: 0 }];
  const sizeIndex = Math.max(0, Number(projection?.poulpita.size_index || 0));
  const currentSize = sizes[sizeIndex] || sizes[0] || { amount: 1, unit: "kg", energy_cost: 0 };
  const nextSize = sizes[sizeIndex + 1] || null;
  const currentShelter = shelterData(projection?.shelters?.[projection?.poulpita.node_id || ""]);
  const baseNextSizeCost = Number(nextSize?.energy_cost || 0);
  const nextSizeCost = Math.max(0, baseNextSizeCost - Math.max(0, Number(currentShelter.seashells || 0) - 2));
  const energy = Number(projection?.poulpita.energy || 0);
  const canBuySize = projection?.phase === "day" && Boolean(nextSize) && !projection?.poulpita.size_upgraded_today && (nextSizeCost === 0 || energy - nextSizeCost > 0);
  const canMoveShellToShelter = projection?.phase === "day" && currentShelter.count > 0 && Number(projection?.poulpita.seashells || 0) > 0 && !pending;
  const resources = [
    { zoneId: "neurons", label: "Neurons", count: Number(projection?.poulpita.neurons || 0), token: tokens.neuron },
    { zoneId: "seashells", label: "Shells", count: Number(projection?.poulpita.seashells || 0), token: tokens.seashell },
  ];

  if (!containerUrl) {
    return (
      <div className="min-h-0 space-y-1.5 overflow-hidden text-xs">
        <SizeBar currentSize={currentSize} canBuy={canBuySize} nextCost={nextSizeCost} nextSize={nextSize} onBuy={onBuySize} pending={pending} sizeIndex={sizeIndex} totalSizes={sizes.length} upgradedToday={Boolean(projection?.poulpita.size_upgraded_today)} />
        {currentShelter.secure && nextSize ? <p className="-mt-1 text-[0.62rem] text-teal-200">Secure shelter discount: -1 energy.</p> : null}
        <div className="grid grid-cols-2 gap-1.5">
        {resources.map((resource) => (
          <div className="min-h-0 rounded bg-slate-800 p-2" key={resource.zoneId}>
            <span className="block text-slate-400">{resource.label}</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {Array.from({ length: resource.count }).map((_, index) =>
                resource.zoneId === "seashells" ? (
                  <button className="rounded-full disabled:cursor-default" disabled={!canMoveShellToShelter} key={index} onClick={onMoveShellToShelter} title={canMoveShellToShelter ? "Move shell to current shelter" : "Shell"}>
                    <ResourceToken label={resource.label} token={resource.token} />
                  </button>
                ) : (
                  <ResourceToken key={index} label={resource.label} token={resource.token} />
                ),
              )}
            </div>
          </div>
        ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded bg-slate-800 p-2 text-xs">
      <div className="mb-1.5 flex shrink-0 items-center justify-between">
        <span className="text-slate-400">Poulpita Board</span>
      </div>
      <SizeBar currentSize={currentSize} canBuy={canBuySize} nextCost={nextSizeCost} nextSize={nextSize} onBuy={onBuySize} pending={pending} sizeIndex={sizeIndex} totalSizes={sizes.length} upgradedToday={Boolean(projection?.poulpita.size_upgraded_today)} />
      {currentShelter.secure && nextSize ? <p className="-mt-1 mb-1.5 shrink-0 text-[0.62rem] text-teal-200">Secure shelter discount: -1 energy.</p> : null}
      <div className="relative min-h-0 flex-1 overflow-hidden rounded border border-slate-700 bg-slate-950" style={{ aspectRatio }}>
        <img alt="Poulpita resource board" className="absolute inset-0 h-full w-full object-contain" src={containerUrl} />
        {resources.map((resource) => {
          const zone = zones[resource.zoneId];
          if (!zone) return null;
          return (
            <div
              className="absolute flex flex-wrap content-start gap-1 overflow-hidden p-1"
              key={resource.zoneId}
              style={{ left: `${zone.x * 100}%`, top: `${zone.y * 100}%`, width: `${zone.width * 100}%`, height: `${zone.height * 100}%` }}
              title={`${resource.label}: ${resource.count}`}
            >
              {Array.from({ length: resource.count }).map((_, index) =>
                resource.zoneId === "seashells" ? (
                  <button className="rounded-full disabled:cursor-default" disabled={!canMoveShellToShelter} key={index} onClick={onMoveShellToShelter} title={canMoveShellToShelter ? "Move shell to current shelter" : "Shell"}>
                    <ResourceToken label={resource.label} token={resource.token} />
                  </button>
                ) : (
                  <ResourceToken key={index} label={resource.label} token={resource.token} />
                ),
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const InteractionPanel = ({
  projection,
  selectedCapability,
  pending,
  selectedTileInstanceId,
  selectedCardIds,
  visualState,
  failMoveTargetNodeId,
  onToggleCard,
  onFailMoveTargetChange,
  onInitiate,
  onConfirmCards,
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
  onConfirmCards: () => void;
  onResolve: () => void;
  failMoveTargetNodeId: string;
  onFailMoveTargetChange: (nodeId: string) => void;
  onFail: (spendEnergyToRetry?: boolean) => void;
  onClose: () => void;
}) => {
  const activeInteraction = projection.interaction;
  const inspectedTileInstance = selectedTileInstanceId
    ? Object.values(projection.tiles || {}).flat().find((tileInstance: any) => tileInstance.instance_id === selectedTileInstanceId)
    : null;
  const tileInstance = activeInteraction || inspectedTileInstance;
  if (!tileInstance) return null;
  const tile = projection.tile_catalog?.tiles?.[tileInstance.tile_id] || {};
  const octopusToken = projection.tile_catalog?.tokens?.octopus;
  const rawEvent = tile.event || projection.tile_catalog?.events?.[tile.event_id];
  const isOctopusToken = tile?.token_type === "octopus" || tileInstance?.token_type === "octopus";
  const event = isOctopusToken
    ? {
        ...(rawEvent || {}),
        id: rawEvent?.id || "__octopus_token_event__",
        name: rawEvent?.name || tile?.name || octopusToken?.name || "Octopus token",
        image_url: rawEvent?.image_url || tile?.image_url || octopusToken?.image_url || "",
      }
    : rawEvent;
  const interactionsById = projection.tile_catalog?.interactions || {};
  const activePlayedCards = activeInteraction?.played_cards || [];
  const selectedCapabilityId = selectedCapability?.id;
  const initiatorConfirmationRequired = Boolean(
    activeInteraction
    && activeInteraction.initiator_confirmed === false
    && activeInteraction.initiator_capability_id !== selectedCapabilityId,
  );
  const canEditInitiatorCards = Boolean(
    activeInteraction
    && activeInteraction.initiator_confirmed === false
    && activeInteraction.initiator_capability_id === selectedCapabilityId,
  );
  const activeOwnedPlayedCards = canEditInitiatorCards
    ? activePlayedCards.filter((card: CardProjection) => card.capability_id === selectedCapabilityId)
    : [];
  const lockedPlayedCards = activePlayedCards.filter((card: CardProjection) => !activeOwnedPlayedCards.some((owned: CardProjection) => owned.card_id === card.card_id));
  const handCards = selectedCapability?.hand || [];
  const selectableCards = [...activeOwnedPlayedCards, ...handCards];
  const selectableCardMap = new Map(selectableCards.map((card: CardProjection) => [card.card_id, card]));
  const selectedCards = selectedCardIds
    .map((cardId) => selectableCardMap.get(cardId))
    .filter(Boolean) as CardProjection[];
  const playedInteractions = [...lockedPlayedCards, ...selectedCards].reduce((selected: string[], card: CardProjection) => {
    selected.push(chooseCardInteractionForTile(card, tile, selected));
    return selected;
  }, []);
  const requiredInteractionIds = activeInteraction?.courtship_card?.interaction_ids || tile.interaction_ids || [];
  const missingSuccess = [...requiredInteractionIds];
  playedInteractions.forEach((interactionId: string) => {
    const index = missingSuccess.indexOf(interactionId);
    if (index >= 0) missingSuccess.splice(index, 1);
  });
  const missingCounter = [...(tile.counter_attack_interaction_ids || [])];
  playedInteractions.forEach((interactionId: string) => {
    const index = missingCounter.indexOf(interactionId);
    if (index >= 0) missingCounter.splice(index, 1);
  });
  const shellRequirementCount = Math.max(0, Number(tile.shell_requirement_count || 0));
  const carriedShells = Math.max(0, Number(projection.poulpita?.seashells || 0));
  const missingShells = Math.max(0, shellRequirementCount - carriedShells);
  const canResolve = missingSuccess.length === 0 && missingShells === 0;
  const confirmationPending = Boolean(canEditInitiatorCards || selectedCardIds.some((cardId) => !activeOwnedPlayedCards.some((card: CardProjection) => card.card_id === cardId)));
  const missingCardSymbols = [...missingSuccess, ...missingCounter];
  const cardCanFillMissing = (card: CardProjection) => {
    const options = card.interaction_ids?.length ? card.interaction_ids : [card.interaction_id];
    return options.some((interactionId) => missingCardSymbols.includes(interactionId));
  };
  const canInitiate = !activeInteraction && projection.active_capability_id === selectedCapability?.id;
  const requiresFreeFailureMove = Boolean(activeInteraction && (tile.failure_effects || []).some((effect: any) => effect.type === "pulpita_move_free"));
  const isCourtship = Boolean(activeInteraction?.courtship_card);
  const currentNodeId = projection.poulpita?.node_id || "";
  const adjacentNodeIds = currentNodeId ? projection.map?.adjacency?.[currentNodeId] || [] : [];
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
  const MissingShellIcons = () => shellRequirementCount > 0 ? (
    <div className="mt-2 flex flex-wrap gap-1">
      {Array.from({ length: shellRequirementCount }).map((_, index) => (
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-full border text-[0.55rem] font-bold ${index < carriedShells ? "border-amber-300 bg-amber-100 text-amber-900" : "border-rose-400 bg-rose-950 text-rose-100"}`}
          key={index}
          title={index < carriedShells ? "Shell carried by Poulpita" : "Missing Poulpita shell"}
        >
          S
        </span>
      ))}
    </div>
  ) : null;
  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-slate-950/45 p-3">
      <section className={`grid max-h-full w-[min(54rem,calc(100%-1rem))] gap-3 overflow-auto rounded-lg border bg-slate-900 p-3 shadow-2xl transition-all duration-300 md:grid-cols-[16rem_1fr] ${panelTone}`}>
        <div>
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-semibold text-white">{activeInteraction ? "Interaction" : "Tile detail"}</h2>
            {!activeInteraction ? <button className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" onClick={onClose} type="button">Close</button> : null}
          </div>
            <div className="mt-3 rounded-md border border-slate-700 bg-slate-950 p-3">
              {isCourtship && activeInteraction.courtship_card.image_url ? <img alt={activeInteraction.courtship_card.name || "Courtship card"} className="mx-auto max-h-64 max-w-full rounded object-contain" src={buildApiUrl(activeInteraction.courtship_card.image_url)} /> : <HexTilePreview className="max-w-[15rem]" event={event} interactionsById={interactionsById} tile={tile} />}
            <p className="mt-2 text-center font-semibold text-white">{tile.name || tileInstance.tile_id}</p>
            <p className="mt-1 text-center text-xs text-slate-400">Node {activeInteraction?.node_id || projection.poulpita.node_id || "-"}</p>
          </div>
          <div className="mt-3 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">Missing for success</p>
            <MissingIcons ids={missingSuccess} />
            <MissingShellIcons />
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
              {handCards.map((card: CardProjection) => (
                <CardButton
                  card={card}
                  disabled={pending || initiatorConfirmationRequired || (!selectedCardIds.includes(card.card_id) && !cardCanFillMissing(card))}
                  key={card.card_id}
                  onClick={() => onToggleCard(card.card_id)}
                  projection={projection}
                  selected={selectedCardIds.includes(card.card_id)}
                />
              ))}
              {handCards.length === 0 ? <p className="text-sm text-slate-500">No cards in focused hand.</p> : null}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            {activeInteraction ? (
              <>
                {requiresFreeFailureMove ? (
                  <select className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={failMoveTargetNodeId} onChange={(event) => onFailMoveTargetChange(event.target.value)}>
                    <option value="">Move Poulpita to...</option>
                    {adjacentNodeIds.map((nodeId: string) => <option key={nodeId} value={nodeId}>{nodeId}</option>)}
                  </select>
                ) : null}
                {isCourtship ? <button className="rounded border border-amber-400 px-3 py-2 text-sm text-amber-100 hover:bg-amber-950 disabled:opacity-50" disabled={pending || Number(projection.poulpita.energy || 0) <= 1} onClick={() => onFail(true)} type="button">Spend 1 energy and retry</button> : null}
                <button className="rounded border border-rose-500 px-3 py-2 text-sm text-rose-100 hover:bg-rose-950 disabled:opacity-50" disabled={pending || (requiresFreeFailureMove && !failMoveTargetNodeId)} onClick={() => onFail(false)} type="button">{isCourtship ? "Leave and move away" : "Fail"}</button>
                <button
                  className="rounded bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50"
                  disabled={pending || initiatorConfirmationRequired || (!confirmationPending && !canResolve)}
                  onClick={confirmationPending ? onConfirmCards : onResolve}
                  type="button"
                >
                  {initiatorConfirmationRequired ? "Waiting for initiator" : confirmationPending ? "Confirm cards" : canResolve ? "Resolve interaction" : "Select missing cards"}
                </button>
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

const SurpriseCardPanel = ({
  onResolve,
  onSkip,
  onToggleCard,
  pending,
  projection,
  selectedCapability,
  selectedCardIds,
}: {
  onResolve: () => void;
  onSkip: () => void;
  onToggleCard: (cardId: string) => void;
  pending: boolean;
  projection: GameProjection;
  selectedCapability: CapabilityProjection | null;
  selectedCardIds: string[];
}) => {
  const surprise = projection.pending_surprise;
  const card = surprise?.card;
  if (!card) return null;
  const selectedCards = (selectedCapability?.hand || []).filter((handCard) => selectedCardIds.includes(handCard.card_id));
  const costs = card.costs || [];
  const hasCost = costs.length > 0;
  const image = contentImageUrl(card);
  const interactionNames = projection.tile_catalog?.interactions || {};
  const categoryNames = projection.tile_catalog?.categories || {};
  return (
    <div className="absolute inset-4 z-50 flex items-center justify-center rounded-lg bg-slate-950/55">
      <div className="grid max-h-full w-[min(50rem,100%)] grid-cols-[14rem_1fr] gap-4 overflow-auto rounded-lg border border-cyan-300 bg-slate-900 p-4 shadow-2xl">
        <div>
          <h2 className="text-lg font-semibold text-white">Surprise card</h2>
          <p className="mt-1 text-sm text-cyan-100">{card.name}</p>
          {image ? <img alt="" className="mt-3 w-full rounded-md border border-slate-700 object-contain" src={image} /> : null}
        </div>
        <div className="space-y-3">
          <div className="rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-200">
            <h3 className="font-semibold text-white">{hasCost ? "Optional cost" : "Automatic effect"}</h3>
            <div className="mt-2 space-y-1">
              {costs.map((cost: any, index: number) => (
                <p key={index}>
                  {cost.type === "play_cards"
                    ? `Play ${cost.interaction_ids?.map((id: string) => interactionNames[id]?.name || id).join(", ")}`
                    : `Pay ${cost.amount || 1} AP${cost.capability_id ? ` from ${projection.capabilities?.[cost.capability_id]?.name || cost.capability_id}` : ""}`}
                </p>
              ))}
              {!hasCost ? <p>Resolve to apply the effects.</p> : null}
            </div>
          </div>
          <div className="rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-200">
            <h3 className="font-semibold text-white">Effects</h3>
            <div className="mt-2 space-y-1">
              {(card.effects || []).map((effect: any, index: number) => (
                <p key={index}>
                  {effect.type === "gain_ap" ? `Gain ${effect.amount} AP on ${projection.capabilities?.[effect.capability_id]?.name || effect.capability_id}` : null}
                  {effect.type === "gain_neurons" ? `Gain ${effect.amount} neurons` : null}
                  {effect.type === "advance_night" ? `Advance night by ${effect.amount} steps` : null}
                  {effect.type === "gain_energy" ? `Gain ${effect.amount} energy` : null}
                  {effect.type === "lose_energy" ? `Lose ${effect.amount} energy` : null}
                  {effect.type === "remove_tiles_category_here" ? `Remove ${categoryNames[effect.category_id]?.name || effect.category_id} tiles here` : null}
                  {effect.type === "remove_tiles_category_adjacent" ? `Remove ${categoryNames[effect.category_id]?.name || effect.category_id} tiles from adjacent nodes` : null}
                </p>
              ))}
            </div>
          </div>
          {hasCost ? (
            <div>
              <h3 className="text-sm font-semibold text-white">Focused hand</h3>
              <div className="mt-2 flex flex-wrap gap-2 rounded border border-dashed border-slate-700 bg-slate-950 p-2">
                {(selectedCapability?.hand || []).map((handCard) => (
                  <CardButton
                    card={handCard}
                    disabled={pending}
                    key={handCard.card_id}
                    onClick={() => onToggleCard(handCard.card_id)}
                    projection={projection}
                    selected={selectedCardIds.includes(handCard.card_id)}
                  />
                ))}
                {(selectedCapability?.hand || []).length === 0 ? <p className="m-auto text-sm text-slate-500">No cards in focused hand.</p> : null}
              </div>
              {selectedCards.length ? <p className="mt-1 text-xs text-cyan-100">{selectedCards.length} selected.</p> : null}
            </div>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            {hasCost ? <button className="rounded border border-slate-600 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50" disabled={pending} onClick={onSkip} type="button">Do not pay</button> : null}
            <button className="rounded bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending} onClick={onResolve} type="button">
              {hasCost ? "Pay and resolve" : "Resolve"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const BotPlansOverlay = ({
  botPlanStatus,
  loading,
  open,
  onClose,
  onRecalculate,
  projection,
}: {
  botPlanStatus: BotPlanStatus | null;
  loading: boolean;
  open: boolean;
  onClose: () => void;
  onRecalculate: () => void;
  projection: GameProjection;
}) => {
  const [expandedPlanId, setExpandedPlanId] = useState<string | null>(null);
  const activeName = projection.active_capability_id
    ? projection.capabilities?.[projection.active_capability_id]?.name || projection.active_capability_id
    : "No active ability";
  const plans = botPlanStatus?.proposals || [];
  const debug = botPlanStatus?.debug || {};

  if (!open) return null;
  return (
    <div className="absolute inset-3 z-[55] flex items-center justify-center rounded-lg bg-slate-950/55 p-3">
      <section className="flex max-h-full w-[min(56rem,100%)] flex-col overflow-hidden rounded-lg border border-cyan-300 bg-slate-900 p-4 shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-cyan-200">Bot planning</p>
            <h2 className="mt-1 text-xl font-semibold text-white">{phaseLabel(projection)}</h2>
            <p className="mt-1 text-sm text-slate-300">
              Current initiative: {activeName}. Proposals are generated server-side from the current room version.
            </p>
          </div>
          <div className="flex gap-2">
            <button className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800" onClick={onRecalculate} type="button">
              Recalculate plans
            </button>
            <button className="rounded border border-slate-600 px-3 py-2 text-xs text-slate-100 hover:bg-slate-800" onClick={onClose} type="button">
              Close
            </button>
          </div>
        </div>
        <div className="mt-4 min-h-0 overflow-auto pr-2 [scrollbar-gutter:stable]">
          {loading ? <p className="rounded-md border border-slate-700 bg-slate-950 p-4 text-sm text-slate-300">Bots are evaluating the current state...</p> : null}
          {!loading && botPlanStatus?.message ? <p className="rounded-md border border-slate-700 bg-slate-950 p-4 text-sm text-slate-300">{botPlanStatus.message}</p> : null}
          {!loading && plans.length ? (
          <div className="grid gap-3 md:grid-cols-3">
          {plans.map((plan) => {
            const proposerName = plan.proposer_ability_id ? projection.capabilities?.[plan.proposer_ability_id]?.name || plan.proposer_ability_id : "Team";
            const resources = plan.expected_resources || {};
            const apCost = Object.values(resources.ap_by_ability || {}).reduce((total, value) => total + Number(value || 0), 0);
            const controlTakes = Object.values(resources.control_takes_by_ability || {}).reduce((total, value) => total + Number(value || 0), 0);
            const stats = plan.statistics || {};
            const successPercent = Math.round(Number(stats.success_probability ?? plan.confidence ?? 1) * 100);
            const expectedDelta = resources.expected_resource_delta || stats.expected_resource_delta || {};
            const expectedDeltaText = Object.entries(expectedDelta)
              .filter(([, value]) => Number(value || 0) !== 0)
              .map(([key, value]) => `${Number(value) > 0 ? "+" : ""}${Number(value)} ${String(key).replaceAll("_", " ")}`)
              .join(", ");
            const expanded = expandedPlanId === plan.plan_id;
            return (
              <article className="flex min-h-[18rem] flex-col rounded-md border border-slate-700 bg-slate-950 p-3" key={plan.plan_id}>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-cyan-200">{proposerName}</p>
                  <h3 className="mt-1 text-base font-semibold text-white">{plan.title}</h3>
                  <p className="mt-1 text-xs text-amber-200">{plan.risk_label}</p>
                  <p className="mt-3 text-sm leading-5 text-slate-300">{plan.rationale}</p>
                </div>
                <div className="mt-3 rounded border border-slate-800 bg-slate-900 p-2 text-xs text-slate-300">
                  <p><span className="text-slate-500">Public cost:</span> {apCost} AP, {Number(resources.time_steps || 0)} time, {controlTakes} controls</p>
                  <p className="mt-1"><span className="text-slate-500">Estimated success:</span> {successPercent}%</p>
                  {resources.expected_ap_gain_by_ability ? <p className="mt-1"><span className="text-slate-500">Expected AP:</span> {Object.entries(resources.expected_ap_gain_by_ability).map(([abilityId, value]) => `${projection.capabilities?.[abilityId]?.name || abilityId} +${Number(value || 0)}`).join(", ")}</p> : null}
                  {expectedDeltaText ? <p className="mt-1"><span className="text-slate-500">EV:</span> {expectedDeltaText}</p> : null}
                  {plan.objective_effect ? <p className="mt-1"><span className="text-slate-500">Objective:</span> {plan.objective_effect}</p> : null}
                </div>
                <ol className="mt-3 flex-1 space-y-1 text-xs text-slate-300">
                  {plan.step_preview.map((step, index) => (
                    <li key={`${plan.plan_id}:step:${index}`}>{index + 1}. {step}</li>
                  ))}
                </ol>
                {(plan.warnings || []).length ? <p className="mt-3 text-xs text-amber-200">{plan.warnings?.join(" ")}</p> : null}
                <button
                  className="mt-3 rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-900"
                  onClick={() => setExpandedPlanId(expanded ? null : plan.plan_id)}
                  type="button"
                >
                  {expanded ? "Hide details" : "Details"}
                </button>
                {expanded ? (
                  <div className="mt-2 max-h-56 overflow-auto rounded border border-slate-800 bg-slate-900 p-2 text-xs text-slate-300">
                    <p>
                      <span className="text-slate-500">Depth:</span> {Number(stats.planning_depth_take_controls || 0)} controls, {Number(stats.estimated_actions || 0)} actions, {Number(stats.estimated_time_steps || 0)} time
                    </p>
                    <div className="mt-2 grid gap-1 sm:grid-cols-3">
                      <p className="rounded bg-slate-950 px-2 py-1"><span className="text-slate-500">Efficiency:</span> {Math.round(Number(stats.efficiency ?? 1) * 100)}%</p>
                      <p className="rounded bg-slate-950 px-2 py-1"><span className="text-slate-500">Confidence:</span> {Math.round(Number(stats.confidence_score ?? successPercent / 100) * 100)}%</p>
                      <p className="rounded bg-slate-950 px-2 py-1"><span className="text-slate-500">Score:</span> {Math.round(Number(stats.expected_gain_score || 0))}</p>
                    </div>
                    <p className="mt-1 text-[0.68rem] text-slate-400">
                      Planner score {Number(stats.planner_score || 0).toFixed(1)}
                      {Number(stats.wasted_current_actions || 0) > 0 ? `; ${Number(stats.wasted_current_actions || 0)} current action(s) would be left unused by switching initiative` : ""}
                    </p>
                    {stats.distance_to_closest_known_shelter !== undefined ? (
                      <p className="mt-1"><span className="text-slate-500">Shelter distance:</span> {stats.distance_to_closest_known_shelter}</p>
                    ) : null}
                    {stats.surprise_card ? (
                      <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <strong className="text-slate-100">{stats.surprise_card?.name || "Surprise"}</strong>
                          <span className="text-cyan-200">{stats.surprise_resolution || "resolve"}</span>
                        </div>
                        {(stats.surprise_costs || []).length ? <p className="mt-1"><span className="text-slate-500">Cost:</span> {(stats.surprise_costs || []).join("; ")}</p> : null}
                        {(stats.surprise_effects || []).length ? <p className="mt-1"><span className="text-slate-500">Effects:</span> {(stats.surprise_effects || []).join(", ")}</p> : null}
                        {Object.keys(stats.surprise_delta || {}).length ? <p className="mt-1"><span className="text-slate-500">Projected:</span> {Object.entries(stats.surprise_delta || {}).map(([key, value]) => `${Number(value) > 0 ? "+" : ""}${Number(value)} ${String(key).replaceAll("_", " ")}`).join(", ")}</p> : null}
                      </div>
                    ) : null}
                    {stats.support_estimate ? (
                      <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <strong className="text-slate-100">{stats.support_estimate.ability_name || "Support"}</strong>
                          <span className="text-cyan-200">{Math.round(Number(stats.support_estimate.probability || 0) * 100)}%</span>
                        </div>
                        {(stats.support_estimate.missing_requirements || []).length ? <p className="mt-1"><span className="text-slate-500">Missing:</span> {(stats.support_estimate.missing_requirements || []).join(", ")}</p> : null}
                        <p className="mt-1">
                          <span className="text-slate-500">Coverage:</span> {Number(stats.support_estimate.hand_matches || 0)} in hand, {Number(stats.support_estimate.known_future_matches || 0)} in deck/discard
                          {stats.support_estimate.is_human ? ", human-controlled" : ""}
                        </p>
                      </div>
                    ) : null}
                    {(stats.interaction_summaries || []).length ? (
                      <div className="mt-2 space-y-2">
                        {(stats.interaction_summaries || []).map((entry: any) => (
                          <article className="rounded border border-slate-800 bg-slate-950 p-2" key={entry.tile_instance_id || entry.tile_name}>
                            <div className="flex items-center justify-between gap-2">
                              <strong className="text-slate-100">{entry.tile_name || "Tile"}</strong>
                              <span className="text-cyan-200">{Math.round(Number(entry.success_probability || 0) * 100)}%</span>
                            </div>
                            <p className="mt-1"><span className="text-slate-500">Needs:</span> {(entry.requirements || []).join(", ")}</p>
                            {(entry.actor_candidates || []).length ? <p className="mt-1"><span className="text-slate-500">Actors:</span> {(entry.actor_candidates || []).map((candidate: any) => `${candidate.ability_name}${candidate.covers_required_cards_from_hand ? " covers" : ""}`).join("; ")}</p> : null}
                            <p className="mt-1"><span className="text-slate-500">Success:</span> {(entry.success_effects || []).join(", ")}</p>
                            <p className="mt-1"><span className="text-slate-500">Failure:</span> {(entry.failure_effects || []).join(", ")}</p>
                            {entry.expected_delta ? <p className="mt-1"><span className="text-slate-500">EV:</span> {Object.entries(entry.expected_delta).map(([key, value]) => `${Number(value) > 0 ? "+" : ""}${Number(value)} ${String(key).replaceAll("_", " ")}`).join(", ") || "none"}</p> : null}
                          </article>
                        ))}
                      </div>
                    ) : (stats.interaction_probabilities || []).length ? (
                      <div className="mt-2 space-y-1">
                        {(stats.interaction_probabilities || []).map((entry: any) => (
                          <p key={entry.tile_instance_id || entry.tile_name}>
                            {entry.tile_name || "Tile"}: {Math.round(Number(entry.success_probability || 0) * 100)}%
                            {entry.counter_attack_probability !== null && entry.counter_attack_probability !== undefined
                              ? `, counter ${Math.round(Number(entry.counter_attack_probability || 0) * 100)}%`
                              : ""}
                          </p>
                        ))}
                      </div>
                    ) : null}
                    {(plan.plan_chain || []).length ? (
                      <PlanDetailTree plan={plan} projection={projection} />
                    ) : null}
                    {(stats.assumptions || []).length ? <p className="mt-2 text-slate-400">{(stats.assumptions || []).join(" ")}</p> : null}
                  </div>
                ) : null}
              </article>
            );
          })}
          </div>
          ) : null}
          {!loading && Object.keys(debug).length ? (
            <section className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-slate-800">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-amber-950">Planner debug</h3>
                <span className="text-[0.68rem] text-amber-800">Version {botPlanStatus?.generated_from_version ?? "-"}</span>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                <p><span className="font-semibold">Generated:</span> {Number(debug.generated_count ?? debug.raw_generated_count ?? 0)}</p>
                <p><span className="font-semibold">Frontier:</span> {Number(debug.frontier_count ?? 0)}</p>
                <p><span className="font-semibold">Selected:</span> {Number(debug.selected_count ?? plans.length)}</p>
                <p><span className="font-semibold">Limit:</span> {Number(debug.max_public_plans ?? 0)} ({Number(debug.max_plans_per_proposer ?? 0)}/bot)</p>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-3">
                <p><span className="font-semibold">Generated by:</span> {Object.entries(debug.generated_by_proposer || {}).map(([key, value]) => `${projection.capabilities?.[key]?.name || key}: ${Number(value)}`).join(", ") || "-"}</p>
                <p><span className="font-semibold">Selected by:</span> {Object.entries(debug.selected_by_proposer || {}).map(([key, value]) => `${projection.capabilities?.[key]?.name || key}: ${Number(value)}`).join(", ") || "-"}</p>
                <p><span className="font-semibold">Selected depths:</span> {Object.entries(debug.selected_depths || {}).map(([key, value]) => `${key}: ${Number(value)}`).join(", ") || "-"}</p>
                <p><span className="font-semibold">Generated depths:</span> {Object.entries(debug.generated_depths || {}).map(([key, value]) => `${key}: ${Number(value)}`).join(", ") || "-"}</p>
              </div>
              {(debug.selected || []).length ? (
                <div className="mt-3">
                  <p className="font-semibold text-amber-950">Selected stop reasons</p>
                  <div className="mt-1 grid gap-1 md:grid-cols-2">
                    {(debug.selected || []).map((entry: any, index: number) => (
                      <p className="rounded border border-amber-200 bg-white px-2 py-1" key={`${entry.plan_id || "selected"}:${index}`}>
                        <span className="font-semibold">{projection.capabilities?.[entry.proposer_ability_id]?.name || entry.proposer_ability_id || "Team"}</span>
                        {` depth ${Number(entry.depth || 0)}: ${entry.rollout_stop_reason || entry.last_step || "no stop reason"}`}
                      </p>
                    ))}
                  </div>
                </div>
              ) : null}
              {(debug.pruned || []).length ? (
                <details className="mt-3">
                  <summary className="cursor-pointer font-semibold text-amber-950">Pruned / not selected ({(debug.pruned || []).length} shown)</summary>
                  <div className="mt-1 grid gap-1 md:grid-cols-2">
                    {(debug.pruned || []).map((entry: any, index: number) => (
                      <p className="rounded border border-amber-200 bg-white px-2 py-1" key={`${entry.plan_id || "pruned"}:${index}`}>
                        <span className="font-semibold">{projection.capabilities?.[entry.proposer_ability_id]?.name || entry.proposer_ability_id || "Team"}</span>
                        {` depth ${Number(entry.depth || 0)} score ${Number(entry.score || 0).toFixed(1)}: ${entry.rollout_stop_reason || entry.last_step || entry.title || "no detail"}`}
                      </p>
                    ))}
                  </div>
                </details>
              ) : null}
            </section>
          ) : null}
        </div>
      </section>
    </div>
  );
};

type PlanChainStep = {
  label: string;
  command_type?: string | null;
  public_command?: {
    type: string;
    payload?: Record<string, unknown>;
  } | null;
  auto_executable?: boolean;
  decision_boundary?: boolean;
  statistics?: Record<string, any>;
};

type BotLogEntry = {
  id: string;
  text: string;
  createdAt: number;
  status?: string;
};

type PlanTreeOption = {
  key: string;
  label: string;
  compactLabel: string;
  step: PlanChainStep;
  depth: number;
  public_command?: {
    type: string;
    payload?: Record<string, unknown>;
  } | null;
  planIds: string[];
  proposerIds: string[];
  avgSuccess: number;
  avgEfficiency: number;
  avgPlannerScore: number;
  avgExpectedGain: number;
  expectedDelta: Record<string, number>;
  preferred: boolean;
};

const commandKey = (command?: { type: string; payload?: Record<string, unknown> } | null) => {
  if (!command) return "";
  const payload = command.payload || {};
  const sortedPayload = Object.fromEntries(Object.entries(payload).sort(([left], [right]) => left.localeCompare(right)));
  return `${command.type}:${JSON.stringify(sortedPayload)}`;
};

const stepKey = (step?: PlanChainStep) => {
  if (!step) return "";
  return step.public_command ? commandKey(step.public_command) : `label:${step.label}`;
};

const mergePlanDeltas = (plans: BotPlanSummary[]) => {
  const delta: Record<string, number> = {};
  plans.forEach((plan) => {
    const planDelta = plan.expected_resources?.expected_resource_delta || plan.statistics?.expected_resource_delta || {};
    Object.entries(planDelta).forEach(([key, value]) => {
      delta[key] = Number((delta[key] || 0) + Number(value || 0));
    });
  });
  Object.keys(delta).forEach((key) => {
    delta[key] = Math.round((delta[key] / Math.max(1, plans.length)) * 100) / 100;
    if (!delta[key]) delete delta[key];
  });
  return delta;
};

const stepStatistics = (plan: BotPlanSummary, stepIndex: number) => plan.plan_chain?.[stepIndex]?.statistics || plan.statistics || {};

const planOptionMetrics = (optionPlans: BotPlanSummary[], stepIndex: number) => {
  const successValues = optionPlans.map((plan) => Number(stepStatistics(plan, stepIndex)?.confidence_score ?? plan.statistics?.success_probability ?? plan.confidence ?? 1));
  const avgSuccess = successValues.reduce((total, value) => total + value, 0) / Math.max(1, successValues.length);
  const efficiencyValues = optionPlans.map((plan) => Number(stepStatistics(plan, stepIndex)?.efficiency ?? 1));
  const plannerScoreValues = optionPlans.map((plan) => Number(plan.statistics?.planner_score ?? 0));
  const expectedGainValues = optionPlans.map((plan) => Number(stepStatistics(plan, stepIndex)?.expected_gain_score ?? plan.statistics?.expected_gain_score ?? 0));
  return {
    avgSuccess,
    avgEfficiency: efficiencyValues.reduce((total, value) => total + value, 0) / Math.max(1, efficiencyValues.length),
    avgPlannerScore: plannerScoreValues.reduce((total, value) => total + value, 0) / Math.max(1, plannerScoreValues.length),
    avgExpectedGain: expectedGainValues.reduce((total, value) => total + value, 0) / Math.max(1, expectedGainValues.length),
    expectedDelta: mergePlanDeltas(optionPlans),
  };
};

const deltaText = (delta: Record<string, number>) =>
  Object.entries(delta)
    .filter(([, value]) => Number(value || 0) !== 0)
    .map(([key, value]) => `${Number(value) > 0 ? "+" : ""}${Number(value)} ${String(key).replaceAll("_", " ")}`)
    .join(", ");

const abilityInitial = (projection: GameProjection, abilityId?: unknown) => {
  const id = typeof abilityId === "string" ? abilityId : "";
  const name = projection.capabilities?.[id]?.name || id || "?";
  return String(name).trim().slice(0, 1).toUpperCase() || "?";
};

const tileForInstance = (projection: GameProjection, tileInstanceId?: unknown) => {
  const instanceId = typeof tileInstanceId === "string" ? tileInstanceId : "";
  if (!instanceId) return null;
  for (const nodeTiles of Object.values(projection.tiles || {})) {
    const instance = (nodeTiles || []).find((entry: any) => entry?.instance_id === instanceId);
    if (!instance?.tile_id) continue;
    return projection.tile_catalog?.tiles?.[instance.tile_id] || null;
  }
  return null;
};

const tileNameForInstance = (projection: GameProjection, tileInstanceId?: unknown) => {
  const tile = tileForInstance(projection, tileInstanceId);
  if (tile) return tile?.event?.name || tile?.name || tile?.id || "tile";
  return "tile";
};

const abilityColor = (projection: GameProjection, abilityId?: unknown) => {
  const id = typeof abilityId === "string" ? abilityId : "";
  const colors = projection.tile_catalog?.bot_settings?.ability_colors || {};
  const fallback: Record<string, string> = {
    agility: "#0ea5e9",
    camouflage: "#16a34a",
    force: "#dc2626",
    propulsion: "#7c3aed",
    intelligence: "#f59e0b",
  };
  return String(colors[id] || fallback[id] || "#0891b2");
};

const actionVisual = (step: PlanChainStep, projection: GameProjection) => {
  const command = step.public_command;
  const payload = command?.payload || {};
  const actorId = typeof payload.capability_id === "string" ? payload.capability_id : "";
  const type = command?.type || step.command_type || "";
  const tile = type === "start_interaction" ? tileForInstance(projection, payload.tile_instance_id) : null;
  const tileImage = tile?.event?.image_url || tile?.image_url;
  if (type === "start_interaction" && tileImage) {
    return { actorId, imageUrl: buildApiUrl(tileImage), text: "", Icon: Swords, title: `Interact ${tileNameForInstance(projection, payload.tile_instance_id)}` };
  }
  if (type === "take_control") return { actorId, text: "Take", Icon: Hand, title: "Take initiative" };
  if (type === "collect_action_points") return { actorId, text: "AP", Icon: CirclePlus, title: "Collect AP" };
  if (type === "move_poulpita") return { actorId, text: String(payload.target_node_id || ""), Icon: MoveRight, title: `Move ${payload.target_node_id || ""}` };
  if (type === "draw_action_card") return { actorId, text: "Draw", Icon: Sparkles, title: "Draw card" };
  if (type === "start_interaction") return { actorId, text: "Fight", Icon: Swords, title: `Interact ${tileNameForInstance(projection, payload.tile_instance_id)}` };
  if (type === "resolve_interaction") return { actorId, text: "OK", Icon: Check, title: "Commit cards" };
  if (type === "fail_interaction") return { actorId, text: "Fail", Icon: X, title: "Fail interaction" };
  if (type === "resolve_surprise_card") return { actorId, text: payload.accept === false ? "Skip" : "Surp", Icon: Sparkles, title: payload.accept === false ? "Skip surprise" : "Resolve surprise" };
  if (type === "end_night") return { actorId, text: "Night", Icon: Moon, title: "End night" };
  if (type === "end_day") return { actorId, text: "Day", Icon: Moon, title: "End day" };
  if (type === "move_seashell_to_shelter" || type === "move_seashell_from_shelter") return { actorId, text: "Shell", Icon: RefreshCw, title: compactPlanStepLabel(step, projection) };
  if (type === "buy_hand_size_upgrade") return { actorId, text: "Up", Icon: CirclePlus, title: "Buy upgrade" };
  if (type === "buy_poulpita_size") return { actorId, text: "Size", Icon: CirclePlus, title: "Grow Poulpita" };
  return { actorId, text: "Plan", Icon: RefreshCw, title: compactPlanStepLabel(step, projection) };
};

const compactPlanStepLabel = (step: PlanChainStep, projection: GameProjection) => {
  const command = step.public_command;
  const payload = command?.payload || {};
  const actor = abilityInitial(projection, payload.capability_id);
  switch (command?.type || step.command_type || "") {
    case "take_control":
      return `${actor} Take control`;
    case "collect_action_points":
      return `${actor} Collect AP`;
    case "move_poulpita":
      return `${actor} Move ${payload.target_node_id || "?"}`;
    case "draw_action_card":
      return `${actor} Draw`;
    case "start_interaction":
      return `${actor} Interact ${tileNameForInstance(projection, payload.tile_instance_id)}`;
    case "resolve_interaction":
      return `${actor} Commit cards`;
    case "fail_interaction":
      return "Fail interaction";
    case "resolve_surprise_card":
      return payload.accept === false ? "Skip surprise" : payload.capability_id ? `${actor} Resolve surprise` : "Resolve surprise";
    case "end_day":
      return "End day";
    case "end_night":
      return `${actor} End night`;
    case "move_seashell_to_shelter":
      return "Store shell";
    case "move_seashell_from_shelter":
      return "Take shell";
    case "buy_hand_size_upgrade":
      return `${actor} Buy upgrade`;
    case "buy_poulpita_size":
      return "Grow size";
    default:
      return String(step.label || "Decision").replace(/^Use expected AP to /, "").slice(0, 34);
  }
};

const PlanActionNode = ({
  option,
  projection,
  pending,
  selected,
  onSelect,
  onExecute,
}: {
  option: PlanTreeOption;
  projection: GameProjection;
  pending: boolean;
  selected: boolean;
  onSelect: (option: PlanTreeOption) => void;
  onExecute: (option: PlanTreeOption) => void;
}) => {
  const visual = actionVisual(option.step, projection);
  const color = abilityColor(projection, visual.actorId);
  const Icon = visual.Icon;
  const initials = option.proposerIds.length ? option.proposerIds.map((id) => abilityInitial(projection, id)).join("") : abilityInitial(projection, visual.actorId);
  const disabled = pending || (!option.public_command && option.planIds.length === 0);
  return (
    <button
      className={[
        "group flex shrink-0 items-center gap-1.5 rounded-full bg-transparent p-0.5 text-left transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60",
        selected ? "rounded-xl bg-amber-200/40 drop-shadow-[0_0_16px_rgba(251,191,36,0.95)] ring-4 ring-amber-300/80" : "",
      ].join(" ")}
      disabled={disabled}
      onClick={() => onSelect(option)}
      onDoubleClick={() => onExecute(option)}
      title={visual.title}
      type="button"
    >
      <span
        className="relative flex h-12 w-12 shrink-0 items-center justify-center overflow-visible rounded-full border-[3px] bg-white text-slate-900"
        style={{ borderColor: selected ? "#f59e0b" : color, boxShadow: selected ? `0 0 0 4px ${color}, 0 0 18px rgba(245,158,11,0.95)` : undefined }}
      >
        <span
          className="absolute -top-2 left-1/2 flex h-5 min-w-5 -translate-x-1/2 items-center justify-center rounded-full border border-white px-1 text-[0.56rem] font-bold text-white shadow"
          style={{ backgroundColor: color }}
        >
          {initials.slice(0, 3)}
        </span>
        {visual.imageUrl ? (
          <img alt="" className="h-full w-full rounded-full object-cover" src={visual.imageUrl} />
        ) : (
          <span className="flex h-full w-full flex-col items-center justify-center gap-0.5 rounded-full bg-cyan-50 px-1 text-center">
            <Icon className="h-5 w-5" aria-hidden />
            <span className="max-w-[2.5rem] truncate text-[0.52rem] font-bold leading-none">{visual.text}</span>
          </span>
        )}
      </span>
      <span className={["grid w-12 shrink-0 gap-0.5 rounded-md border px-1.5 py-1 text-[0.5rem] leading-none shadow", selected ? "border-amber-300 bg-white text-slate-950 ring-2 ring-amber-200" : "border-slate-700 bg-slate-950/85 text-slate-200"].join(" ")}>
        <span>Eff {Math.round(option.avgEfficiency * 100)}%</span>
        <span>Risk {Math.round((1 - option.avgSuccess) * 100)}%</span>
        <span>Score {Math.round(option.avgExpectedGain)}</span>
      </span>
    </button>
  );
};

const PlanDetailTree = ({ plan, projection }: { plan: BotPlanSummary; projection: GameProjection }) => {
  const resources = plan.expected_resources || {};
  const expectedDelta = resources.expected_resource_delta || plan.statistics?.expected_resource_delta || {};
  return (
    <div className="mt-3 space-y-2">
      <p className="text-[0.65rem] font-semibold uppercase tracking-wide text-slate-400">Computed tree</p>
      <div className="space-y-1.5">
        {(plan.plan_chain || []).map((step, index) => {
          const visual = actionVisual(step, projection);
          const color = abilityColor(projection, visual.actorId);
          const Icon = visual.Icon;
          const stats = step.statistics || {};
          const components = stats.global_score_components || {};
          const efficiency = Math.round(Number(stats.efficiency ?? 1) * 100);
          const risk = Math.round(Number(stats.risk_score ?? 1 - Number(stats.confidence_score ?? plan.statistics?.success_probability ?? 1)) * 100);
          const gain = Math.round(Number(stats.expected_gain_score ?? plan.statistics?.expected_gain_score ?? 0));
          return (
            <div className="group relative flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950 p-1.5" key={`${plan.plan_id}_tree_${index}`}>
              <span
                className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-[3px] bg-white text-slate-900"
                style={{ borderColor: color }}
              >
                <span className="absolute -top-2 left-1/2 flex h-4 min-w-4 -translate-x-1/2 items-center justify-center rounded-full border border-white px-1 text-[0.5rem] font-bold text-white" style={{ backgroundColor: color }}>
                  {abilityInitial(projection, visual.actorId)}
                </span>
                {visual.imageUrl ? (
                  <img alt="" className="h-full w-full rounded-full object-cover" src={visual.imageUrl} />
                ) : (
                  <span className="flex h-full w-full flex-col items-center justify-center rounded-full bg-cyan-50">
                    <Icon className="h-4 w-4" aria-hidden />
                    <span className="max-w-[2rem] truncate text-[0.48rem] font-bold leading-none">{visual.text}</span>
                  </span>
                )}
              </span>
              <span className="grid w-12 shrink-0 gap-0.5 text-[0.5rem] leading-none text-slate-300">
                <span>Eff {efficiency}%</span>
                <span>Risk {risk}%</span>
                <span>Score {gain}</span>
              </span>
              <span className="truncate text-[0.65rem] text-slate-300">{index + 1}. {compactPlanStepLabel(step, projection)}</span>
              <div className="pointer-events-none absolute left-16 top-9 z-[80] hidden w-64 rounded-md border border-cyan-300 bg-slate-950 p-2 text-[0.65rem] text-slate-300 shadow-xl group-hover:block">
                <p className="font-semibold text-white">{compactPlanStepLabel(step, projection)}</p>
                <p className="mt-1 text-slate-400">{step.label}</p>
                <p className="mt-2">Efficiency {efficiency}% - Risk {risk}% - Score {gain}</p>
                {Object.keys(components).length ? (
                  <p className="mt-1">
                    Energy {Number(components.energy || 0)}, neurons {Number(components.neurons || 0)}, hand {Number(components.cards_in_hand || 0)}, upgrades {Number(components.purchased_upgrades || 0)}, size {Number(components.size_index || 0)}
                  </p>
                ) : null}
                <p className="mt-1">Used {Number(stats.planned_actions_used || 0)} / {Number(stats.planned_action_capacity || 0)} planned actions.</p>
                {Number(stats.wasted_current_actions || 0) > 0 ? <p className="mt-1 text-amber-200">{Number(stats.wasted_current_actions || 0)} current action(s) left unused by initiative switch.</p> : null}
                {deltaText(expectedDelta) ? <p className="mt-1">EV: {deltaText(expectedDelta)}</p> : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const BotPlanTree = ({
  plans,
  activePlanIds,
  collapsed,
  stepIndex,
  preferredPlanId,
  pending,
  onToggleCollapsed,
  onSelectOption,
  onExecuteOption,
  projection,
}: {
  plans: BotPlanSummary[];
  activePlanIds: string[];
  collapsed: boolean;
  stepIndex: number;
  preferredPlanId: string | null;
  pending: boolean;
  onToggleCollapsed: () => void;
  onSelectOption: (option: PlanTreeOption) => void;
  onExecuteOption: (option: PlanTreeOption) => void;
  projection: GameProjection;
}) => {
  if (!plans.length) return null;
  const activeIdSet = new Set(activePlanIds);
  const preferredPlan = plans.find((plan) => plan.plan_id === preferredPlanId) || null;
  const maxVisibleDepth = Math.max(0, Math.min(7, Math.max(...plans.map((plan) => (plan.plan_chain || []).length), 1) - 1));
  const planMatchesSelectedPath = (plan: BotPlanSummary, depth: number) => {
    if (depth === 0) return true;
    if (!preferredPlan) return !activePlanIds.length || activeIdSet.has(plan.plan_id);
    const selectedPathDepth = Math.max(0, Math.min(depth, stepIndex));
    for (let index = 0; index < selectedPathDepth; index += 1) {
      if (stepKey(plan.plan_chain?.[index]) !== stepKey(preferredPlan.plan_chain?.[index])) return false;
    }
    return true;
  };
  const optionsForDepth = (depth: number): PlanTreeOption[] => {
    const groups = new Map<string, { step: PlanChainStep; plans: BotPlanSummary[] }>();
    const sourcePlans = plans.filter((plan) => planMatchesSelectedPath(plan, depth));
    sourcePlans.forEach((plan) => {
      const step = plan.plan_chain?.[depth];
      if (!step) return;
      const key = stepKey(step);
      if (!groups.has(key)) groups.set(key, { step, plans: [] });
      groups.get(key)?.plans.push(plan);
    });
    return Array.from(groups.entries()).map(([key, entry]) => {
      const metrics = planOptionMetrics(entry.plans, depth);
      return {
        key,
        label: entry.step.label,
        compactLabel: compactPlanStepLabel(entry.step, projection),
        step: entry.step,
        depth,
        public_command: entry.step.public_command || null,
        planIds: entry.plans.map((plan) => plan.plan_id),
        proposerIds: Array.from(new Set(entry.plans.map((plan) => plan.proposer_ability_id).filter(Boolean) as string[])),
        preferred: entry.plans.some((plan) => plan.plan_id === preferredPlanId),
        ...metrics,
      };
    }).sort((left, right) => right.avgPlannerScore - left.avgPlannerScore);
  };
  const selectedDepth = Math.max(0, Math.min(stepIndex - 1, maxVisibleDepth));
  const selectedOptions = optionsForDepth(selectedDepth);
  const selectedOption = selectedOptions.find((option) => option.preferred) || selectedOptions[0] || null;
  return (
    <div className="absolute left-3 top-3 z-[45] w-max max-w-none overflow-visible p-0">
      <div className="flex items-center justify-between gap-2">
        <button className="rounded bg-white/90 px-2 py-1 text-[0.65rem] font-semibold uppercase tracking-wide text-slate-950 shadow hover:bg-cyan-50" onClick={onToggleCollapsed} type="button">
          Planning tree
        </button>
        {!collapsed ? (
          <button
            className="rounded bg-teal-400 px-2 py-1 text-[0.62rem] font-semibold uppercase tracking-wide text-slate-950 shadow hover:bg-teal-300 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pending || !selectedOption?.public_command}
            onClick={() => selectedOption && onExecuteOption(selectedOption)}
            type="button"
          >
            Execute
          </button>
        ) : null}
      </div>
      {collapsed ? null : (
      <div className="mt-2 space-y-2">
        {Array.from({ length: maxVisibleDepth + 1 }).map((_, depth) => {
          const depthOptions = optionsForDepth(depth);
          return (
            <div className="min-w-max" key={depth}>
              <div className="flex min-w-max items-center gap-2">
                {depthOptions.map((option) => (
                  <PlanActionNode
                    key={`${depth}:${option.key}`}
                    onExecute={onExecuteOption}
                    onSelect={onSelectOption}
                    option={option}
                    pending={pending}
                    projection={projection}
                    selected={option.preferred}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      )}
    </div>
  );
};

const BotActionLog = ({
  entries,
  logOpen,
  popups,
  onToggle,
}: {
  entries: BotLogEntry[];
  logOpen: boolean;
  popups: BotLogEntry[];
  onToggle: () => void;
}) => (
  <div className="absolute right-3 top-[3.65rem] z-[45] flex w-72 flex-col items-end">
    <button className="w-28 rounded-full border border-cyan-300 bg-slate-900 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-cyan-100 shadow-lg hover:bg-slate-800" onClick={onToggle} type="button">
      {logOpen ? "Close log" : "Log"}
    </button>
    <div className="pointer-events-none mt-2 flex w-full flex-col gap-2">
      {popups.map((entry) => (
        <div
          className={[
            "rounded-md border px-3 py-2 text-xs shadow-lg transition",
            entry.status === "ok" ? "border-teal-300 bg-teal-950/95 text-teal-100" : "border-amber-300 bg-amber-950/95 text-amber-100",
          ].join(" ")}
          key={entry.id}
        >
          {entry.text}
        </div>
      ))}
    </div>
    {logOpen ? (
      <div className="mt-2 max-h-[42vh] w-full overflow-auto rounded-lg border border-slate-700 bg-slate-950/95 p-2 text-xs text-slate-300 shadow-xl">
        {entries.length ? (
          entries.map((entry) => (
            <p className="border-b border-slate-800 py-1.5 last:border-b-0" key={entry.id}>
              {new Date(entry.createdAt).toLocaleTimeString()} - {entry.text}
            </p>
          ))
        ) : (
          <p className="py-2 text-slate-500">No bot actions yet.</p>
        )}
      </div>
    ) : null}
  </div>
);

const GameRoomPage = () => {
  const { roomId } = useParams();
  const { token, user } = useStore();
  const navigate = useNavigate();
  const socketRef = useRef<WebSocket | null>(null);
  const orchestratorPendingRef = useRef(false);
  const pendingPlanContinuationRef = useRef<{ expectedCommand: { type: string; payload?: Record<string, unknown> } | null; previousPlanIds: string[] } | null>(null);
  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [levels, setLevels] = useState<Array<any>>([]);
  const [focusedCapabilityId, setFocusedCapabilityId] = useState<string | null>(null);
  const [moveMode, setMoveMode] = useState(false);
  const [specialTargetMode, setSpecialTargetMode] = useState<"intelligence" | "propulsion" | "camouflage" | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [selectedTileInstanceId, setSelectedTileInstanceId] = useState<string | null>(null);
  const [selectedCardIds, setSelectedCardIds] = useState<string[]>([]);
  const [surpriseSelectedCardIds, setSurpriseSelectedCardIds] = useState<string[]>([]);
  const [discardBeforeDraw, setDiscardBeforeDraw] = useState(false);
  const [failMoveTargetNodeId, setFailMoveTargetNodeId] = useState("");
  const [interactionPanelState, setInteractionPanelState] = useState<"open" | "success" | "failure" | "closing">("open");
  const [alertsVisible, setAlertsVisible] = useState(false);
  const [botPlansOpen, setBotPlansOpen] = useState(false);
  const [botPlanTreeCollapsed, setBotPlanTreeCollapsed] = useState(false);
  const [botPlanStatus, setBotPlanStatus] = useState<BotPlanStatus | null>(null);
  const [botPlansLoading, setBotPlansLoading] = useState(false);
  const [activePlanIds, setActivePlanIds] = useState<string[]>([]);
  const [planStepIndex, setPlanStepIndex] = useState(0);
  const [preferredPlanId, setPreferredPlanId] = useState<string | null>(null);
  const [botLogEntries, setBotLogEntries] = useState<BotLogEntry[]>([]);
  const [botLogPopups, setBotLogPopups] = useState<BotLogEntry[]>([]);
  const [botLogOpen, setBotLogOpen] = useState(false);
  const [botsOnlyPaused, setBotsOnlyPaused] = useState(false);
  const [orchestratorRunning, setOrchestratorRunning] = useState(false);
  const [orchestratorElapsedSeconds, setOrchestratorElapsedSeconds] = useState(0);

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
  const botsOnlyMode = projection?.mode === "bots_only" && Boolean(projection?.bot_config);
  const botModeEnabled = projection?.mode === "solo_with_bots" && Boolean(projection?.bot_config);
  const botLogEnabled = botModeEnabled || botsOnlyMode;
  const gameplayPending = pending || botsOnlyMode;
  const activePlanTreePlans = useMemo(() => {
    const proposals = botPlanStatus?.proposals || [];
    if (!activePlanIds.length) return [];
    const activeIds = new Set(activePlanIds);
    return proposals.filter((plan) => activeIds.has(plan.plan_id));
  }, [activePlanIds, botPlanStatus?.proposals]);

  const pushBotLog = useCallback((text: string, status: string = "ok") => {
    const entry = { id: makeCommandId(), text, createdAt: Date.now(), status };
    setBotLogEntries((entries) => [entry, ...entries].slice(0, 80));
    setBotLogPopups((entries) => [...entries, entry].slice(-4));
    window.setTimeout(() => {
      setBotLogPopups((entries) => entries.filter((existing) => existing.id !== entry.id));
    }, 5000);
  }, []);

  useEffect(() => {
    if (projection && !focusedCapabilityId) {
      setFocusedCapabilityId(projection.focused_capability_id || projection.capability_order?.[0] || null);
    }
  }, [focusedCapabilityId, projection]);

  useEffect(() => {
    setSpecialTargetMode(null);
  }, [focusedCapabilityId, projection?.version]);

  useEffect(() => {
    if (!botsOnlyMode || botsOnlyPaused) return;
    const activeCapabilityId = projection?.active_capability_id;
    if (!activeCapabilityId || activeCapabilityId === focusedCapabilityId) return;
    setFocusedCapabilityId(activeCapabilityId);
    setMoveMode(false);
  }, [botsOnlyMode, botsOnlyPaused, focusedCapabilityId, projection?.active_capability_id]);

  useEffect(() => {
    if (!feedback && !error) {
      setAlertsVisible(false);
      return undefined;
    }
    setAlertsVisible(true);
    const fadeTimer = window.setTimeout(() => setAlertsVisible(false), 4600);
    const clearTimer = window.setTimeout(() => {
      setFeedback("");
      setError("");
    }, 5200);
    return () => {
      window.clearTimeout(fadeTimer);
      window.clearTimeout(clearTimer);
    };
  }, [feedback, error]);

  useEffect(() => {
    if (projection?.phase !== "game_over" || !roomId) return undefined;
    const timer = window.setTimeout(() => navigate(`/games/${roomId}/post-game`), 3500);
    return () => window.clearTimeout(timer);
  }, [navigate, projection?.phase, roomId]);

  useEffect(() => {
    if (!selectedCapability) {
      setDiscardBeforeDraw(false);
      return;
    }
    const handCount = Number(selectedCapability.hand?.length || 0);
    const handLimit = Number(selectedCapability.current_max_cards_in_hand || 3);
    if (handCount < handLimit) {
      setDiscardBeforeDraw(false);
    }
  }, [selectedCapability?.id, selectedCapability?.hand?.length, selectedCapability?.current_max_cards_in_hand]);

  useEffect(() => {
    if (!projection?.interaction) return;
    setSelectedTileInstanceId(projection.interaction.tile_instance_id || null);
    setInteractionPanelState("open");
    const focusedPlayedCardIds = projection.interaction.initiator_confirmed === false
      && projection.interaction.initiator_capability_id === focusedCapabilityId
      ? (projection.interaction.played_cards || [])
        .filter((card: CardProjection) => card.capability_id === focusedCapabilityId)
        .map((card: CardProjection) => card.card_id)
      : [];
    setSelectedCardIds(focusedPlayedCardIds);
    setFailMoveTargetNodeId("");
  }, [focusedCapabilityId, projection?.interaction?.tile_instance_id, projection?.version]);

  useEffect(() => {
    if (!projection?.pending_surprise) setSurpriseSelectedCardIds([]);
  }, [projection?.pending_surprise?.card?.id]);

  const latestEvent = useMemo(() => {
    const events = projection?.events || [];
    return events.length ? events[events.length - 1] : null;
  }, [projection?.events]);
  const gameWon = projection?.phase === "game_over" && (latestEvent?.type === "game_won" || Boolean(projection?.objectives?.length && projection.objectives.every((objective: any) => objective.completed)));
  const gameOverTitle = gameWon
    ? "All objectives completed"
    : ({
        poulpita_no_energy: "Poulpita has no energy left",
        maximum_nights_reached: "The final day has ended",
        size_deadline_missed: "The required size was not reached in time",
        no_controls_or_actions: "No actions remain",
      } as Record<string, string>)[projection?.game_over_reason || String(latestEvent?.reason || "")]
      || "The game is lost";

  const loadProjection = useCallback(async () => {
    if (!token || !roomId) return;
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/state?t=${Date.now()}`), {
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load game state.");
      setProjection(payload);
      setError("");
    } catch (loadError: any) {
      setError(loadError.message || "Failed to load game state.");
    }
  }, [roomId, token]);

  const loadBotPlans = useCallback(async (method: "GET" | "POST" = "GET") => {
    if (!token || !roomId) return;
    setBotPlansLoading(true);
    try {
      const response = await fetch(
        buildApiUrl(`/api/game/rooms/${roomId}/bot-plans${method === "POST" ? "/recalculate" : ""}`),
        {
          method,
          cache: "no-store",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load bot plans.");
      setBotPlanStatus(payload);
      const continuation = pendingPlanContinuationRef.current;
      if (continuation) {
        pendingPlanContinuationRef.current = null;
        const proposals = payload.proposals || [];
        const expectedCommand = continuation.expectedCommand;
        if (expectedCommand) {
          const matchingPlans = proposals.filter((plan: BotPlanSummary) => plannedCommandMatches(plan.plan_chain?.[0], expectedCommand.type, expectedCommand.payload || {}));
          if (matchingPlans.length) {
            setActivePlanIds(matchingPlans.map((plan: BotPlanSummary) => plan.plan_id));
            setPreferredPlanId((current) => matchingPlans.some((plan: BotPlanSummary) => plan.plan_id === current) ? current : matchingPlans[0]?.plan_id || null);
            setPlanStepIndex(1);
          } else {
            setActivePlanIds([]);
            setPreferredPlanId(null);
            setPlanStepIndex(0);
            pushBotLog("Planned branch changed after new information; choose the next plan manually.", "warn");
          }
        } else {
          setActivePlanIds([]);
          setPreferredPlanId(null);
          setPlanStepIndex(0);
        }
      }
      setError("");
    } catch (plansError: any) {
      setError(plansError.message || "Failed to load bot plans.");
    } finally {
      setBotPlansLoading(false);
    }
  }, [roomId, token]);

  const runOrchestratorStep = useCallback(async () => {
    if (!token || !roomId || orchestratorPendingRef.current) return;
    orchestratorPendingRef.current = true;
    setOrchestratorRunning(true);
    try {
      const response = await fetch(buildApiUrl(`/api/game/rooms/${roomId}/bot-orchestrator/step`), {
        method: "POST",
        cache: "no-store",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Bot orchestrator failed.");
      if (payload.projection) setProjection(payload.projection);
      if (payload.ok) {
        const commandType = String(payload.decision?.command?.type || "action").replaceAll("_", " ");
        const title = payload.decision?.plan_title || payload.decision?.plan_id || "plan";
        pushBotLog(`${title}: ${commandType}`, "ok");
        setBotPlanStatus(null);
      } else if (payload.status === "idle") {
        setBotsOnlyPaused(true);
        setFeedback(payload.message || "The orchestrator has no executable action. Bots were paused.");
      } else {
        setFeedback(payload.message || "The orchestrator action was rejected.");
      }
    } catch (orchestratorError: any) {
      setBotsOnlyPaused(true);
      setError(orchestratorError.message || "Bot orchestrator failed.");
    } finally {
      orchestratorPendingRef.current = false;
      setOrchestratorRunning(false);
    }
  }, [pushBotLog, roomId, token]);

  useEffect(() => {
    if (!activePlanIds.length || !botPlanStatus || activePlanTreePlans.length) return;
    const proposalIds = (botPlanStatus.proposals || []).map((plan) => plan.plan_id);
    if (proposalIds.length) {
      setActivePlanIds(proposalIds);
      setPreferredPlanId(proposalIds[0] || null);
      setPlanStepIndex(1);
      return;
    }
    setActivePlanIds([]);
    setPreferredPlanId(null);
    setPlanStepIndex(0);
    void loadBotPlans("POST");
  }, [activePlanIds.length, activePlanTreePlans.length, botPlanStatus, loadBotPlans]);

  useEffect(() => {
    if (!botModeEnabled || activePlanIds.length || !(botPlanStatus?.proposals || []).length) return;
    const firstPlan = botPlanStatus?.proposals?.[0];
    if (!firstPlan) return;
    const firstKey = stepKey(firstPlan.plan_chain?.[0]);
    const matchingPlanIds = (botPlanStatus.proposals || [])
      .filter((plan) => stepKey(plan.plan_chain?.[0]) === firstKey)
      .map((plan) => plan.plan_id);
    setActivePlanIds(matchingPlanIds.length ? matchingPlanIds : [firstPlan.plan_id]);
    setPreferredPlanId(firstPlan.plan_id);
    setPlanStepIndex(1);
  }, [activePlanIds.length, botModeEnabled, botPlanStatus]);

  useEffect(() => {
    if (!botModeEnabled || !projection || projection.phase === "setup") {
      setBotPlanStatus(null);
      setActivePlanIds([]);
      setPreferredPlanId(null);
      setPlanStepIndex(0);
      return;
    }
    if (!botPlanStatus && !botPlansLoading) void loadBotPlans();
  }, [botModeEnabled, botPlanStatus, botPlansLoading, loadBotPlans, projection?.phase]);

  useEffect(() => {
    if (!botsOnlyMode || botsOnlyPaused || !projection || ["setup", "game_over"].includes(projection.phase)) return undefined;
    const timer = window.setTimeout(() => {
      void runOrchestratorStep();
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [botsOnlyMode, botsOnlyPaused, projection?.phase, projection?.version, runOrchestratorStep]);

  useEffect(() => {
    if (!orchestratorRunning) {
      setOrchestratorElapsedSeconds(0);
      return undefined;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setOrchestratorElapsedSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [orchestratorRunning]);

  useEffect(() => {
    void loadProjection();
  }, [loadProjection]);

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
    let disposed = false;
    socketRef.current = socket;
    socket.onopen = () => {
      if (disposed) {
        socket.close(1000, "stale room socket");
        return;
      }
      void loadProjection();
      socket.send(JSON.stringify({ type: "request_projection" }));
    };
    socket.onmessage = (event) => {
      if (disposed) return;
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
    socket.onerror = () => {
      if (!disposed) setError("Room websocket is unavailable; HTTP commands will still work.");
    };
    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;
    };
    return () => {
      disposed = true;
      if (socketRef.current === socket) socketRef.current = null;
      socket.onmessage = null;
      socket.onerror = null;
      if (socket.readyState === WebSocket.OPEN) {
        socket.close(1000, "leaving room");
      }
    };
  }, [loadProjection, roomId, token]);

  useEffect(() => {
    if (!token || !roomId) return undefined;
    const refreshProjection = () => {
      if (document.visibilityState === "hidden") return;
      void loadProjection();
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: "request_projection" }));
      }
    };
    window.addEventListener("focus", refreshProjection);
    window.addEventListener("pageshow", refreshProjection);
    window.addEventListener("online", refreshProjection);
    document.addEventListener("visibilitychange", refreshProjection);
    return () => {
      window.removeEventListener("focus", refreshProjection);
      window.removeEventListener("pageshow", refreshProjection);
      window.removeEventListener("online", refreshProjection);
      document.removeEventListener("visibilitychange", refreshProjection);
    };
  }, [loadProjection, roomId, token]);

  const plannedCommandMatches = (step: PlanChainStep | undefined, type: string, payload: Record<string, unknown>) => {
    const planned = step?.public_command;
    if (!planned || planned.type !== type) return false;
    const plannedPayload = planned.payload || {};
    return Object.entries(plannedPayload).every(([key, value]) => payload[key] === value);
  };

  const advanceOrInvalidatePlan = (type: string, payload: Record<string, unknown>, source: "manual" | "plan") => {
    if (!activePlanIds.length) return;
    const currentPlans = activePlanTreePlans.length ? activePlanTreePlans : (botPlanStatus?.proposals || []).filter((plan) => activePlanIds.includes(plan.plan_id));
    const matchingPlans = currentPlans.filter((plan) => plannedCommandMatches(plan.plan_chain?.[planStepIndex], type, payload));
    if (matchingPlans.length) {
      setActivePlanIds(matchingPlans.map((plan) => plan.plan_id));
      setPreferredPlanId((current) => matchingPlans.some((plan) => plan.plan_id === current) ? current : matchingPlans[0]?.plan_id || null);
      setPlanStepIndex((index) => index + 1);
      return;
    }
    const currentHasExecutableAlternatives = currentPlans.some((plan) => Boolean(plan.plan_chain?.[planStepIndex]?.public_command));
    if (source === "manual" && currentHasExecutableAlternatives) {
      setActivePlanIds([]);
      setPreferredPlanId(null);
      setPlanStepIndex(0);
      pushBotLog("Selected plan invalidated by a manual action.", "warn");
      void loadBotPlans("POST");
    }
  };

  const submitCommand = async (type: string, payload: Record<string, unknown> = {}, source: "manual" | "plan" = "manual") => {
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
      advanceOrInvalidatePlan(type, payload, source);
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
    if (!selectedCapabilityId || !selectedCapability) return;
    setMoveMode(false);
    const handCount = Number(selectedCapability.hand?.length || 0);
    const handLimit = Number(selectedCapability.current_max_cards_in_hand || 3);
    if (handCount >= handLimit) {
      setDiscardBeforeDraw(true);
      setFeedback("Choose a card to discard before drawing.");
      return;
    }
    setDiscardBeforeDraw(false);
    void submitCommand("draw_action_card", { capability_id: selectedCapabilityId });
  };

  const drawActionCardAfterDiscard = (discardCardId: string) => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    setDiscardBeforeDraw(false);
    void submitCommand("draw_action_card", { capability_id: selectedCapabilityId, discard_card_id: discardCardId });
  };

  const endNight = () => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("end_night", { capability_id: selectedCapabilityId });
  };

  const buyHandSizeUpgrade = (upgradeIndex: number) => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("buy_hand_size_upgrade", { capability_id: selectedCapabilityId, upgrade_index: upgradeIndex });
  };

  const endDay = () => {
    setMoveMode(false);
    void submitCommand("end_day");
  };

  const buyPoulpitaSize = () => {
    setMoveMode(false);
    void submitCommand("buy_poulpita_size");
  };

  const moveShellToShelter = () => {
    setMoveMode(false);
    void submitCommand("move_seashell_to_shelter");
  };

  const moveShellFromShelter = () => {
    setMoveMode(false);
    void submitCommand("move_seashell_from_shelter");
  };

  const movePoulpita = (targetNodeId: NodeId) => {
    if (!selectedCapabilityId) return;
    setMoveMode(false);
    void submitCommand("move_poulpita", {
      capability_id: selectedCapabilityId,
      target_node_id: targetNodeId,
    });
  };

  const useSpecialPower = () => {
    if (!selectedCapabilityId || !projection) return;
    const payload: Record<string, any> = { capability_id: selectedCapabilityId };
    if (["intelligence", "propulsion", "camouflage"].includes(selectedCapabilityId)) {
      setMoveMode(false);
      setSpecialTargetMode(selectedCapabilityId as "intelligence" | "propulsion" | "camouflage");
      setFeedback(selectedCapabilityId === "intelligence" ? "Select a hidden tile on an adjacent node." : "Select a highlighted destination node.");
      return;
    }
    setMoveMode(false);
    setSpecialTargetMode(null);
    void submitCommand("use_special_power", payload);
  };

  const selectSpecialTile = (tileInstanceId: string) => {
    if (specialTargetMode !== "intelligence" || !selectedCapabilityId) return;
    setSpecialTargetMode(null);
    void submitCommand("use_special_power", { capability_id: selectedCapabilityId, tile_instance_id: tileInstanceId });
  };

  const selectSpecialNode = (targetNodeId: NodeId) => {
    if (!projection || !selectedCapabilityId || !specialTargetMode) return;
    const currentNodeId = projection.poulpita?.node_id || "";
    if (specialTargetMode === "propulsion") {
      const middleNodeId = (projection.map?.adjacency?.[currentNodeId] || []).find((nodeId: string) => (projection.map?.adjacency?.[nodeId] || []).includes(targetNodeId));
      if (!middleNodeId) return;
      setSpecialTargetMode(null);
      void submitCommand("use_special_power", { capability_id: selectedCapabilityId, path: [middleNodeId, targetNodeId] });
      return;
    }
    if (specialTargetMode === "camouflage") {
      setSpecialTargetMode(null);
      void submitCommand("use_special_power", { capability_id: selectedCapabilityId, target_node_id: targetNodeId });
    }
  };

  const inspectTile = (tileInstanceId: string) => {
    setMoveMode(false);
    setSelectedTileInstanceId(tileInstanceId);
    setSelectedCardIds([]);
    setFailMoveTargetNodeId("");
    setInteractionPanelState("open");
  };

  const toggleDraftCard = (cardId: string) => {
    setSelectedCardIds((cardIds) => cardIds.includes(cardId) ? cardIds.filter((id) => id !== cardId) : [...cardIds, cardId]);
  };

  const toggleSurpriseCard = (cardId: string) => {
    setSurpriseSelectedCardIds((current) => (current.includes(cardId) ? current.filter((id) => id !== cardId) : [...current, cardId]));
  };

  const resolveSurpriseCard = () => {
    void submitCommand("resolve_surprise_card", {
      accept: true,
      capability_id: selectedCapabilityId,
      card_ids: surpriseSelectedCardIds,
    });
  };

  const skipSurpriseCard = () => {
    void submitCommand("resolve_surprise_card", { accept: false });
  };

  const closeInteractionPanel = () => {
    setInteractionPanelState("closing");
    window.setTimeout(() => {
      setSelectedTileInstanceId(null);
      setSelectedCardIds([]);
      setFailMoveTargetNodeId("");
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

  const confirmInteractionCards = async () => {
    if (!selectedCapabilityId) return;
    await submitCommand("resolve_interaction", {
      capability_id: selectedCapabilityId,
      card_ids: selectedCardIds,
      confirm_only: true,
    });
  };

  const resolveInteraction = async () => {
    if (!selectedCapabilityId) return;
    const result = await submitCommand("resolve_interaction", {
      capability_id: selectedCapabilityId,
    });
    const eventType = result?.events?.[0]?.type;
    if (eventType === "interaction_resolved") {
      setInteractionPanelState("success");
      window.setTimeout(() => {
        setSelectedTileInstanceId(null);
        setSelectedCardIds([]);
        setFailMoveTargetNodeId("");
        setInteractionPanelState("open");
      }, 420);
    }
  };

  const failInteraction = async (spendEnergyToRetry = false) => {
    const result = await submitCommand("fail_interaction", { ...(failMoveTargetNodeId ? { target_node_id: failMoveTargetNodeId } : {}), spend_energy_to_retry: spendEnergyToRetry });
    if (result?.ok !== false) {
      setFailMoveTargetNodeId("");
      setInteractionPanelState("failure");
      window.setTimeout(() => {
        setSelectedTileInstanceId(null);
        setSelectedCardIds([]);
        setFailMoveTargetNodeId("");
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

  const recalculateBotPlans = () => {
    setActivePlanIds([]);
    setPreferredPlanId(null);
    setPlanStepIndex(0);
    void loadBotPlans("POST");
  };

  const selectPlanTreeOption = async (option: PlanTreeOption) => {
    if (pending) return;
    setActivePlanIds(option.planIds);
    setPreferredPlanId((current) => option.planIds.includes(String(current || "")) ? current : option.planIds[0] || null);
    setPlanStepIndex(option.depth + 1);
  };

  const executePlanTreeOption = async (option: PlanTreeOption) => {
    if (pending || !option.public_command) return;
    setActivePlanIds(option.planIds);
    setPreferredPlanId((current) => option.planIds.includes(String(current || "")) ? current : option.planIds[0] || null);
    const nextCommand = option.public_command;
    const selectedPlans = (botPlanStatus?.proposals || []).filter((plan) => option.planIds.includes(plan.plan_id));
    const expectedNextCommand = selectedPlans
      .map((plan) => plan.plan_chain?.[option.depth + 1]?.public_command)
      .find(Boolean) || null;
    const result = await submitCommand(nextCommand.type, nextCommand.payload || {}, "plan");
    if (result?.ok === false) {
      setActivePlanIds([]);
      setPreferredPlanId(null);
      setPlanStepIndex(0);
      void loadBotPlans("POST");
      return;
    }
    setPlanStepIndex(option.depth + 1);
    pushBotLog(`Planned action done: ${option.compactLabel}`, "ok");
    pendingPlanContinuationRef.current = { expectedCommand: expectedNextCommand, previousPlanIds: option.planIds };
    void loadBotPlans("POST");
  };

  const hasAvailableBotPlans = Boolean(botModeEnabled && !botPlansOpen && (botPlanStatus?.proposals || []).length);

  return (
    <main className="h-screen overflow-hidden bg-slate-950 text-slate-100">
      <header className="flex h-[5vh] min-h-10 items-center justify-between border-b border-slate-800 bg-slate-900 px-4">
        <div className="min-w-0 text-sm">
          <span className="font-semibold text-white">Ma vie de poulpe</span>
          <span className="ml-3 text-slate-400">v{projection?.version ?? "-"} - {phaseLabel(projection)}</span>
        </div>
        <div className="flex items-center gap-2">
          {botsOnlyMode && projection?.phase !== "setup" && projection?.phase !== "game_over" ? (
            <>
              <span className="text-xs text-cyan-200">
                {orchestratorRunning
                  ? `Simulating plan${orchestratorElapsedSeconds ? ` ${orchestratorElapsedSeconds}s` : ""}`
                  : botsOnlyPaused
                    ? "Bots paused"
                    : "Bots playing"}
              </span>
              <button
                className="rounded border border-cyan-500 px-3 py-1.5 text-xs text-cyan-100 hover:bg-cyan-950"
                onClick={() => setBotsOnlyPaused((paused) => !paused)}
                type="button"
              >
                {botsOnlyPaused ? "Resume bots" : "Pause bots"}
              </button>
            </>
          ) : null}
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

      {feedback || error ? (
        <div className={["pointer-events-none fixed left-1/2 top-[22vh] z-50 w-[min(42rem,calc(100vw-2rem))] -translate-x-1/2 transition-opacity duration-500", alertsVisible ? "opacity-100" : "opacity-0"].join(" ")}>
          {feedback ? <p className="rounded-md border border-amber-500/50 bg-amber-950/95 px-3 py-2 text-sm text-amber-100">{feedback}</p> : null}
          {error ? <p className="mt-2 rounded-md border border-rose-500/50 bg-rose-950/95 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
        </div>
      ) : null}
      {projection?.phase === "game_over" ? (
        <div className="pointer-events-none fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/45">
          <div className={["animate-[pulse_1.2s_ease-in-out_2] rounded-lg border px-8 py-5 text-center shadow-2xl", gameWon ? "border-teal-300 bg-teal-950" : "border-rose-300 bg-rose-950"].join(" ")}>
            <p className={["text-sm uppercase tracking-wide", gameWon ? "text-teal-200" : "text-rose-200"].join(" ")}>{gameWon ? "Game won" : "Game lost"}</p>
            <h2 className="mt-1 text-2xl font-semibold text-white">
              {gameOverTitle}
            </h2>
            <p className={["mt-2 text-sm", gameWon ? "text-teal-100" : "text-rose-100"].join(" ")}>Post-game opens in a few seconds.</p>
          </div>
        </div>
      ) : null}

      <section className="grid h-[95vh] grid-cols-[17rem_minmax(0,1fr)_minmax(14rem,25%)] grid-rows-[minmax(0,1fr)_minmax(11rem,24vh)] overflow-hidden">
        <aside className="row-span-2 flex min-h-0 flex-col gap-2 overflow-hidden border-r border-slate-800 bg-slate-950 p-2">
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            {otherCapabilities.map((capability) => (
              <div className="min-h-0 flex-1" key={capability.id}>
                <CapabilityBoard
                  active={projection?.active_capability_id === capability.id}
                  capability={capability}
                  compact
                  focused={false}
                  moveMode={moveMode}
                  onFocus={() => {
                    setFocusedCapabilityId(capability.id);
                    setMoveMode(false);
                  }}
                  pending={gameplayPending}
                  projection={projection}
                />
              </div>
            ))}
          </div>
          <div className="min-h-0 h-[24vh] max-h-[24vh]">
            {selectedCapability ? (
              <CapabilityBoard
                active={projection?.active_capability_id === selectedCapability.id}
                capability={selectedCapability}
                compact
                focused
                moveMode={moveMode}
                onFocus={() => {
                  setFocusedCapabilityId(selectedCapability.id);
                  setMoveMode(false);
                }}
                pending={gameplayPending}
                projection={projection}
              />
            ) : null}
          </div>
        </aside>
        <div className="relative min-w-0 overflow-hidden border-r border-slate-800">
          {projection ? (
            <>
              <BoardView focusedCapabilityId={selectedCapabilityId} moveMode={moveMode} onInspectTile={inspectTile} onMove={movePoulpita} onMoveShellFromShelter={moveShellFromShelter} onSpecialNode={selectSpecialNode} onSpecialTile={selectSpecialTile} pending={gameplayPending} projection={projection} specialTargetMode={specialTargetMode} />
              {botModeEnabled ? (
                <BotPlanTree
                  onExecuteOption={executePlanTreeOption}
                  onSelectOption={selectPlanTreeOption}
                  onToggleCollapsed={() => setBotPlanTreeCollapsed((collapsed) => !collapsed)}
                  pending={gameplayPending}
                  activePlanIds={activePlanIds}
                  collapsed={botPlanTreeCollapsed}
                  plans={botPlanStatus?.proposals || []}
                  preferredPlanId={preferredPlanId}
                  projection={projection}
                  stepIndex={planStepIndex}
                />
              ) : null}
              {botModeEnabled ? (
                <button
                  className={[
                    "absolute right-3 top-3 z-[65] w-28 rounded-full border bg-slate-900 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-cyan-100 shadow-lg hover:bg-slate-800",
                    hasAvailableBotPlans ? "animate-pulse border-amber-300 ring-2 ring-amber-200/70" : "border-cyan-300",
                  ].join(" ")}
                  onClick={() => {
                    setBotPlansOpen((open) => !open);
                    if (!botPlansOpen) void loadBotPlans();
                  }}
                  type="button"
                >
                  {botPlansOpen ? "Close plans" : "Plans"}
                </button>
              ) : null}
              {botLogEnabled ? (
                <BotActionLog
                  entries={botLogEntries}
                  logOpen={botLogOpen}
                  onToggle={() => setBotLogOpen((open) => !open)}
                  popups={botLogPopups}
                />
              ) : null}
              {botModeEnabled ? (
                <BotPlansOverlay
                  botPlanStatus={botPlanStatus}
                  loading={botPlansLoading}
                  onClose={() => setBotPlansOpen(false)}
                  onRecalculate={recalculateBotPlans}
                  open={botPlansOpen}
                  projection={projection}
                />
              ) : null}
              <InteractionPanel
                failMoveTargetNodeId={failMoveTargetNodeId}
                onFail={failInteraction}
                onFailMoveTargetChange={setFailMoveTargetNodeId}
                onClose={closeInteractionPanel}
                onInitiate={initiateInteraction}
                onConfirmCards={confirmInteractionCards}
                onResolve={resolveInteraction}
                onToggleCard={toggleDraftCard}
                pending={gameplayPending}
                projection={projection}
                selectedCardIds={selectedCardIds}
                selectedCapability={selectedCapability}
                selectedTileInstanceId={selectedTileInstanceId}
                visualState={interactionPanelState}
              />
              <SurpriseCardPanel
                onResolve={resolveSurpriseCard}
                onSkip={skipSurpriseCard}
                onToggleCard={toggleSurpriseCard}
                pending={gameplayPending}
                projection={projection}
                selectedCapability={selectedCapability}
                selectedCardIds={surpriseSelectedCardIds}
              />
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">Loading room state.</div>
          )}
        </div>
        <aside className="row-span-2 flex min-h-0 flex-col gap-2 overflow-hidden bg-slate-900 p-2">
          <div className="shrink-0">
            <p className="text-xs uppercase text-slate-500">Poulpita</p>
            <h2 className="mt-0.5 truncate text-base font-semibold text-white">{phaseLabel(projection)}</h2>
          </div>
          <ObjectivesPanel projection={projection} />
          <TimeTracker projection={projection} />
          <EnergyBar energy={Number(projection?.poulpita.energy || 0)} maximum={Number(projection?.poulpita.max_energy || 32)} />
          <PoulpitaResourcePanel onBuySize={buyPoulpitaSize} onMoveShellToShelter={moveShellToShelter} pending={gameplayPending} projection={projection} />
        </aside>
        <div className="grid min-h-0 grid-cols-[11rem_1fr] gap-2 overflow-hidden border-t border-r border-slate-800 bg-slate-950 p-1">
          <ActionPanel
            active={Boolean(projection?.active_capability_id && projection.active_capability_id === selectedCapability?.id)}
            capability={selectedCapability || null}
            moveMode={moveMode}
            onCollect={collectActionPoints}
            onDraw={drawActionCard}
            onEndDay={endDay}
            onEndNight={endNight}
            onMoveMode={() => { setSpecialTargetMode(null); setMoveMode((value) => !value); }}
            onSpecialPower={useSpecialPower}
            onTakeControl={takeControl}
            pending={gameplayPending}
            projection={projection}
          />
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-white">{projection?.phase === "day" ? "Day upgrades" : "Player hand"}</h3>
              {discardBeforeDraw ? (
                <button className="text-xs text-slate-400 hover:text-white" onClick={() => setDiscardBeforeDraw(false)} type="button">
                  Cancel discard
                </button>
              ) : null}
            </div>
            {projection?.phase === "day" ? (
              <div className="mt-3 grid h-[calc(100%-2rem)] content-start gap-2 overflow-auto rounded border border-dashed border-slate-700 p-2 sm:grid-cols-2 lg:grid-cols-3">
                {(selectedCapability?.hand_size_upgrades || []).map((upgrade, index) => {
                  const purchased = new Set((selectedCapability?.purchased_hand_size_upgrade_indices || []).map((value) => Number(value)));
                  const bought = purchased.has(index);
                  const cost = Number(upgrade.cost || 0);
                  const isDeckExchange = upgrade.type === "deck_exchange";
                  return (
                    <button
                      className={[
                        "rounded-md border p-3 text-left text-xs transition",
                        bought ? "border-slate-700 bg-slate-950 text-slate-500" : "border-cyan-300 bg-slate-950 text-cyan-100 hover:bg-cyan-950",
                      ].join(" ")}
                      disabled={gameplayPending || bought || Number(projection?.poulpita.neurons || 0) < cost}
                      key={index}
                      onClick={() => buyHandSizeUpgrade(index)}
                      type="button"
                    >
                      <span className="block font-semibold text-white">{isDeckExchange ? "Improve deck" : `Increase hand +${Number(upgrade.hand_size_bonus || 1)}`}</span>
                      <span className="mt-1 block text-slate-400">{bought ? "Bought" : `${cost} neurons`}</span>
                      {isDeckExchange ? <span className="mt-1 block text-slate-400">Exchange cards at next night setup.</span> : null}
                    </button>
                  );
                })}
                {(selectedCapability?.hand_size_upgrades || []).length === 0 ? <p className="m-auto text-sm text-slate-500">No upgrades configured.</p> : null}
              </div>
            ) : (
              <>
                {discardBeforeDraw ? <p className="mt-2 text-xs text-amber-200">Choose one card to discard, then a new card will be drawn.</p> : null}
                <div className="mt-3 flex h-[calc(100%-2rem)] flex-wrap content-start gap-2 overflow-auto rounded border border-dashed border-slate-700 p-2">
                  {(selectedCapability?.hand || []).map((card) => (
                    <CardButton
                      card={card}
                      disabled={
                        pending ||
                        (!discardBeforeDraw && (!(projection?.interaction || selectedTileInstanceId) || projection?.active_capability_id !== selectedCapability?.id))
                      }
                      key={card.card_id}
                      onClick={() => {
                        if (discardBeforeDraw) {
                          drawActionCardAfterDiscard(card.card_id);
                          return;
                        }
                        if (projection?.interaction || selectedTileInstanceId) {
                          toggleDraftCard(card.card_id);
                        }
                      }}
                      projection={projection as GameProjection}
                      selected={discardBeforeDraw || selectedCardIds.includes(card.card_id)}
                      showPreview
                    />
                  ))}
                  {(selectedCapability?.hand || []).length === 0 ? <p className="m-auto text-sm text-slate-500">No cards in hand.</p> : null}
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </main>
  );
};

export default GameRoomPage;
