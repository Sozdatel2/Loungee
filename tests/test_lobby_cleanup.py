import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.games import Games
from database.manager import game_manager
from test_mafia import interaction
from test_stability import http_error


class LobbyCleanupTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        for lobby in game_manager.list_active():
            game_manager.remove(lobby.channel_id)

    def command(self):
        return SimpleNamespace(bot=SimpleNamespace(get_cog=lambda name: None))

    def request(self):
        i = interaction(1)
        i.channel_id = 2
        i.guild = SimpleNamespace(name='test')
        i.user.mention = '<@1>'
        i.original_message = AsyncMock(return_value=SimpleNamespace(id=123))
        i.delete_original_message = AsyncMock()
        return i

    async def test_failed_lobby_send_releases_channel(self):
        i = self.request()
        i.response.send_message.side_effect = http_error()
        i.delete_original_message.side_effect = http_error()
        with self.assertLogs('cogs.games', level='ERROR'):
            with self.assertRaises(type(http_error())):
                await Games.game_start.callback(self.command(), i, 'mafia_lite')
        self.assertFalse(game_manager.has_active(2))

    async def test_original_message_lookup_failure_releases_channel(self):
        i = self.request()
        i.original_message.side_effect = http_error()
        with self.assertLogs('cogs.games', level='ERROR'):
            with self.assertRaises(type(http_error())):
                await Games.game_start.callback(self.command(), i, 'mafia_lite')
        self.assertFalse(game_manager.has_active(2))
        i.delete_original_message.assert_awaited_once()

    async def test_direct_message_lobby_rejected(self):
        i = self.request()
        i.guild_id = None
        await Games.game_start.callback(self.command(), i, 'mafia_lite')
        self.assertFalse(game_manager.has_active(2))
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])

    async def test_cancel_command_removes_original_controls(self):
        lobby = game_manager.create('mafia_lite', 1, 2, 1)
        lobby.message_id = 123
        i = self.request()
        message = SimpleNamespace(edit=AsyncMock())
        i.channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        await Games.game_cancel.callback(self.command(), i)
        self.assertFalse(game_manager.has_active(2))
        i.channel.fetch_message.assert_awaited_once_with(123)
        message.edit.assert_awaited_once_with(view=None)

    async def test_watcher_does_not_remove_replacement_or_refreshed_lobby(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                first = game_manager.create('mafia_lite', 1, 10, 1)
                second = game_manager.create('mafia_lite', 1, 20, 1)
                first.expires_at = second.expires_at = time.time() - 5
                async def update_during_send(**kwargs):
                    if replacement:
                        game_manager.create('mafia_lite', 1, 20, 1)
                    else:
                        second.refresh_timer()
                ch = SimpleNamespace(guild=SimpleNamespace(name='test'),
                                     send=AsyncMock(side_effect=update_during_send))
                cog = SimpleNamespace(bot=SimpleNamespace(get_channel=lambda cid: ch))
                await Games._lobby_watcher.coro(cog)
                self.assertTrue(game_manager.has_active(20))
                self.assertEqual(ch.send.await_count, 1)
                game_manager.remove(20)
