import aiosqlite
import os

DB_PATH = os.path.join("data", "lounge.db")

async def init_db():
    """Создаёт таблицы, если их нет."""
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                games_played INTEGER DEFAULT 0,
                games_won INTEGER DEFAULT 0,
                chips INTEGER DEFAULT 0,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                channel_id INTEGER,
                host_id INTEGER,
                players TEXT,
                winner_id INTEGER,
                duration_sec INTEGER,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            )
        """)
        await db.commit()

async def get_db():
    """Возвращает соединение с БД."""
    return await aiosqlite.connect(DB_PATH)

async def get_player(guild_id: int, user_id: int):
    """Получить игрока или None."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT username, games_played, games_won, chips FROM players "
            "WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            return await cursor.fetchone()
    finally:
        await db.close()

async def ensure_player(guild_id: int, user_id: int, username: str):
    """Создать запись игрока, если её нет."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO players (guild_id, user_id, username) "
            "VALUES (?, ?, ?)",
            (guild_id, user_id, username),
        )
        await db.execute(
            "UPDATE players SET username = ? WHERE guild_id = ? AND user_id = ?",
            (username, guild_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()

async def add_game_result(
    guild_id: int,
    user_id: int,
    won: bool,
    chips_delta: int,
):
    """Обновить статистику игрока после партии."""
    db = await get_db()
    try:
        won_inc = 1 if won else 0
        await db.execute(
            """
            UPDATE players
            SET games_played = games_played + 1,
                games_won = games_won + ?,
                chips = chips + ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (won_inc, chips_delta, guild_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()

async def save_game(
    guild_id: int,
    game_type: str,
    channel_id: int,
    host_id: int,
    players_json: str,
    winner_id: int | None,
    duration_sec: int,
):
    """Записать завершённую партию в историю."""
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO games
                (guild_id, game_type, channel_id, host_id, players,
                 winner_id, duration_sec, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (guild_id, game_type, channel_id, host_id, players_json,
             winner_id, duration_sec),
        )
        await db.commit()
    finally:
        await db.close()

async def get_top_players(guild_id: int, limit: int = 10):
    """Топ игроков по фишкам."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT user_id, username, chips, games_played, games_won "
            "FROM players WHERE guild_id = ? "
            "ORDER BY chips DESC LIMIT ?",
            (guild_id, limit),
        ) as cursor:
            return await cursor.fetchall()
    finally:
        await db.close()