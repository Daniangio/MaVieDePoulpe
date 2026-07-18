import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "react-router-dom";
import BoardView from "../components/BoardView.js";
import CardPreview from "../components/CardPreview.jsx";
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
  if (projection.phase === "day") return `Day ${projection.day_index || 1}`;
  return `Night ${projection.day_index || 1}`;
};

const TimeTracker = ({ projection }: { projection: GameProjection | null }) => {
  const spent = Math.max(0, Number(projection?.night_time_spent || 0));
  const total = Math.max(24, Number(projection?.night_time_total || 24));
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

const EnergyBar = ({ energy }: { energy: number }) => {
  const current = Math.max(0, Math.min(32, Number(energy || 0)));
  return (
    <div className="shrink-0 rounded bg-slate-800 p-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Energy</span>
        <strong>{current}/32</strong>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-0.5">
        {Array.from({ length: 32 }).map((_, index) => (
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
    Number(projection?.night_time_spent || 0) >= Number(projection?.night_shelter_available_at || 16);
  const purchasedUpgrades = new Set((capability.purchased_hand_size_upgrade_indices || []).map((index) => Number(index)));
  const sharedNeurons = Number(projection?.poulpita?.neurons || 0);
  const ArticleTag = compact ? "button" : "article";
  return (
  <ArticleTag
    className={[
      "group/board relative min-w-0 overflow-auto rounded-md border bg-slate-900 text-left text-slate-100 shadow-xl transition",
      compact ? "cursor-pointer hover:z-50 hover:border-cyan-300 hover:bg-slate-800 hover:shadow-cyan-500/20 focus:outline-none focus:ring-2 focus:ring-cyan-300" : "",
      active ? "border-teal-300" : focused ? "border-amber-300" : "border-slate-700",
      compact ? "h-full p-1" : "h-full p-2",
    ].join(" ")}
    onClick={compact ? onFocus : undefined}
    type={compact ? "button" : undefined}
  >
    <div className="flex items-start justify-between gap-1">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-white">{capability.name}</h3>
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
  onTakeControl: () => void;
  pending: boolean;
  projection: GameProjection | null;
}) => {
  if (!capability) return <div className="rounded-md border border-slate-800 bg-slate-900 p-3 text-sm text-slate-500">No actions.</div>;
  const isNightAction = projection?.phase === "night_action";
  const isNight = projection?.phase === "night_idle" || projection?.phase === "night_action";
  const currentNodeId = projection?.poulpita?.node_id || "";
  const canEndNight =
    active &&
    projection?.phase === "night_action" &&
    Boolean(currentNodeId) &&
    shelterData(projection?.shelters?.[currentNodeId]).count > 0 &&
    Number(projection?.night_time_spent || 0) >= Number(projection?.night_shelter_available_at || 16);
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto rounded-md border border-slate-800 bg-slate-900 p-2">
      <h3 className="text-sm font-semibold text-white">Actions</h3>
      <div className="grid grid-cols-2 gap-1.5">
        <button className="rounded bg-teal-400 px-1.5 py-2 text-[0.68rem] font-semibold leading-tight text-slate-950 hover:bg-teal-300 disabled:opacity-50" disabled={pending || active || !isNight} onClick={onTakeControl} type="button">
          Take control
        </button>
        <button className="rounded border border-slate-600 px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 hover:bg-slate-800 disabled:opacity-50" disabled={pending || !active || !isNightAction} onClick={onCollect} type="button">
          Collect AP
        </button>
        <button
          className={["rounded border px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 disabled:opacity-50", moveMode ? "border-amber-300 bg-amber-950" : "border-slate-600 hover:bg-slate-800"].join(" ")}
          disabled={pending || !active || !isNightAction || capability.pa < 1}
          onClick={onMoveMode}
          type="button"
        >
          Move
        </button>
        <button className="rounded border border-slate-600 px-1.5 py-2 text-[0.68rem] leading-tight text-slate-100 hover:bg-slate-800 disabled:opacity-50" disabled={pending || !active || !isNightAction || capability.pa < 1} onClick={onDraw} type="button">
          Draw
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
        className="rounded border border-cyan-300 px-2 py-1 text-[0.68rem] font-semibold text-cyan-100 hover:bg-cyan-950 disabled:opacity-50"
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
  const nextSizeCost = Math.max(0, baseNextSizeCost - (currentShelter.secure ? 1 : 0));
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
  failMoveTargetNodeId: string;
  onFailMoveTargetChange: (nodeId: string) => void;
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
  const playedInteractions = [...lockedPlayedCards, ...selectedCards].reduce((selected: string[], card: CardProjection) => {
    selected.push(chooseCardInteractionForTile(card, tile, selected));
    return selected;
  }, []);
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
  const shellRequirementCount = Math.max(0, Number(tile.shell_requirement_count || 0));
  const carriedShells = Math.max(0, Number(projection.poulpita?.seashells || 0));
  const missingShells = Math.max(0, shellRequirementCount - carriedShells);
  const canResolve = missingSuccess.length === 0 && missingShells === 0;
  const canInitiate = !activeInteraction && projection.active_capability_id === selectedCapability?.id;
  const requiresFreeFailureMove = Boolean(activeInteraction && (tile.failure_effects || []).some((effect: any) => effect.type === "pulpita_move_free"));
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
              <HexTilePreview className="max-w-[15rem]" event={event} interactionsById={interactionsById} tile={tile} />
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
                {requiresFreeFailureMove ? (
                  <select className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={failMoveTargetNodeId} onChange={(event) => onFailMoveTargetChange(event.target.value)}>
                    <option value="">Move Poulpita to...</option>
                    {adjacentNodeIds.map((nodeId: string) => <option key={nodeId} value={nodeId}>{nodeId}</option>)}
                  </select>
                ) : null}
                <button className="rounded border border-rose-500 px-3 py-2 text-sm text-rose-100 hover:bg-rose-950 disabled:opacity-50" disabled={pending || (requiresFreeFailureMove && !failMoveTargetNodeId)} onClick={onFail} type="button">Fail</button>
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
  const [surpriseSelectedCardIds, setSurpriseSelectedCardIds] = useState<string[]>([]);
  const [discardBeforeDraw, setDiscardBeforeDraw] = useState(false);
  const [failMoveTargetNodeId, setFailMoveTargetNodeId] = useState("");
  const [interactionPanelState, setInteractionPanelState] = useState<"open" | "success" | "failure" | "closing">("open");
  const [alertsVisible, setAlertsVisible] = useState(false);

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
    const activeCapabilityId = projection.active_capability_id;
    const activePlayedCardIds = (projection.interaction.played_cards || [])
      .filter((card: CardProjection) => card.capability_id === activeCapabilityId)
      .map((card: CardProjection) => card.card_id);
    setSelectedCardIds(activePlayedCardIds);
    setFailMoveTargetNodeId("");
  }, [projection?.active_capability_id, projection?.interaction?.tile_instance_id, projection?.version]);

  useEffect(() => {
    if (!projection?.pending_surprise) setSurpriseSelectedCardIds([]);
  }, [projection?.pending_surprise?.card?.id]);

  const latestEvent = useMemo(() => {
    const events = projection?.events || [];
    return events.length ? events[events.length - 1] : null;
  }, [projection?.events]);
  const gameWon = projection?.phase === "game_over" && (latestEvent?.type === "game_won" || Boolean(projection?.objectives?.length && projection.objectives.every((objective: any) => objective.completed)));

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
        setFailMoveTargetNodeId("");
        setInteractionPanelState("open");
      }, 420);
    }
  };

  const failInteraction = async () => {
    const result = await submitCommand("fail_interaction", failMoveTargetNodeId ? { target_node_id: failMoveTargetNodeId } : {});
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
              {gameWon
                ? "All objectives completed"
                : String(latestEvent?.reason || "") === "poulpita_no_energy"
                  ? "Poulpita has no energy left"
                  : "No actions remain"}
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
                  pending={pending}
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
                pending={pending}
                projection={projection}
              />
            ) : null}
          </div>
        </aside>
        <div className="relative min-w-0 overflow-hidden border-r border-slate-800">
          {projection ? (
            <>
              <BoardView focusedCapabilityId={selectedCapabilityId} moveMode={moveMode} onInspectTile={inspectTile} onMove={movePoulpita} onMoveShellFromShelter={moveShellFromShelter} pending={pending} projection={projection} />
              <InteractionPanel
                failMoveTargetNodeId={failMoveTargetNodeId}
                onFail={failInteraction}
                onFailMoveTargetChange={setFailMoveTargetNodeId}
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
              <SurpriseCardPanel
                onResolve={resolveSurpriseCard}
                onSkip={skipSurpriseCard}
                onToggleCard={toggleSurpriseCard}
                pending={pending}
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
          <EnergyBar energy={Number(projection?.poulpita.energy || 0)} />
          <PoulpitaResourcePanel onBuySize={buyPoulpitaSize} onMoveShellToShelter={moveShellToShelter} pending={pending} projection={projection} />
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
            onMoveMode={() => setMoveMode((value) => !value)}
            onTakeControl={takeControl}
            pending={pending}
            projection={projection}
          />
          <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-white">Player hand</h3>
              {discardBeforeDraw ? (
                <button className="text-xs text-slate-400 hover:text-white" onClick={() => setDiscardBeforeDraw(false)} type="button">
                  Cancel discard
                </button>
              ) : null}
            </div>
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
          </div>
        </div>
      </section>
    </main>
  );
};

export default GameRoomPage;
