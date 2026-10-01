from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class Player:
    user_id: int
    username: str
    games_played: int = 0
    games_won: int = 0
    chips: int = 0


@dataclass
class Game:
    game_type: str
    guild_id: int
    channel_id: int
    host_id: int
    players: List[int] = field(default_factory=list)
    state: str = "lobby"
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    message_id: Optional[int] = None

    def add_player(self, user_id: int) -> bool:
        if user_id in self.players:
            return False
        self.players.append(user_id)
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id not in self.players:
            return False
        self.players.remove(user_id)
        return True

    def refresh_timer(self, seconds: int = 900) -> None:
        """Продлевает таймер лобби на N секунд."""
        self.expires_at = time.time() + seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at