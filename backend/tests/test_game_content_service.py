import asyncio
from io import BytesIO

from starlette.datastructures import UploadFile

from backend.app import game_content_service as service
from backend.app import map_service


def run(coro):
    return asyncio.run(coro)


def test_generated_cards_group_tile_events_by_category(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    service._write_content(
        {
            "categories": [
                {"id": "prey", "name": "Prey"},
                {"id": "threat", "name": "Threat"},
            ],
            "interactions": [
                {"id": "charge", "name": "Charge", "image_filename": "charge.png"},
                {"id": "tighten", "name": "Tighten", "image_filename": "tighten.png"},
            ],
            "events": [
                {"id": "crab", "name": "Crab", "category_id": "prey", "image_filename": "crab.png"},
                {"id": "shark", "name": "Shark", "category_id": "threat", "image_filename": "shark.png"},
            ],
            "tiles": [
                {
                    "id": "crab-tile",
                    "name": "Crab",
                    "event_id": "crab",
                    "interaction_ids": ["charge", "tighten"],
                    "counter_attack_interaction_ids": ["charge"],
                    "success_effects": [{"type": "gain_energy", "amount": 2}],
                    "counter_attack_effects": [{"type": "gain_seashells", "amount": 1}],
                    "failure_effects": [
                        {"type": "lose_half_ap", "amount": None},
                        {"type": "pulpita_move_free", "amount": None},
                        {"type": "remove_preys", "amount": None, "category_id": "prey"},
                        {"type": "remove_tile", "amount": None},
                    ],
                },
                {"id": "shark-tile", "name": "Shark", "event_id": "shark", "interaction_ids": ["tighten"]},
            ],
        }
    )

    cards = {card["id"]: card for card in service.get_content_state()["cards"]}

    assert [entry["event_name"] for entry in cards["charge"]["resolves"]["prey"]] == ["Crab"]
    assert cards["charge"]["resolves"]["threat"] == []
    assert [entry["event_name"] for entry in cards["charge"]["resolves"][service.COUNTER_ATTACK_CATEGORY_ID]] == ["Crab"]
    assert [entry["event_name"] for entry in cards["tighten"]["resolves"]["prey"]] == ["Crab"]
    assert [entry["event_name"] for entry in cards["tighten"]["resolves"]["threat"]] == ["Shark"]
    assert cards["tighten"]["resolves"][service.COUNTER_ATTACK_CATEGORY_ID] == []
    assert service.get_content_state()["tiles"][0]["failure_effects"] == [
        {"type": "lose_half_ap", "amount": None},
        {"type": "pulpita_move_free", "amount": None},
        {"type": "remove_preys", "amount": None, "category_id": "prey"},
        {"type": "remove_tile", "amount": None},
    ]


def test_player_board_config_is_fixed_to_five_boards_and_validates_interactions(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    service._write_content(
        {
            "categories": [],
            "interactions": [{"id": "charge", "name": "Charge", "image_filename": "charge.png"}],
            "events": [{"id": "crab", "name": "Crab", "category_id": "prey", "image_filename": "crab.png"}],
            "tiles": [],
            "player_boards": [],
        }
    )

    board = service.save_player_board(
        board_id="agility",
        name="Agility",
        initiates_event_ids=["crab"],
        deck=[{"interaction_id": "charge", "count": 4}],
        default_max_cards_in_hand=3,
        hand_size_upgrades=[{"cost_resource": "energy", "cost": 2, "hand_size_bonus": 1}],
        actions_per_control=2,
        control_takes_per_night=4,
        initial_ap=7,
    )
    state = service.get_content_state()

    assert board["deck"] == [{"interaction_id": "charge", "count": 4}]
    assert len(state["player_boards"]) == 5
    assert state["player_boards"][0]["initiates_event_ids"] == ["crab"]
    assert state["player_boards"][0]["actions_per_control"] == 2
    assert state["player_boards"][0]["initial_ap"] == 7


def test_player_board_can_define_deck_exchange_upgrades(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    service._write_content(
        {
            "categories": [],
            "interactions": [
                {"id": "charge", "name": "Charge", "image_filename": None},
                {"id": "hide", "name": "Hide", "image_filename": None},
            ],
            "events": [],
            "tiles": [],
            "player_boards": [],
        }
    )

    board = service.save_player_board(
        board_id="force",
        name="Force",
        initiates_event_ids=[],
        deck=[{"interaction_id": "charge", "count": 3}, {"interaction_id": "hide", "count": 2}],
        default_max_cards_in_hand=3,
        hand_size_upgrades=[
            {
                "type": "deck_exchange",
                "cost": 2,
                "remove_cards": [{"interaction_id": "charge", "count": 1}],
                "add_cards": [{"interaction_ids": ["charge", "hide"], "count": 1}],
            }
        ],
        actions_per_control=3,
        control_takes_per_night=3,
    )

    assert board["hand_size_upgrades"] == [
        {
            "type": "deck_exchange",
            "cost_resource": "neurons",
            "cost": 2,
            "remove_cards": [{"interaction_id": "charge", "count": 1}],
            "add_cards": [{"interaction_ids": ["charge", "hide"], "count": 1}],
        }
    ]


def test_action_costs_and_shell_tile_requirement_are_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    service._write_content(
        {
            "categories": [],
            "interactions": [{"id": "charge", "name": "Charge", "image_filename": None}],
            "events": [{"id": "crab", "name": "Crab", "category_id": "", "image_filename": None}],
            "tiles": [],
        }
    )

    costs = service.update_action_costs({"interact": {"ap_cost": 2, "time_cost": 3, "neuron_cost": 1}})
    tile = service.save_tile(
        name="Shell threat",
        event_id="crab",
        priority=0,
        shell_requirement_count=2,
        interaction_ids=["charge"],
    )

    state = service.get_content_state()
    assert costs["interact"] == {"ap_cost": 2, "time_cost": 3, "neuron_cost": 1}
    assert costs["move"] == {"ap_cost": 1, "time_cost": 1, "neuron_cost": 0}
    assert tile["shell_requirement_count"] == 2
    assert state["action_costs"]["interact"]["time_cost"] == 3


def test_bot_settings_include_efficiency_weights_and_ability_colors(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    service._write_content(
        {
            "categories": [],
            "interactions": [],
            "events": [],
            "tiles": [],
            "player_boards": [],
        }
    )

    settings = service.update_bot_settings(
        {
            "expected_ap_roll": 4,
            "planning_depth_take_controls": 5,
            "orchestrator_rollout_take_controls": 4,
            "orchestrator_rollouts_per_plan": 2,
            "orchestrator_sampling_temperature": 0.7,
            "orchestrator_max_candidates": 6,
            "max_plans": 12,
            "min_energy_after_size_upgrade": 6,
            "weights": {
                "efficiency": 50,
                "confidence": 25,
                "expected_gain": 25,
                "tile_resolution": 18,
                "compulsory_tile_resolution": 42,
                "third_ability_penalty": 60,
                "late_shelter_urgency": 11,
            },
            "resource_weights": {"energy": 10, "neurons": 7},
            "ability_colors": {"force": "#aa0000", "agility": "not-a-color"},
        }
    )

    assert settings["expected_ap_roll"] == 4
    assert settings["planning_depth_take_controls"] == 5
    assert settings["orchestrator_rollout_take_controls"] == 4
    assert settings["orchestrator_rollouts_per_plan"] == 2
    assert settings["orchestrator_sampling_temperature"] == 0.7
    assert settings["orchestrator_max_candidates"] == 6
    assert settings["max_plans"] == 12
    assert settings["min_energy_after_size_upgrade"] == 6
    assert settings["weights"]["efficiency"] == 50
    assert settings["weights"]["tile_resolution"] == 18
    assert settings["weights"]["compulsory_tile_resolution"] == 42
    assert settings["weights"]["third_ability_penalty"] == 60
    assert settings["weights"]["late_shelter_urgency"] == 11
    assert settings["resource_weights"]["energy"] == 10
    assert settings["resource_weights"]["neurons"] == 7
    assert settings["ability_colors"]["force"] == "#aa0000"
    assert settings["ability_colors"]["agility"] == service.DEFAULT_BOT_SETTINGS["ability_colors"]["agility"]


def test_level_save_validates_group_capacity_and_node_assignment(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")
    monkeypatch.setattr(
        service,
        "get_map",
        lambda _map_id: {
            "id": "reef",
            "name": "Reef",
            "nodes": {
                "N1": {"id": "N1", "x": 0.1, "y": 0.1, "tier": 1},
                "N2": {"id": "N2", "x": 0.5, "y": 0.5, "tier": 1},
            },
        },
    )

    service._write_content(
        {
            "categories": [],
            "interactions": [],
            "events": [],
            "tiles": [
                {"id": "crab", "name": "Crab", "event_id": "crab-event", "interaction_ids": []},
                {"id": "fish", "name": "Small fish", "event_id": "fish-event", "interaction_ids": []},
            ],
            "player_boards": [],
            "levels": [],
        }
    )

    level = service.save_level(
        name="Night 1",
        map_id="reef",
        node_tile_counts={"N1": 2, "N2": 1},
        node_group_ids={"N1": "shore", "N2": "deep"},
        groups=[
            {"id": "shore", "name": "Shore", "tile_counts": {"crab": 2}},
            {"id": "deep", "name": "Deep", "tile_counts": {"fish": 1}},
        ],
        objectives=[{"type": "increase_size", "target": 2}, {"type": "find_shelter"}],
        starting_energy=7,
        max_energy=24,
        starting_neurons=4,
        night_duration_steps=18,
        max_nights=6,
        courtship_min_size_index=2,
        courtship_min_energy=9,
        win_min_energy=6,
        size_deadline_night=5,
        tile_sets=[
            {
                "id": "adult-set",
                "size_index": 2,
                "groups": [
                    {"id": "shore", "name": "Shore", "tile_counts": {"fish": 2}},
                    {"id": "deep", "name": "Deep", "tile_counts": {"crab": 1}},
                ],
            }
        ],
    )

    assert level["node_tile_counts"] == {"N1": 2, "N2": 1}
    assert level["starting_energy"] == 7
    assert level["max_energy"] == 24
    assert level["starting_neurons"] == 4
    assert level["night_duration_steps"] == 18
    assert level["max_nights"] == 6
    assert level["courtship_min_size_index"] == 2
    assert level["courtship_min_energy"] == 9
    assert level["win_min_energy"] == 6
    assert level["size_deadline_night"] == 5
    assert level["tile_sets"][0]["groups"][0]["tile_counts"] == {"fish": 2}
    assert level["objectives"] == [
        {"id": "objective-1", "type": "increase_size", "target": 2},
        {"id": "objective-2", "type": "find_shelter"},
    ]
    assert len(service.get_content_state()["levels"]) == 1

    try:
        service.save_level(
            name="Invalid",
            map_id="reef",
            node_tile_counts={"N1": 2, "N2": 1},
            node_group_ids={"N1": "shore", "N2": "deep"},
            groups=[{"id": "shore", "name": "Shore", "tile_counts": {"crab": 1}}, {"id": "deep", "name": "Deep", "tile_counts": {"fish": 1}}],
        )
    except ValueError as exc:
        assert "has 1 assigned tiles but needs 2" in str(exc)
    else:
        raise AssertionError("Expected invalid group capacity to be rejected.")


def test_tokens_and_poulpita_panel_are_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    state = service.get_content_state()

    assert [token["id"] for token in state["tokens"]] == ["neuron", "seashell", "shelter", "octopus", "courtship"]
    assert set(state["poulpita_panel"]["zones"]) == {"neurons", "seashells"}

    saved = run(
        service.update_poulpita_panel(
            zones={
                "neurons": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                "seashells": {"x": 0.5, "y": 0.2, "width": 0.3, "height": 0.4},
            },
            image=None,
            image_width=800,
            image_height=600,
        )
    )

    assert saved["image_width"] == 800
    assert saved["image_height"] == 600
    assert saved["zones"]["neurons"] == {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}
    resized = run(
        service.update_poulpita_panel(
            zones=saved["zones"],
            sizes=[{"amount": 500, "unit": "mg", "energy_cost": 99}, {"kg": 1.2, "unit": "g", "energy_cost": 2}],
            image=None,
            image_width=800,
            image_height=600,
        )
    )
    assert [{key: size[key] for key in ["amount", "unit", "energy_cost"]} for size in resized["sizes"]] == [
        {"amount": 500.0, "unit": "mg", "energy_cost": 0},
        {"amount": 1.2, "unit": "g", "energy_cost": 2},
    ]
    with_size_image = run(
        service.update_poulpita_panel(
            zones=resized["zones"],
            sizes=resized["sizes"],
            size_images={0: UploadFile(filename="poulpita.png", file=BytesIO(b"poulpita-image"))},
            image=None,
            image_width=800,
            image_height=600,
        )
    )
    assert with_size_image["sizes"][0]["image_url"].startswith("/static/content/images/poulpita-size-1-")
    assert with_size_image["sizes"][1]["image_url"] == with_size_image["sizes"][0]["image_url"]
    assert with_size_image["sizes"][1]["uses_previous_image"] is True
    assert service.get_game_content_catalog()["poulpita_panel"]["zones"]["seashells"]["x"] == 0.5


def test_courtship_cards_preserve_repeated_required_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")
    service._write_content(
        {
            "categories": [],
            "interactions": [
                {"id": "dance", "name": "Dance", "image_filename": None},
                {"id": "display", "name": "Display", "image_filename": None},
            ],
            "events": [],
            "tiles": [],
        }
    )

    card = run(
        service.save_courtship_card(
            name="Reef dance",
            interaction_ids=["dance", "dance", "display"],
        )
    )

    assert card["interaction_ids"] == ["dance", "dance", "display"]
    assert service.get_game_content_catalog()["courtship_cards"][card["id"]]["image_url"] is None


def test_octopus_token_rules_and_level_node_tokens_are_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")
    monkeypatch.setattr(
        service,
        "get_map",
        lambda _map_id: {
            "id": "reef",
            "name": "Reef",
            "starting_node_id": "N1",
            "nodes": {
                "N1": {"id": "N1", "x": 0.1, "y": 0.1, "tier": 1},
                "N2": {"id": "N2", "x": 0.5, "y": 0.5, "tier": 1},
            },
        },
    )
    service._write_content(
        {
            "categories": [{"id": "threat", "name": "Threat", "compulsory_on_same_node": True}],
            "interactions": [{"id": "charge", "name": "Charge", "image_filename": None}],
            "events": [],
            "tiles": [],
            "player_boards": [],
            "levels": [],
        }
    )

    octopus = run(
        service.update_token(
            token_id="octopus",
            image=None,
            priority=9,
            interaction_ids=["charge"],
            counter_attack_interaction_ids=[],
            success_effects=[{"type": "gain_neurons", "amount": 1}],
            counter_attack_effects=[],
            failure_effects=[{"type": "lose_energy", "amount": 1}],
        )
    )
    level = service.save_level(
        name="Octopus night",
        map_id="reef",
        node_tile_counts={"N1": 0, "N2": 0},
        node_group_ids={"N1": "main", "N2": "main"},
        groups=[{"id": "main", "name": "Main", "tile_counts": {}}],
        poulpita_starting_node_id="N2",
        node_tokens={"N1": [{"type": "shelter"}], "N2": [{"type": "octopus"}]},
    )

    assert octopus["priority"] == 9
    assert octopus["interaction_ids"] == ["charge"]
    assert level["poulpita_starting_node_id"] == "N2"
    assert level["node_tokens"] == {"N1": [{"type": "shelter"}], "N2": [{"type": "octopus"}]}


def test_categories_can_be_compulsory_and_tiles_have_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")

    category = service.create_category(name="Threat", compulsory_on_same_node=True)
    service._write_content(
        {
            "categories": [category],
            "interactions": [{"id": "hide", "name": "Hide", "image_filename": "hide.png"}],
            "events": [{"id": "shark", "name": "Shark", "category_id": category["id"], "image_filename": "shark.png"}],
            "tiles": [],
        }
    )

    tile = service.save_tile(
        name="Shark",
        event_id="shark",
        priority=7,
        interaction_ids=["hide"],
    )
    catalog = service.get_game_content_catalog()

    assert catalog["categories"][category["id"]]["compulsory_on_same_node"] is True
    assert tile["priority"] == 7
    assert catalog["tiles"][tile["id"]]["priority"] == 7


def test_tile_can_have_no_required_interactions(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")
    service._write_content(
        {
            "categories": [{"id": "prey", "name": "Prey"}],
            "interactions": [],
            "events": [{"id": "shell", "name": "Shell", "category_id": "prey", "image_filename": None}],
            "tiles": [],
            "levels": [],
            "player_boards": [],
        }
    )

    tile = service.save_tile(
        name="Free shell",
        event_id="shell",
        interaction_ids=[],
        success_effects=[{"type": "gain_neurons", "amount": 1}],
    )

    assert tile["interaction_ids"] == []


def test_surprise_card_can_be_created_without_image(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONTENT_ROOT", tmp_path)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", tmp_path / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", tmp_path / "content.json")
    service._write_content(
        {
            "categories": [{"id": "prey", "name": "Prey"}],
            "interactions": [{"id": "charge", "name": "Charge", "image_filename": None}],
            "events": [],
            "tiles": [],
            "levels": [],
            "surprise_cards": [],
            "surprise_decks": [],
            "player_boards": [],
        }
    )

    card = run(
        service.save_surprise_card(
            name="No image surprise",
            costs=[{"type": "play_cards", "interaction_ids": ["charge"]}],
            effects=[{"type": "gain_neurons", "amount": 1}],
            image=None,
        )
    )

    assert card["image_filename"] is None
    assert card["image_url"] is None
    assert service.get_content_state()["surprise_cards"][0]["name"] == "No image surprise"


def test_admin_content_package_exports_without_images_and_imports_by_id(tmp_path, monkeypatch):
    content_root = tmp_path / "content"
    maps_root = tmp_path / "maps"
    monkeypatch.setattr(service, "CONTENT_ROOT", content_root)
    monkeypatch.setattr(service, "CONTENT_IMAGES_ROOT", content_root / "images")
    monkeypatch.setattr(service, "CONTENT_JSON_PATH", content_root / "content.json")
    monkeypatch.setattr(map_service, "MAPS_ROOT", maps_root)
    monkeypatch.setattr(service, "get_map", lambda map_id: map_service.get_map(map_id))

    map_service.save_map_data(
        map_id="reef",
        name="Old reef",
        nodes={"N1": {"x": 0.1, "y": 0.2, "tier": 1}},
        adjacency={"N1": []},
        image_filename="board.png",
        image_width=1200,
        image_height=800,
        starting_node_id="N1",
    )
    service._write_content(
        {
            "categories": [{"id": "prey", "name": "Prey", "image_filename": "ignored.png"}],
            "interactions": [{"id": "charge", "name": "Charge", "image_filename": "charge.png"}],
            "events": [{"id": "crab", "name": "Crab", "category_id": "prey", "image_filename": "crab.png"}],
            "tiles": [{"id": "crab-tile", "name": "Crab tile", "event_id": "crab", "interaction_ids": ["charge"]}],
            "levels": [{"id": "night-1", "name": "Night 1", "map_id": "reef", "node_tile_counts": {"N1": 0}, "node_group_ids": {"N1": "main"}, "groups": [{"id": "main", "name": "Main", "tile_counts": {}}], "surprise_deck_id": "surprise-deck"}],
            "surprise_cards": [{"id": "surprise-card", "name": "Spark", "image_filename": "spark.png", "costs": [], "effects": [{"type": "gain_neurons", "amount": 1}]}],
            "surprise_decks": [{"id": "surprise-deck", "name": "Surprises", "card_ids": ["surprise-card"]}],
            "player_boards": [{"id": "agility", "name": "Agility", "initiates_event_ids": ["crab"], "deck": [{"interaction_id": "charge", "count": 2}], "default_max_cards_in_hand": 3, "hand_size_upgrades": [], "actions_per_control": 3, "control_takes_per_night": 3}],
        }
    )

    exported = service.export_admin_content_package(maps=map_service.export_maps_data())

    assert exported["maps"][0]["image_filename"] is None
    assert "image_url" not in exported["maps"][0]
    assert exported["content"]["interactions"][0]["image_filename"] is None
    assert exported["content"]["events"][0]["image_filename"] is None
    assert exported["content"]["surprise_cards"][0]["image_filename"] is None
    assert exported["content"]["surprise_decks"][0]["id"] == "surprise-deck"
    assert exported["content"]["levels"][0]["surprise_deck_id"] == "surprise-deck"
    assert exported["content"]["player_boards"][0]["id"] == "agility"

    imported = {
        "maps": [
            {
                "id": "reef",
                "name": "Imported reef",
                "nodes": {"N1": {"x": 0.3, "y": 0.4, "tier": 1}},
                "adjacency": {"N1": []},
                "starting_node_id": "N1",
                "image_filename": "must-not-import.png",
                "image_width": 640,
                "image_height": 480,
            },
            {
                "id": "lagoon",
                "name": "Lagoon",
                "nodes": {"A": {"x": 0.5, "y": 0.5, "tier": 1}},
                "adjacency": {"A": []},
                "starting_node_id": "A",
            },
        ],
        "content": {
            "categories": [{"id": "prey", "name": "Updated prey"}, {"id": "threat", "name": "Threat"}],
            "interactions": [{"id": "charge", "name": "Updated charge", "image_filename": "must-not-import.png"}],
            "events": [{"id": "crab", "name": "Updated crab", "category_id": "prey", "image_filename": "must-not-import.png"}],
            "tiles": [{"id": "crab-tile", "name": "Updated tile", "event_id": "crab", "interaction_ids": ["charge"]}],
            "surprise_cards": [
                {"id": "surprise-card", "name": "Updated spark", "image_filename": "must-not-import.png", "costs": [], "effects": [{"type": "gain_neurons", "amount": 2}]},
                {"id": "surprise-card-2", "name": "Second spark", "image_filename": "must-not-import.png", "costs": [], "effects": []},
            ],
            "surprise_decks": [{"id": "surprise-deck", "name": "Updated surprises", "card_ids": ["surprise-card", "surprise-card-2"]}],
            "levels": [{"id": "night-1", "name": "Updated night", "map_id": "reef", "node_tile_counts": {"N1": 0}, "node_group_ids": {"N1": "main"}, "groups": [{"id": "main", "name": "Main", "tile_counts": {}}], "surprise_deck_id": "surprise-deck"}],
            "player_boards": [{"id": "agility", "name": "Quickness", "initiates_event_ids": ["crab"], "deck": [{"interaction_id": "charge", "count": 4}], "default_max_cards_in_hand": 4, "hand_size_upgrades": [], "actions_per_control": 2, "control_takes_per_night": 5}],
        },
    }

    map_summary = map_service.import_maps_data(imported["maps"])
    content_summary = service.import_admin_content_package(imported)
    state = service.get_content_state()
    reef = map_service.get_map("reef")

    assert map_summary == {"created": 1, "updated": 1}
    assert content_summary["created"]["categories"] == 1
    assert content_summary["updated"]["categories"] == 1
    assert content_summary["created"]["surprise_cards"] == 1
    assert content_summary["updated"]["surprise_cards"] == 1
    assert content_summary["updated"]["surprise_decks"] == 1
    assert content_summary["updated"]["levels"] == 1
    assert content_summary["updated"]["player_boards"] == 1
    assert reef["name"] == "Imported reef"
    assert reef["image_filename"] is None
    assert reef["image_url"] is None
    assert map_service.get_map("lagoon")["name"] == "Lagoon"
    assert {category["id"]: category["name"] for category in state["categories"]}["prey"] == "Updated prey"
    assert state["interactions"][0]["image_filename"] is None
    assert state["events"][0]["image_filename"] is None
    assert {card["id"]: card for card in state["surprise_cards"]}["surprise-card"]["name"] == "Updated spark"
    assert {card["id"]: card for card in state["surprise_cards"]}["surprise-card"]["image_filename"] is None
    assert {deck["id"]: deck for deck in state["surprise_decks"]}["surprise-deck"]["card_ids"] == ["surprise-card", "surprise-card-2"]
    assert {level["id"]: level for level in state["levels"]}["night-1"]["name"] == "Updated night"
    assert {board["id"]: board for board in state["player_boards"]}["agility"]["name"] == "Quickness"
