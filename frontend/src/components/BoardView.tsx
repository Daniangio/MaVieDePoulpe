import type { GameProjection, NodeId } from "../types/game";

type BoardViewProps = {
  projection: GameProjection;
  pending: boolean;
  onMove: (targetNodeId: NodeId) => void;
};

const gridColumns = "repeat(11, minmax(3rem, 1fr))";

const BoardView = ({ projection, pending, onMove }: BoardViewProps) => {
  const currentNodeId = projection.poulpita.node_id;
  const adjacentNodeIds = currentNodeId ? projection.map.adjacency[currentNodeId] || [] : [];
  const nodes = Object.values(projection.map.nodes).sort((a, b) => a.x - b.x || a.y - b.y);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div
        className="grid gap-3"
        style={{
          gridTemplateColumns: gridColumns,
        }}
      >
        {nodes.map((node) => {
          const isCurrent = node.id === currentNodeId;
          const isPrevious = node.id === projection.poulpita.previous_node_id;
          const isAdjacent = adjacentNodeIds.includes(node.id);
          const canMove = projection.phase === "night_action" && isAdjacent && !pending;
          return (
            <button
              className={[
                "relative flex aspect-square min-h-14 flex-col items-center justify-center rounded-md border text-sm transition",
                isCurrent
                  ? "border-teal-200 bg-teal-300 text-slate-950 shadow-lg shadow-teal-950/40"
                  : isAdjacent
                    ? "border-teal-500/70 bg-slate-800 text-white hover:bg-teal-950"
                    : "border-slate-700 bg-slate-950 text-slate-300",
                canMove ? "cursor-pointer" : "cursor-default",
              ].join(" ")}
              disabled={!canMove}
              key={node.id}
              onClick={() => onMove(node.id)}
              style={{
                gridColumn: node.x + 1,
                gridRow: node.y + 1,
              }}
              type="button"
            >
              <span className="font-semibold">{node.id}</span>
              <span className="mt-1 text-[10px] uppercase tracking-[0.12em] opacity-70">Tier {node.tier}</span>
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
