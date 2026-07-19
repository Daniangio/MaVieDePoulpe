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
  size_index?: number;
  size_upgraded_today?: boolean;
};

export type CardProjection = {
  card_id: string;
  interaction_id: string;
  interaction_ids?: string[];
  owner_capability_id?: string;
  capability_id?: string;
  upgraded?: boolean;
};

export type CapabilityProjection = {
  id: string;
  name: string;
  controller_type?: "human" | "bot" | "shared";
  controller_seat_id?: string;
  is_human_controlled?: boolean;
  is_bot_controlled?: boolean;
  is_shared_controlled?: boolean;
  pa: number;
  control_takes_this_night: number;
  actions_taken_this_control: number;
  max_actions_per_control: number;
  max_control_takes_per_night: number;
  current_max_cards_in_hand?: number;
  default_max_cards_in_hand?: number;
  hand_size_upgrades?: Array<{
    type?: "hand_size" | "deck_exchange";
    cost_resource?: string;
    cost?: number;
    hand_size_bonus?: number;
    remove_cards?: Array<{ interaction_id: string; count: number }>;
    add_cards?: Array<{ interaction_ids: string[]; count: number }>;
  }>;
  purchased_hand_size_upgrade_indices?: number[];
  initiates_event_ids?: string[];
  draw_pile?: CardProjection[];
  hand?: CardProjection[];
  discard?: CardProjection[];
};

export type PlayerProjection = {
  id: string;
  seat_id: string;
  display_name: string;
  controller_type?: "human" | "bot" | "shared";
  controller_seat_id?: string;
};

export type BotRoomConfig = {
  mode: "solo_with_bots";
  human_ability_id: string;
  privacy_mode: "solo_faithful" | "omniscient_debug";
  controllers: Array<{
    ability_id: string;
    controller_type: "human" | "bot" | "shared";
    seat_id?: string | null;
  }>;
};

export type BotPlanSummary = {
  plan_id: string;
  proposer_ability_id?: string | null;
  title: string;
  rationale: string;
  risk_label: "low" | "moderate" | "high" | "forced" | string;
  confidence?: number | null;
  step_preview: string[];
  plan_chain?: Array<{
    index?: number;
    label: string;
    command_type?: string | null;
    public_command?: {
      type: string;
      payload?: Record<string, any>;
    } | null;
    auto_executable?: boolean;
    decision_boundary?: boolean;
    statistics?: {
      efficiency?: number;
      confidence_score?: number;
      risk_score?: number;
      expected_gain_score?: number;
      planned_action_capacity?: number;
      planned_actions_used?: number;
      wasted_current_actions?: number;
      initiative_switch_penalty?: number;
      actions_used_by_ability?: Record<string, number>;
      step_index?: number;
    };
  }>;
  expected_resources?: {
    ap_by_ability?: Record<string, number>;
    time_steps?: number;
    control_takes_by_ability?: Record<string, number>;
    expected_ap_gain_by_ability?: Record<string, number>;
    energy_delta_expected?: number;
    shells_delta_expected?: number;
    neurons_delta_expected?: number;
    expected_resource_delta?: Record<string, number>;
  };
  statistics?: {
    success_probability?: number;
    interaction_probabilities?: Array<Record<string, any>>;
    interaction_summaries?: Array<Record<string, any>>;
    expected_resource_delta?: Record<string, number>;
    distance_to_closest_known_shelter?: number | null;
    estimated_take_controls?: number;
    estimated_actions?: number;
    estimated_time_steps?: number;
    efficiency?: number;
    confidence_score?: number;
    expected_gain_score?: number;
    planner_score?: number;
    planned_action_capacity?: number;
    planned_actions_used?: number;
    wasted_current_actions?: number;
    initiative_switch_penalty?: number;
    actions_used_by_ability?: Record<string, number>;
    pareto_axes?: Record<string, number>;
    expected_ap_roll?: number;
    planning_depth_take_controls?: number;
    assumptions?: string[];
  };
  objective_effect?: string | null;
  warnings?: string[];
  commands?: Array<Record<string, any>>;
};

export type BotPlanStatus = {
  status: "disabled" | "idle" | "planning" | "awaiting_selection" | "executing" | "awaiting_human" | "error";
  proposal_set_id?: string | null;
  generated_from_version?: number;
  proposals: BotPlanSummary[];
  message?: string;
  debug?: Record<string, any>;
};

export type GameProjection = {
  room_id: string;
  projection_mode: "goldfish";
  privacy_enforced: false;
  mode: "goldfish" | "solo_with_bots";
  bot_config?: BotRoomConfig | null;
  version: number;
  phase: "setup" | "night_idle" | "night_action" | "day" | "game_over";
  level_id: string;
  day_index: number;
  night_time_spent: number;
  night_time_total?: number;
  night_shelter_available_at?: number;
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
  shelters?: Record<NodeId, number | { count?: number; seashells?: number; secure?: boolean }>;
  objectives?: Array<Record<string, any>>;
  objective_progress?: Record<string, any>;
  tile_catalog?: {
    tiles?: Record<string, any>;
    events?: Record<string, any>;
    interactions?: Record<string, any>;
    cards?: Record<string, any>;
    card_categories?: Array<Record<string, any>>;
    tokens?: Record<string, any>;
    poulpita_panel?: Record<string, any>;
    bot_settings?: Record<string, any>;
  };
  interaction?: any;
  pending_surprise?: any;
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
