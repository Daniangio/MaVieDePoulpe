import { useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { buildApiUrl } from "../utils/connection.js";
import type { GameProjection, NodeId } from "../types/game";

type BoardViewProps = {
  projection: GameProjection;
  moveMode: boolean;
  pending: boolean;
  onMove: (targetNodeId: NodeId) => void;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const BoardView = ({ projection, moveMode, pending, onMove }: BoardViewProps) => {
  const currentNodeId = projection.poulpita.node_id;
  const adjacentNodeIds = currentNodeId ? projection.map.adjacency[currentNodeId] || [] : [];
  const nodes = useMemo(() => Object.values(projection.map.nodes).sort((a, b) => a.x - b.x || a.y - b.y), [projection.map.nodes]);
  const imageUrl = projection.map.image_url ? buildApiUrl(projection.map.image_url) : "";
  const imageWidth = Number(projection.map.image_width || 0);
  const imageHeight = Number(projection.map.image_height || 0);
  const aspectRatio = imageWidth > 0 && imageHeight > 0 ? `${imageWidth} / ${imageHeight}` : "11 / 4";
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);

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
    <section className="relative h-full overflow-hidden bg-slate-950">
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
            return (
              <button
                className={[
                  "absolute flex h-10 w-10 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border text-xs font-semibold shadow-lg transition",
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
                key={node.id}
                onClick={(event) => {
                  event.stopPropagation();
                  onMove(node.id);
                }}
                onPointerDown={(event) => event.stopPropagation()}
                style={{
                  left: `${node.x * 100}%`,
                  top: `${node.y * 100}%`,
                }}
                type="button"
              >
                <span>{isCurrent ? "P" : node.id}</span>
                {isPrevious && !isCurrent ? <span className="absolute right-0 top-0 h-2 w-2 rounded-full bg-slate-400" /> : null}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default BoardView;
