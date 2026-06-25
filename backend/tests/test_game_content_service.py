import asyncio

from backend.app import game_content_service as service


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
    )
    state = service.get_content_state()

    assert board["deck"] == [{"interaction_id": "charge", "count": 4}]
    assert len(state["player_boards"]) == 5
    assert state["player_boards"][0]["initiates_event_ids"] == ["crab"]
    assert state["player_boards"][0]["actions_per_control"] == 2


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
    )

    assert level["node_tile_counts"] == {"N1": 2, "N2": 1}
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

    assert [token["id"] for token in state["tokens"]] == ["neuron", "seashell", "shelter"]
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
    assert service.get_game_content_catalog()["poulpita_panel"]["zones"]["seashells"]["x"] == 0.5


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
