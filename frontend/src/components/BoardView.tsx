import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import HexTilePreview from "./HexTilePreview.jsx";
import { buildApiUrl } from "../utils/connection.js";
import type { GameProjection, NodeId } from "../types/game.js";

type BoardViewProps = {
  projection: GameProjection;
  focusedCapabilityId?: string | null;
  moveMode: boolean;
  specialTargetMode?: "intelligence" | "propulsion" | "camouflage" | null;
  pending: boolean;
  onMove: (targetNodeId: NodeId) => void;
  onSpecialNode?: (targetNodeId: NodeId) => void;
  onSpecialTile?: (tileInstanceId: string) => void;
  onInspectTile?: (tileInstanceId: string) => void;
  onMoveShellFromShelter?: (nodeId: NodeId) => void;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const BoardTileToken = ({ event, faceDown, highlighted, title }: { event: any; faceDown?: boolean; highlighted?: boolean; title: string }) => {
  const imageUrl = event?.image_url ? buildApiUrl(event.image_url) : "";
  return (
    <span
      className={[
        "block h-full w-full overflow-hidden border bg-white shadow",
        highlighted ? "border-emerald-300 ring-2 ring-emerald-300 ring-offset-1 ring-offset-transparent" : "border-teal-300",
      ].join(" ")}
      style={{ clipPath: "polygon(25% 4%, 75% 4%, 100% 50%, 75% 96%, 25% 96%, 0 50%)" }}
    >
      {faceDown ? (
        <span className="flex h-full w-full items-center justify-center bg-[linear-gradient(135deg,#0f766e_0_45%,#164e63_45%_55%,#0f766e_55%)] text-[0.55rem] font-semibold text-cyan-50" />
      ) : imageUrl ? (
        <img alt={title} className="h-full w-full object-cover" draggable={false} src={imageUrl} />
      ) : (
        <span className="flex h-full w-full items-center justify-center bg-cyan-50 text-[0.55rem] font-semibold text-teal-900">
          {title.slice(0, 2)}
        </span>
      )}
    </span>
  );
};

const InteractionRequirementBadge = ({ interaction, counter = false }: { interaction: any; counter?: boolean }) => {
  const iconUrl = interaction?.image_url ? buildApiUrl(interaction.image_url) : "";
  return (
    <span
      className={[
        "flex h-4 w-4 items-center justify-center overflow-hidden border bg-white text-[0.45rem] font-bold shadow-sm",
        counter ? "rounded-sm border-fuchsia-500 text-fuchsia-900" : "rounded-full border-teal-500 text-teal-900",
      ].join(" ")}
      title={interaction?.name || "Requirement"}
    >
      {iconUrl ? <img alt="" className="h-full w-full object-cover" draggable={false} src={iconUrl} /> : interaction?.name?.slice(0, 2) || "?"}
    </span>
  );
};

const RequirementStrip = ({
  tile,
  interactionsById,
  large = false,
}: {
  tile: any;
  interactionsById: Record<string, any>;
  large?: boolean;
}) => {
  const interactionIds = tile?.interaction_ids || [];
  const counterAttackIds = tile?.counter_attack_interaction_ids || [];
  const shellCount = Math.max(0, Number(tile?.shell_requirement_count || 0));
  if (!interactionIds.length && !counterAttackIds.length && !shellCount) return null;
  return (
    <span className={["flex flex-wrap items-center justify-center gap-0.5", large ? "max-w-32" : "max-w-20"].join(" ")}>
      {interactionIds.map((id: string) => (
        <InteractionRequirementBadge interaction={interactionsById[id]} key={`i:${id}`} />
      ))}
      {Array.from({ length: shellCount }).map((_, index) => (
        <span className="flex h-4 w-4 items-center justify-center rounded-full border border-amber-300 bg-amber-50 text-[0.45rem] font-bold text-amber-900 shadow-sm" key={`s:${index}`} title="Poulpita shell required">
          S
        </span>
      ))}
      {counterAttackIds.map((id: string) => (
        <InteractionRequirementBadge counter interaction={interactionsById[id]} key={`c:${id}`} />
      ))}
    </span>
  );
};

const OctopusBoardToken = ({
  tile,
  token,
  interactionsById,
  highlighted,
  title,
  large = false,
}: {
  tile: any;
  token: any;
  interactionsById: Record<string, any>;
  highlighted?: boolean;
  title: string;
  large?: boolean;
}) => {
  const imagePath = token?.image_url || tile?.image_url || tile?.event?.image_url || "";
  const imageUrl = imagePath ? buildApiUrl(imagePath) : "";
  const sizeClass = large ? "h-28 w-28" : "h-10 w-10";
  return (
    <span className="relative flex items-center justify-center bg-transparent">
      <span className={["absolute z-10", large ? "-top-4" : "-top-2"].join(" ")}>
        <RequirementStrip interactionsById={interactionsById} large={large} tile={tile} />
      </span>
      <span
        className={[
          "flex items-center justify-center overflow-hidden rounded-full border bg-cyan-100 font-bold text-teal-950 shadow",
          sizeClass,
          highlighted ? "border-emerald-300 ring-2 ring-emerald-300 ring-offset-1 ring-offset-transparent" : "border-cyan-100",
        ].join(" ")}
        title={title}
      >
        {imageUrl ? <img alt={title} className="h-full w-full object-cover" draggable={false} src={imageUrl} /> : <span className={large ? "text-base" : "text-[0.55rem]"}>O</span>}
      </span>
    </span>
  );
};

const tileOrbitPosition = (index: number) => {
  const radius = 34;
  const anglePattern = [90, 25, 155, -25, -155, -90, 0, 180];
  const angle = anglePattern[index % anglePattern.length];
  const ring = Math.floor(index / anglePattern.length) + 1;
  const radians = (angle * Math.PI) / 180;
  return {
    x: Math.cos(radians) * radius * ring,
    y: Math.sin(radians) * radius * ring,
  };
};

const normalizeShelter = (entry: any) => {
  if (typeof entry === "number") return { count: Math.max(0, Number(entry || 0)), seashells: 0, secure: false };
  return {
    count: Math.max(0, Number(entry?.count || 0)),
    seashells: Math.max(0, Number(entry?.seashells || 0)),
    secure: Boolean(entry?.secure) || Number(entry?.seashells || 0) >= 3,
  };
};

type AnimatedTile = any & { __animation?: "placing" | "removing" };

const flattenTiles = (tiles: Record<string, any[]> | undefined) => {
  const flattened = new Map<string, { nodeId: string; tile: any }>();
  for (const [nodeId, nodeTiles] of Object.entries(tiles || {})) {
    for (const tile of nodeTiles || []) {
      if (tile?.instance_id) flattened.set(String(tile.instance_id), { nodeId, tile });
    }
  }
  return flattened;
};

const groupTiles = (entries: Array<{ nodeId: string; tile: AnimatedTile }>) => {
  const grouped: Record<string, AnimatedTile[]> = {};
  for (const entry of entries) grouped[entry.nodeId] = [...(grouped[entry.nodeId] || []), entry.tile];
  return grouped;
};

const BoardView = ({ projection, focusedCapabilityId, moveMode, specialTargetMode, pending, onMove, onSpecialNode, onSpecialTile, onInspectTile, onMoveShellFromShelter }: BoardViewProps) => {
  const boardRef = useRef<HTMLElement | null>(null);
  const currentNodeId = projection.poulpita.node_id;
  const focusedCapability = focusedCapabilityId ? projection.capabilities?.[focusedCapabilityId] : null;
  const adjacentNodeIds = currentNodeId ? projection.map.adjacency[currentNodeId] || [] : [];
  const nodes = useMemo(() => Object.values(projection.map.nodes).sort((a, b) => a.x - b.x || a.y - b.y), [projection.map.nodes]);
  const imageUrl = projection.map.image_url ? buildApiUrl(projection.map.image_url) : "";
  const imageWidth = Number(projection.map.image_width || 0);
  const imageHeight = Number(projection.map.image_height || 0);
  const aspectRatio = imageWidth > 0 && imageHeight > 0 ? `${imageWidth} / ${imageHeight}` : "11 / 4";
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hoveredTile, setHoveredTile] = useState<{
    tile: any;
    event: any;
    interactionsById: Record<string, any>;
    token: any;
    isRoundToken: boolean;
    left: number;
    top: number;
  } | null>(null);
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const previousTilesRef = useRef<Map<string, { nodeId: string; tile: any }>>(new Map());
  const [displayTiles, setDisplayTiles] = useState<Record<string, AnimatedTile[]>>(() =>
    groupTiles(Array.from(flattenTiles(projection.tiles).values()).map((entry) => ({ ...entry, tile: { ...entry.tile, __animation: "placing" } }))),
  );

  useEffect(() => {
    const previous = previousTilesRef.current;
    const current = flattenTiles(projection.tiles);
    const addedIds = new Set(Array.from(current.keys()).filter((instanceId) => !previous.has(instanceId)));
    const removed = Array.from(previous.entries())
      .filter(([instanceId]) => !current.has(instanceId))
      .map(([, entry]) => ({ ...entry, tile: { ...entry.tile, __animation: "removing" as const } }));
    const timers: number[] = [];

    const showCurrent = () => {
      setDisplayTiles(groupTiles(Array.from(current.entries()).map(([instanceId, entry]) => ({
        ...entry,
        tile: { ...entry.tile, ...(addedIds.has(instanceId) ? { __animation: "placing" as const } : {}) },
      }))));
      timers.push(window.setTimeout(() => {
        setDisplayTiles(groupTiles(Array.from(current.values()).map((entry) => ({ ...entry, tile: { ...entry.tile } }))));
      }, 850));
    };

    if (removed.length) {
      const surviving = Array.from(current.entries())
        .filter(([instanceId]) => !addedIds.has(instanceId))
        .map(([, entry]) => ({ ...entry, tile: { ...entry.tile } }));
      setDisplayTiles(groupTiles([...surviving, ...removed]));
      timers.push(window.setTimeout(showCurrent, 420));
    } else {
      showCurrent();
    }
    previousTilesRef.current = current;
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [projection.tiles]);

  const showTilePreview = (target: HTMLElement, tile: any, event: any, interactionsById: Record<string, any>, token: any, isRoundToken: boolean) => {
    const boardRect = boardRef.current?.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    if (!boardRect) return;
    const previewWidth = isRoundToken ? 128 : 160;
    const previewHeight = isRoundToken ? 144 : 156;
    const gap = 8;
    const centerX = targetRect.left + targetRect.width / 2 - boardRect.left;
    const topY = targetRect.top - boardRect.top - previewHeight - gap;
    const bottomY = targetRect.bottom - boardRect.top + gap;
    const top = topY >= gap ? topY : Math.min(bottomY, boardRect.height - previewHeight - gap);
    const left = clamp(centerX - previewWidth / 2, gap, Math.max(gap, boardRect.width - previewWidth - gap));
    setHoveredTile({
      tile,
      event,
      interactionsById,
      token,
      isRoundToken,
      left,
      top: clamp(top, gap, Math.max(gap, boardRect.height - previewHeight - gap)),
    });
  };

  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    dragRef.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const drag = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    setPan({
      x: dragRef.current.panX + event.clientX - dragRef.current.x,
      y: dragRef.current.panY + event.clientY - dragRef.current.y,
    });
  };

  const endDrag = () => {
    dragRef.current = null;
  };

  return (
    <section className="relative h-full overflow-hidden bg-slate-950" ref={boardRef}>
      <div className="absolute right-3 bottom-3 z-30 flex gap-2 rounded-md border border-slate-800 bg-slate-950/90 p-2">
        <button className="h-8 w-8 rounded bg-slate-800 text-white hover:bg-slate-700" onClick={() => setZoom((value) => clamp(value - 0.15, 0.35, 3))} type="button">-</button>
        <button className="h-8 w-8 rounded bg-slate-800 text-white hover:bg-slate-700" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} type="button">1</button>
        <button className="h-8 w-8 rounded bg-slate-800 text-white hover:bg-slate-700" onClick={() => setZoom((value) => clamp(value + 0.15, 0.35, 3))} type="button">+</button>
      </div>

      <div className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing" onPointerDown={startDrag} onPointerMove={drag} onPointerUp={endDrag} onPointerCancel={endDrag}>
        <div
          className="relative mx-auto h-full"
          style={{
            aspectRatio,
            maxWidth: imageWidth || undefined,
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center center",
          }}
        >
          {imageUrl ? <img alt={projection.map.name || "Game board"} className="absolute inset-0 h-full w-full select-none object-contain" draggable={false} src={imageUrl} /> : null}
          {!imageUrl ? <div className="absolute inset-0 bg-slate-900" /> : null}
          {nodes.map((node) => {
            const isCurrent = node.id === currentNodeId;
            const isPrevious = node.id === projection.poulpita.previous_node_id;
            const isAdjacent = adjacentNodeIds.includes(node.id);
            const canMove = moveMode && projection.phase === "night_action" && isAdjacent && !pending;
            const canCamouflage = specialTargetMode === "camouflage" && projection.phase === "night_action" && isAdjacent && !pending;
            const canPropel = specialTargetMode === "propulsion"
              && projection.phase === "night_action"
              && node.id !== currentNodeId
              && node.id !== projection.poulpita_starting_node_id
              && adjacentNodeIds.some((middleNodeId) => (projection.map.adjacency[middleNodeId] || []).includes(node.id))
              && !pending;
            const canSelectNode = canMove || canCamouflage || canPropel;
            const nodeTiles = displayTiles[node.id] || [];
            const shelter = normalizeShelter(projection.shelters?.[node.id]);
            const shelterCount = shelter.count;
            const shelterToken = projection.tile_catalog?.tokens?.shelter;
            const shelterImageUrl = shelterToken?.image_url ? buildApiUrl(shelterToken.image_url) : "";
            const seashellToken = projection.tile_catalog?.tokens?.seashell;
            const seashellImageUrl = seashellToken?.image_url ? buildApiUrl(seashellToken.image_url) : "";
            const canMoveShellBack = projection.phase === "day" && isCurrent && shelter.seashells > 0 && !pending;
            return (
              <div className="absolute -translate-x-1/2 -translate-y-1/2" key={node.id} style={{ left: `${node.x * 100}%`, top: `${node.y * 100}%` }}>
                <button
                  className={[
                    "relative flex h-10 w-10 flex-col items-center justify-center rounded-full border text-xs font-semibold shadow-lg transition",
                    isCurrent
                      ? "border-teal-100 bg-teal-300 text-slate-950"
                      : canMove
                        ? "border-teal-300 bg-slate-950/95 text-white hover:bg-teal-900"
                        : isAdjacent
                          ? "border-teal-700 bg-slate-950/85 text-slate-100"
                          : "border-slate-700 bg-slate-950/75 text-slate-300",
                    canSelectNode ? "cursor-pointer ring-2 ring-fuchsia-300" : "cursor-default",
                  ].join(" ")}
                  disabled={!canSelectNode}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (canMove) onMove(node.id);
                    else if (canCamouflage || canPropel) onSpecialNode?.(node.id);
                  }}
                  onPointerDown={(event) => event.stopPropagation()}
                  type="button"
                >
                  <span className={isCurrent ? "opacity-0" : ""}>{node.id}</span>
                  {isPrevious && !isCurrent ? <span className="absolute right-0 top-0 h-2 w-2 rounded-full bg-slate-400" /> : null}
                </button>
                {shelterCount > 0 ? (
                  <span className={["absolute right-1/2 top-0 z-20 flex h-10 min-w-10 -translate-y-[50%] items-center justify-center overflow-hidden rounded-full border bg-cyan-100 text-[0.55rem] font-bold text-teal-950 shadow", shelter.secure ? "border-emerald-200 bg-emerald-100 ring-4 ring-emerald-300 shadow-[0_0_18px_rgba(52,211,153,0.9)]" : "border-cyan-100"].join(" ")} title={`${shelterCount} shelter token${shelterCount === 1 ? "" : "s"}${shelter.secure ? " - secure" : ""}`}>
                    {shelterImageUrl ? <img alt="" className="h-full w-full object-cover" draggable={false} src={shelterImageUrl} /> : shelterCount > 1 ? shelterCount : "S"}
                    {shelterCount > 1 && shelterImageUrl ? <span className="absolute -bottom-0.5 -right-0.5 rounded-full bg-teal-950 px-1 text-[0.5rem] leading-3 text-cyan-50">{shelterCount}</span> : null}
                  </span>
                ) : null}
                {shelter.seashells > 0 ? (
                  <div className="absolute left-[calc(100%+0.15rem)] top-3 z-20 flex flex-col gap-0.5">
                    {Array.from({ length: shelter.seashells }).map((_, index) => (
                      <button
                        className="flex h-5 w-5 items-center justify-center overflow-hidden rounded-full border border-amber-200 bg-white text-[0.45rem] font-bold text-amber-900 shadow disabled:cursor-default"
                        disabled={!canMoveShellBack}
                        key={index}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (canMoveShellBack) onMoveShellFromShelter?.(node.id);
                        }}
                        onPointerDown={(event) => event.stopPropagation()}
                        title={canMoveShellBack ? "Move shell back to Poulpita" : "Stored shell"}
                        type="button"
                      >
                        {seashellImageUrl ? <img alt="" className="h-full w-full object-cover" draggable={false} src={seashellImageUrl} /> : "Sh"}
                      </button>
                    ))}
                  </div>
                ) : null}
                {nodeTiles.length ? (
                  <>
                    {nodeTiles.slice(0, 8).map((tileInstance, tileIndex) => {
                      const isRemoving = tileInstance.__animation === "removing";
                      const isFaceDown = tileInstance.face_up === false || !tileInstance.tile_id;
                      const tile = projection.tile_catalog?.tiles?.[tileInstance.tile_id];
                       const octopusToken = projection.tile_catalog?.tokens?.octopus;
                       const courtshipToken = projection.tile_catalog?.tokens?.courtship;
                       const isOctopusToken = Boolean(tileInstance.token_type === "octopus" || tile?.token_type === "octopus");
                       const isCourtshipToken = Boolean(tileInstance.token_type === "courtship" || tile?.token_type === "courtship");
                      const rawEvent = tile?.event || projection.tile_catalog?.events?.[tile?.event_id];
                      const event = isOctopusToken && rawEvent
                        ? { ...rawEvent, image_url: rawEvent.image_url || tile?.image_url || octopusToken?.image_url }
                        : rawEvent;
                      const interactionsById = projection.tile_catalog?.interactions || {};
                      const canInspect = !isRemoving && !isFaceDown && isCurrent && projection.phase === "night_action" && !pending;
                      const canRevealWithIntelligence = Boolean(
                        specialTargetMode === "intelligence"
                        && isFaceDown
                        && isAdjacent
                        && projection.phase === "night_action"
                        && !pending,
                      );
                      const canFocusedCapabilityInitiate =
                        canInspect &&
                        !projection.interaction &&
                         Boolean(isOctopusToken || isCourtshipToken || (tile?.event_id && (focusedCapability?.initiates_event_ids || []).includes(tile.event_id)));
                      const title = isFaceDown ? "Hidden tile" : tile?.name || event?.name || tileInstance.tile_id;
                      const position = tileOrbitPosition(tileIndex);
                      return (
                        <button
                          aria-disabled={!canInspect}
                          className={[
                            "group/tile absolute left-1/2 top-1/2 z-10 h-10 w-10 overflow-visible bg-transparent p-0",
                            canInspect || canRevealWithIntelligence ? "cursor-pointer" : "cursor-default",
                            canRevealWithIntelligence ? "rounded-full ring-2 ring-fuchsia-300" : "",
                            tileInstance.__animation === "placing" ? "board-tile-placing" : "",
                            isRemoving ? "board-tile-removing pointer-events-none" : "",
                          ].join(" ")}
                          key={tileInstance.instance_id}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (canRevealWithIntelligence) onSpecialTile?.(tileInstance.instance_id);
                            else if (canInspect) onInspectTile?.(tileInstance.instance_id);
                          }}
                          onMouseEnter={(mouseEvent) => {
                            if (!isFaceDown) showTilePreview(mouseEvent.currentTarget, tile, event, interactionsById, isCourtshipToken ? courtshipToken : octopusToken, isOctopusToken || isCourtshipToken);
                          }}
                          onMouseLeave={() => setHoveredTile(null)}
                          onPointerDown={(event) => event.stopPropagation()}
                          style={{
                            animationDelay: tileInstance.__animation === "placing" ? `${Math.min(tileIndex, 8) * 45}ms` : undefined,
                            transform: `translate(calc(-50% + ${position.x*1.2}px), calc(-50% + ${position.y*1.2}px))`,
                          }}
                          title={title}
                          type="button"
                        >
                           {(isOctopusToken || isCourtshipToken) && !isFaceDown ? (
                             <OctopusBoardToken highlighted={canFocusedCapabilityInitiate} interactionsById={interactionsById} tile={tile} title={title} token={isCourtshipToken ? courtshipToken : octopusToken} />
                          ) : (
                            <BoardTileToken event={event} faceDown={isFaceDown} highlighted={canFocusedCapabilityInitiate} title={title} />
                          )}
                        </button>
                      );
                    })}
                    {nodeTiles.length > 8 ? <span className="absolute left-1/2 top-1/2 z-10 translate-x-8 -translate-y-2 text-xs font-semibold text-white">+{nodeTiles.length - 8}</span> : null}
                  </>
                ) : null}
              </div>
            );
          })}
          {currentNodeId && projection.map.nodes[currentNodeId] ? (
            <div
              aria-label="Poulpita"
              className="pointer-events-none absolute z-30 flex h-[3.25rem] w-[3.25rem] -translate-x-1/2 -translate-y-1/2 items-center justify-center transition-[left,top] duration-700 ease-in-out"
              style={{
                left: `${projection.map.nodes[currentNodeId].x * 100}%`,
                top: `${projection.map.nodes[currentNodeId].y * 100}%`,
              }}
            >
              {(() => {
                const sizes = projection.tile_catalog?.poulpita_panel?.sizes || [];
                const sizeIndex = Math.max(0, Number(projection.poulpita?.size_index || 0));
                const sizeImage = sizes[sizeIndex]?.image_url;
                return sizeImage ? (
                  <img alt="Poulpita" className="h-[3.25rem] w-[3.25rem] select-none object-contain drop-shadow-[0_3px_5px_rgba(8,47,73,0.7)]" draggable={false} src={buildApiUrl(sizeImage)} />
                ) : (
                  <span className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-teal-100 bg-teal-300 text-sm font-bold text-teal-950 shadow-lg">P</span>
                );
              })()}
            </div>
          ) : null}
        </div>
      </div>
      {hoveredTile ? (
        <div
          className={["pointer-events-none absolute z-[80]", hoveredTile.isOctopusToken ? "w-32" : "w-40 shadow-2xl"].join(" ")}
          style={{ left: hoveredTile.left, top: hoveredTile.top }}
        >
          {hoveredTile.isRoundToken ? (
            <OctopusBoardToken interactionsById={hoveredTile.interactionsById} large tile={hoveredTile.tile} title={hoveredTile.tile?.name || hoveredTile.event?.name || "Octopus token"} token={hoveredTile.token} />
          ) : (
            <HexTilePreview
              className="max-w-none"
              event={hoveredTile.event}
              interactionsById={hoveredTile.interactionsById}
              tile={hoveredTile.tile}
            />
          )}
        </div>
      ) : null}
    </section>
  );
};

export default BoardView;
