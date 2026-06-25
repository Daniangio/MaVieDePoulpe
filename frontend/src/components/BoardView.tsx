import { useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import HexTilePreview from "./HexTilePreview.jsx";
import { buildApiUrl } from "../utils/connection.js";
import type { GameProjection, NodeId } from "../types/game.js";

type BoardViewProps = {
  projection: GameProjection;
  focusedCapabilityId?: string | null;
  moveMode: boolean;
  pending: boolean;
  onMove: (targetNodeId: NodeId) => void;
  onInspectTile?: (tileInstanceId: string) => void;
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

const BoardView = ({ projection, focusedCapabilityId, moveMode, pending, onMove, onInspectTile }: BoardViewProps) => {
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
    left: number;
    top: number;
  } | null>(null);
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);

  const showTilePreview = (target: HTMLElement, tile: any, event: any, interactionsById: Record<string, any>) => {
    const boardRect = boardRef.current?.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    if (!boardRect) return;
    const previewWidth = 160;
    const previewHeight = 156;
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
            const nodeTiles = projection.tiles?.[node.id] || [];
            const shelterCount = Number(projection.shelters?.[node.id] || 0);
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
                    canMove ? "cursor-pointer" : "cursor-default",
                  ].join(" ")}
                  disabled={!canMove}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (canMove) onMove(node.id);
                  }}
                  onPointerDown={(event) => event.stopPropagation()}
                  type="button"
                >
                  <span>{isCurrent ? "P" : node.id}</span>
                  {isPrevious && !isCurrent ? <span className="absolute right-0 top-0 h-2 w-2 rounded-full bg-slate-400" /> : null}
                  {shelterCount > 0 ? (
                    <span className="absolute -left-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full border border-cyan-100 bg-cyan-200 px-1 text-[0.55rem] font-bold text-teal-950" title={`${shelterCount} shelter token${shelterCount === 1 ? "" : "s"}`}>
                      {shelterCount > 1 ? shelterCount : "S"}
                    </span>
                  ) : null}
                </button>
                {nodeTiles.length ? (
                  <div className="absolute left-1/2 top-11 flex -translate-x-1/2 gap-1">
                    {nodeTiles.slice(0, 4).map((tileInstance) => {
                      const isFaceDown = tileInstance.face_up === false || !tileInstance.tile_id;
                      const tile = projection.tile_catalog?.tiles?.[tileInstance.tile_id];
                      const event = tile?.event || projection.tile_catalog?.events?.[tile?.event_id];
                      const interactionsById = projection.tile_catalog?.interactions || {};
                      const canInspect = !isFaceDown && isCurrent && projection.phase === "night_action" && !pending;
                      const canFocusedCapabilityInitiate =
                        canInspect &&
                        !projection.interaction &&
                        Boolean(tile?.event_id && (focusedCapability?.initiates_event_ids || []).includes(tile.event_id));
                      const title = isFaceDown ? "Hidden tile" : tile?.name || event?.name || tileInstance.tile_id;
                      return (
                        <button
                          aria-disabled={!canInspect}
                          className={[
                            "group/tile relative h-8 w-8 overflow-visible bg-transparent p-0",
                            canInspect ? "cursor-pointer" : "cursor-default",
                          ].join(" ")}
                          key={tileInstance.instance_id}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (canInspect) onInspectTile?.(tileInstance.instance_id);
                          }}
                          onMouseEnter={(mouseEvent) => {
                            if (!isFaceDown) showTilePreview(mouseEvent.currentTarget, tile, event, interactionsById);
                          }}
                          onMouseLeave={() => setHoveredTile(null)}
                          onPointerDown={(event) => event.stopPropagation()}
                          title={title}
                          type="button"
                        >
                          <BoardTileToken event={event} faceDown={isFaceDown} highlighted={canFocusedCapabilityInitiate} title={title} />
                        </button>
                      );
                    })}
                    {nodeTiles.length > 4 ? <span className="text-xs text-white">+{nodeTiles.length - 4}</span> : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      {hoveredTile ? (
        <div
          className="pointer-events-none absolute z-[80] w-40 shadow-2xl"
          style={{ left: hoveredTile.left, top: hoveredTile.top }}
        >
          <HexTilePreview
            className="max-w-none"
            event={hoveredTile.event}
            interactionsById={hoveredTile.interactionsById}
            tile={hoveredTile.tile}
          />
        </div>
      ) : null}
    </section>
  );
};

export default BoardView;
