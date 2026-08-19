from backend.app.game_analytics_service import build_level_analytics


def test_level_analytics_aggregates_resource_actions_specials_and_node_density():
    games = [
        {
            "id": "saved_1",
            "source": "saved_game",
            "created_at": "2026-08-19T10:00:00+00:00",
            "level_id": "reef",
            "mode": "goldfish",
            "outcome": "won",
            "game_over_reason": "objectives_completed",
            "map": {
                "id": "reef-map",
                "nodes": {
                    "N1": {"id": "N1", "x": 0.2, "y": 0.3},
                    "N2": {"id": "N2", "x": 0.8, "y": 0.7},
                },
            },
            "points": [
                {"day_index": 1, "energy": 5, "neurons": 1, "node_id": "N1", "command_type": "start_goldfish_game", "capability_id": "", "event_types": []},
                {"day_index": 1, "energy": 7, "neurons": 4, "node_id": "N1", "command_type": "resolve_interaction", "capability_id": "force", "event_types": ["interaction_resolved"]},
                {"day_index": 1, "energy": 5, "neurons": 2, "node_id": "N2", "command_type": "use_special_power", "capability_id": "propulsion", "event_types": ["special_power_used"]},
                {"day_index": 2, "energy": 4, "neurons": 0, "node_id": "N2", "command_type": "buy_hand_size_upgrade", "capability_id": "intelligence", "event_types": ["hand_size_upgrade_bought"]},
            ],
        }
    ]

    result = build_level_analytics(level_id="reef", games=games)
    analytics = result["analytics"]

    assert analytics["overview"]["games"] == 1
    assert analytics["overview"]["win_rate"] == 100.0
    assert analytics["resource_distributions"]["energy_gained_per_night"] == [{"value": 0, "count": 1}, {"value": 2, "count": 1}]
    assert analytics["resource_distributions"]["energy_lost_per_night"] == [{"value": 1, "count": 1}, {"value": 2, "count": 1}]
    assert analytics["resource_distributions"]["neurons_gained_per_night"] == [{"value": 0, "count": 1}, {"value": 3, "count": 1}]
    assert analytics["resource_distributions"]["neurons_spent_per_night"] == [{"value": 2, "count": 2}]
    assert analytics["special_abilities"] == [{"ability_id": "propulsion", "count": 1}]
    assert analytics["upgrades_by_day"] == [{"day": 2, "count": 1}]
    assert analytics["interaction_outcomes"]["resolved"] == 1
    assert analytics["node_visits"] == [{"node_id": "N1", "count": 1}, {"node_id": "N2", "count": 1}]
    force_actions = next(entry for entry in analytics["actions_by_ability"] if entry["ability_id"] == "force")
    assert force_actions["actions"] == [{"id": "resolve_interaction", "label": "Resolve interaction", "count": 1}]

    filtered = build_level_analytics(level_id="reef", games=games, selected_nights={1})["analytics"]
    assert filtered["resource_filter"] == {
        "available_nights": [1, 2],
        "selected_nights": [1],
        "samples": 1,
        "totals": {
            "energy_gained_per_night": 2,
            "energy_lost_per_night": 2,
            "neurons_gained_per_night": 3,
            "neurons_spent_per_night": 2,
        },
    }
    assert filtered["resource_distributions"]["energy_lost_per_night"] == [{"value": 2, "count": 1}]
