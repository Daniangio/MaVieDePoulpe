from backend.app import game_content_service as service


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
                    "failure_effects": [{"type": "half_ap", "amount": None}],
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
    assert service.get_content_state()["tiles"][0]["failure_effects"] == [{"type": "half_ap", "amount": None}]
