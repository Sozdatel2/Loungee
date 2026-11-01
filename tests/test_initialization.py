import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main
from test_mafia import interaction, game
from cogs.mafia import DayView, Mafia


class InitializationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(extensions={}, sync_application_commands=AsyncMock(),
                                   close=AsyncMock(), change_presence=AsyncMock(),
                                   user=SimpleNamespace(id=1), guilds=[])
        def load(extension):
            self.bot.extensions[extension] = object()
        self.bot.load_extension = Mock(side_effect=load)
        for binding in (patch.object(main, 'bot', self.bot),
                        patch.object(main, '_initialized', False),
                        patch.object(main, '_initialization_lock', asyncio.Lock()),
                        patch.object(main, 'init_db', new=AsyncMock())):
            binding.start()
            self.addCleanup(binding.stop)

    async def test_concurrent_initialization_and_reconnect_do_not_duplicate_setup(self):
        await asyncio.gather(main.initialize_bot(), main.initialize_bot())
        await main.initialize_bot()
        self.assertTrue(main._initialized)
        main.init_db.assert_awaited_once()
        self.assertEqual(self.bot.load_extension.call_count, 4)
        self.bot.sync_application_commands.assert_awaited_once()

    async def test_database_failure_closes_bot_before_loading_commands(self):
        main.init_db.side_effect = RuntimeError('db')
        with self.assertLogs('Lounge', level='ERROR'):
            await main.on_ready()
        self.assertFalse(main._initialized)
        self.bot.close.assert_awaited_once()
        self.bot.load_extension.assert_not_called()
        self.bot.change_presence.assert_not_awaited()

    async def test_extension_failure_does_not_mark_ready_and_can_retry(self):
        original = self.bot.load_extension.side_effect
        def fail(extension):
            if extension == 'cogs.games':
                raise RuntimeError('extension')
            original(extension)
        self.bot.load_extension.side_effect = fail
        with self.assertRaises(RuntimeError):
            await main.initialize_bot()
        self.assertFalse(main._initialized)
        self.bot.sync_application_commands.assert_not_awaited()
        self.bot.load_extension.side_effect = original
        await main.initialize_bot()
        self.assertTrue(main._initialized)
        self.assertEqual(set(self.bot.extensions), {'cogs.lobby', 'cogs.games', 'cogs.mafia', 'cogs.developer'})
        self.assertEqual(self.bot.load_extension.call_args_list.count((('cogs.lobby',),)), 1)

    async def test_sync_failure_closes_bot_and_never_marks_ready(self):
        self.bot.sync_application_commands.side_effect = RuntimeError('sync')
        with self.assertLogs('Lounge', level='ERROR'):
            await main.on_ready()
        self.assertFalse(main._initialized)
        self.bot.close.assert_awaited_once()

    async def test_commands_blocked_until_initialization_completes(self):
        i = interaction(1)
        self.assertFalse(await main.require_initialization(i))
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])
        await main.initialize_bot()
        self.assertTrue(await main.require_initialization(interaction(1)))

    async def test_skip_discussion_announcement_is_public(self):
        g = game()
        g.phase = 'day'
        g.channel = object()
        g.cog = Mafia(None)
        g.cog.games[g.channel_id] = g
        view = DayView(g)
        i = interaction(1, g.game_id)
        with patch.object(g.cog, 'start_vote', new=AsyncMock()):
            await view.to_vote.callback(i)
            await asyncio.sleep(0)
        i.response.send_message.assert_awaited_once_with(
            '⏩ Ведущий ускорил обсуждение.', ephemeral=False)
