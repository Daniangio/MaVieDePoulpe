import { buildApiUrl } from "../utils/connection.js";
import type { GameProjection, NodeId } from "../types/game";

type BoardViewProps = {
  projection: GameProjection;
  pending: boolean;
  onMove: (targetNodeId: NodeId) => void;
};

const BoardView = ({ projection, pending, onMove }: BoardViewProps) => {
  const currentNodeId = projection.poulpita.node_id;
  const adjacentNodeIds = currentNodeId ? projection.map.adjacency[currentNodeId] || [] : [];
  const nodes = Object.values(projection.map.nodes).sort((a, b) => a.x - b.x || a.y - b.y);
  const imageUrl = projection.map.image_url ? buildApiUrl(projection.map.image_url) : "";
  const imageWidth = Number(projection.map.image_width || 0);
  const imageHeight = Number(projection.map.image_height || 0);
  const aspectRatio = imageWidth > 0 && imageHeight > 0 ? `${imageWidth} / ${imageHeight}` : "11 / 4";

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-semibold text-white">{projection.map.name || "Board"}</h2>
        <span className="text-xs text-slate-500">{nodes.length} nodes</span>
      </div>

      <div className="relative mx-auto w-full overflow-hidden rounded-lg border border-slate-800 bg-slate-950" style={{ aspectRatio, maxWidth: imageWidth || undefined }}>
        {imageUrl ? <img alt={projection.map.name || "Game board"} className="absolute inset-0 h-full w-full object-contain" src={imageUrl} /> : null}
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
          {Object.entries(projection.map.adjacency).flatMap(([fromId, adjacentIds]) =>
            adjacentIds
              .filter((toId) => fromId < toId)
              .map((toId) => {
                const from = projection.map.nodes[fromId];
                const to = projection.map.nodes[toId];
                if (!from || !to) return null;
                return (
                  <line
                    key={`${fromId}:${toId}`}
                    stroke="rgba(148, 163, 184, 0.55)"
                    strokeWidth="0.006"
                    x1={from.x}
                    x2={to.x}
                    y1={from.y}
                    y2={to.y}
                  />
                );
              })
          )}
        </svg>
        {nodes.map((node) => {
          const isCurrent = node.id === currentNodeId;
          const isPrevious = node.id === projection.poulpita.previous_node_id;
          const isAdjacent = adjacentNodeIds.includes(node.id);
          const canMove = projection.phase === "night_action" && isAdjacent && !pending;
          return (
            <button
              className={[
                "absolute flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border text-xs transition",
                isCurrent
                  ? "border-teal-200 bg-teal-300 text-slate-950 shadow-lg shadow-teal-950/40"
                  : isAdjacent
                    ? "border-teal-500/70 bg-slate-950/90 text-white hover:bg-teal-950"
                    : "border-slate-700 bg-slate-950/80 text-slate-300",
                canMove ? "cursor-pointer" : "cursor-default",
              ].join(" ")}
              disabled={!canMove}
              key={node.id}
              onClick={() => onMove(node.id)}
              style={{
                left: `${node.x * 100}%`,
                top: `${node.y * 100}%`,
              }}
              type="button"
            >
              <span className="font-semibold">{node.id}</span>
              {isCurrent ? <span className="mt-1 text-xl leading-none">P</span> : null}
              {isPrevious && !isCurrent ? <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-slate-500" /> : null}
            </button>
          );
        })}
      </div>
    </section>
  );
};

export default BoardView;
