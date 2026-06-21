from __future__ import annotations

from typing import Optional


_presence_service = None
_connection_manager = None
_game_room_service = None


def set_presence_service(service) -> None:
    global _presence_service
    _presence_service = service


def get_presence_service():
    return _presence_service


def set_connection_manager(manager) -> None:
    global _connection_manager
    _connection_manager = manager


def get_connection_manager():
    return _connection_manager


def set_game_room_service(service) -> None:
    global _game_room_service
    _game_room_service = service


def get_game_room_service():
    return _game_room_service

