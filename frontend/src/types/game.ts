export type NodeId = string;

export type BoardNode = {
  id: NodeId;
  tier: number;
  x: number;
  y: number;
};

export type MapProjection = {
  id?: string;
  name?: string;
  image_url?: string | null;
  image_width?: number | null;
  image_height?: number | null;
  nodes: Record<NodeId, BoardNode>;
  adjacency: Record<NodeId, NodeId[]>;
};

export type PoulpitaProjection = {
  node_id: NodeId | null;
  previous_node_id: NodeId | null;
};

export type GameProjection = {
  room_id: string;
  projection_mode: "goldfish";
  privacy_enforced: false;
  mode: "goldfish";
  version: number;
  phase: "setup" | "night_action" | "game_over";
  level_id: string;
  selected_map_id?: string;
  active_capability_id: string | null;
  last_active_capability_id: string | null;
  map: MapProjection;
  poulpita: PoulpitaProjection;
  events: Array<Record<string, unknown>>;
};

export type CommandRejection = {
  ok: false;
  command_id: string;
  reason: string;
  message: string;
  current_version: number;
  projection?: GameProjection;
};
