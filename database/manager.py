from typing import Dict, Optional
from database.models import Game

class GameManager:
    """Хранит активные игры по channel_id. In-memory."""

    def __init__(self):
        self._games: Dict[int, Game] = {}

    def get(self, channel_id: int) -> Optional[Game]:
        return self._games.get(channel_id)

    def create(
        self,
        game_type: str,
        guild_id: int,
        channel_id: int,
        host_id: int,
    ) -> Game:
        game = Game(
            game_type=game_type,
            guild_id=guild_id,
            channel_id=channel_id,
            host_id=host_id,
            players=[host_id],
        )
        self._games[channel_id] = game
        return game

    def remove(self, channel_id: int) -> bool:
        return self._games.pop(channel_id, None) is not None

    def list_active(self, guild_id: Optional[int] = None) -> list[Game]:
        games = list(self._games.values())
        if guild_id is not None:
            games = [g for g in games if g.guild_id == guild_id]
        return games

    def has_active(self, channel_id: int) -> bool:
        return channel_id in self._games

game_manager = GameManager()