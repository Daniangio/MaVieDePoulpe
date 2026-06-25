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
  energy?: number;
  neurons?: number;
  seashells?: number;
};

export type CardProjection = {
  card_id: string;
  interaction_id: string;
  owner_capability_id?: string;
  capability_id?: string;
};

export type CapabilityProjection = {
  id: string;
  name: string;
  pa: number;
  control_takes_this_night: number;
  actions_taken_this_control: number;
  max_actions_per_control: number;
  max_control_takes_per_night: number;
  current_max_cards_in_hand?: number;
  initiates_event_ids?: string[];
  draw_pile?: CardProjection[];
  hand?: CardProjection[];
  discard?: CardProjection[];
};

export type PlayerProjection = {
  id: string;
  seat_id: string;
  display_name: string;
};

export type GameProjection = {
  room_id: string;
  projection_mode: "goldfish";
  privacy_enforced: false;
  mode: "goldfish";
  version: number;
  phase: "setup" | "night_idle" | "night_action" | "game_over";
  level_id: string;
  day_index: number;
  night_time_spent: number;
  selected_level_id?: string;
  selected_map_id?: string;
  active_capability_id: string | null;
  last_active_capability_id: string | null;
  focused_capability_id: string;
  capability_order: string[];
  capabilities: Record<string, CapabilityProjection>;
  players: PlayerProjection[];
  player_boards: CapabilityProjection[];
  map: MapProjection;
  poulpita: PoulpitaProjection;
  tiles?: Record<NodeId, Array<{ instance_id: string; tile_id: string; face_up?: boolean }>>;
  tile_catalog?: {
    tiles?: Record<string, any>;
    events?: Record<string, any>;
    interactions?: Record<string, any>;
    cards?: Record<string, any>;
    card_categories?: Array<Record<string, any>>;
    tokens?: Record<string, any>;
    poulpita_panel?: Record<string, any>;
  };
  interaction?: any;
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
