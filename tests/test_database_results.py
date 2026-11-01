import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db


class ResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'lounge.db')
        self.binding = patch.object(db, 'DB_PATH', self.path)
        self.binding.start()
        await db.init_db()
        await db.ensure_player(1, 10, 'winner')
        await db.ensure_player(1, 20, 'other')
        self.result = dict(game_id='unique-game', guild_id=1, game_type='mafia_lite',
                           channel_id=2, host_id=10, players_json=json.dumps([10, 20]),
                           winner_id=10, duration_sec=60,
                           rewards=[(10, True, 15), (20, False, 3)])

    async def asyncTearDown(self):
        self.binding.stop()
        self.temp.cleanup()

    def count_games(self):
        with sqlite3.connect(self.path) as connection:
            return connection.execute('SELECT count(*) FROM games').fetchone()[0]

    async def test_history_and_awards_commit_together(self):
        self.assertTrue(await db.record_game_result(**self.result))
        self.assertEqual(self.count_games(), 1)
        self.assertEqual(await db.get_player(1, 10), ('winner', 1, 1, 15))
        self.assertEqual(await db.get_player(1, 20), ('other', 1, 0, 3))

    async def test_repeated_and_concurrent_requests_award_once(self):
        outcomes = await asyncio.gather(*(db.record_game_result(**self.result) for _ in range(4)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertFalse(await db.record_game_result(**self.result))
        self.assertEqual(self.count_games(), 1)
        self.assertEqual((await db.get_player(1, 10))[1:], (1, 1, 15))
        self.assertEqual((await db.get_player(1, 20))[1:], (1, 0, 3))

    async def test_mid_award_failure_rolls_back_history_and_first_award(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TRIGGER fail_award BEFORE UPDATE ON players
                WHEN NEW.user_id = 20 AND NEW.games_played > OLD.games_played
                BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await db.record_game_result(**self.result)
        self.assertEqual(self.count_games(), 0)
        self.assertEqual((await db.get_player(1, 10))[1:], (0, 0, 0))
        self.assertEqual((await db.get_player(1, 20))[1:], (0, 0, 0))
        with sqlite3.connect(self.path) as connection:
            connection.execute('DROP TRIGGER fail_award')
        self.assertTrue(await db.record_game_result(**self.result))
        self.assertEqual((await db.get_player(1, 10))[1:], (1, 1, 15))

    async def test_missing_recipient_rolls_back_everything(self):
        self.result['rewards'].append((30, False, 3))
        with self.assertRaises(ValueError):
            await db.record_game_result(**self.result)
        self.assertEqual(self.count_games(), 0)
        self.assertEqual((await db.get_player(1, 10))[1:], (0, 0, 0))

    async def test_server_statistics_remain_separate(self):
        await db.ensure_player(2, 10, 'other-server')
        await db.record_game_result(**self.result)
        self.assertEqual((await db.get_player(2, 10))[1:], (0, 0, 0))

    async def test_legacy_database_migrates_without_losing_history(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute('DROP TABLE games')
            connection.execute('''CREATE TABLE games (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
                game_type TEXT NOT NULL, channel_id INTEGER, host_id INTEGER,
                players TEXT, winner_id INTEGER, duration_sec INTEGER,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP)''')
            connection.execute("INSERT INTO games (guild_id, game_type) VALUES (1, 'old')")
            connection.execute("INSERT INTO games (guild_id, game_type) VALUES (1, 'old')")
        await db.init_db()
        await db.init_db()
        self.assertTrue(await db.record_game_result(**self.result))
        self.assertEqual(self.count_games(), 3)

    async def test_cancellation_rolls_back_in_progress_transaction(self):
        connection = await db.get_db()
        execute = connection.execute
        async def cancel_before_award(sql, *args, **kwargs):
            if sql.startswith('UPDATE players'):
                raise asyncio.CancelledError()
            return await execute(sql, *args, **kwargs)
        with patch.object(connection, 'execute', side_effect=cancel_before_award), \
             patch.object(db, 'get_db', return_value=connection):
            with self.assertRaises(asyncio.CancelledError):
                await db.record_game_result(**self.result)
        self.assertEqual(self.count_games(), 0)
        self.assertEqual((await db.get_player(1, 10))[1:], (0, 0, 0))
