import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nextcord
from cogs.games import Games, LobbyView
from cogs.mafia import Mafia, DayView, NightActionView, VoteView
from database.manager import game_manager
from test_mafia import game, interaction


def http_error():
    return nextcord.HTTPException(SimpleNamespace(status=500, reason='Server error'), 'test failure')


def channel():
    return SimpleNamespace(guild=SimpleNamespace(name='test', get_member=lambda uid: None),
                           send=AsyncMock())


class StabilityTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        for lobby in game_manager.list_active():
            game_manager.remove(lobby.channel_id)

    def lobby(self):
        lobby = game_manager.create('mafia_lite', 1, 2, 1)
        lobby.players = [1, 2, 3, 4]
        return lobby, LobbyView(2, 1)

    def click(self, view, action, uid=1):
        i = interaction(uid, view.game_id)
        i.data['custom_id'] = f'lobby:{view.game_id}:{action}'
        i.channel_id = 2
        return i

    async def test_ids_are_unique_and_present_in_all_views(self):
        g = game()
        other = game()
        self.assertNotEqual(g.game_id, other.game_id)
        self.assertEqual(len(g.game_id), 32)
        _, lobby = self.lobby()
        for view, expected in [(lobby, lobby.game_id), (DayView(g), g.game_id),
                               (VoteView(g), g.game_id), (NightActionView(g, 3, 'heal'), g.game_id)]:
            ids = [b.custom_id for b in view.children]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(cid.split(':')[1] == expected for cid in ids))
            self.assertTrue(all(len(cid) <= 100 for cid in ids))

    async def test_old_lobby_buttons_cannot_touch_replacement(self):
        old, view = self.lobby()
        game_manager.remove(2)
        new = game_manager.create('mafia_lite', 1, 2, 1)
        for action in ('join', 'leave', 'start', 'cancel'):
            i = self.click(view, action)
            await getattr(view, action).callback(i)
            i.response.send_message.assert_awaited_once_with(
                'Это кнопки от старой игры, сэр', ephemeral=True)
            self.assertIs(game_manager.get(2), new)
            self.assertEqual(new.players, [1])
            self.assertEqual(new.state, 'lobby')

    async def test_forged_game_id_rejected_by_all_mafia_buttons(self):
        g = game()
        callbacks = [NightActionView(g, 1, 'kill')._make_callback(5),
                     DayView(g).to_vote.callback, VoteView(g)._make_vote_callback(5),
                     VoteView(g)._abstain_callback]
        for callback in callbacks:
            i = interaction(1, 'old-game')
            await callback(i)
            i.response.send_message.assert_awaited_once_with(
                'Это кнопки от старой игры, сэр', ephemeral=True)
        self.assertEqual(g.mafia_votes, {})
        self.assertEqual(g.votes, {})

    async def test_lobby_double_click_reserves_channel_until_start_finishes(self):
        lobby, view = self.lobby()
        entered, release = asyncio.Event(), asyncio.Event()
        async def launch(*args, **kwargs):
            self.assertIs(game_manager.get(2), lobby)
            entered.set()
            await release.wait()
        mafia = SimpleNamespace(start_game=AsyncMock(side_effect=launch), cancel_game=lambda cid: None,
                                has_active_game=lambda cid: False)
        view._bot = SimpleNamespace(get_cog=lambda name: mafia)
        first = self.click(view, 'start')
        task = asyncio.create_task(view.start.callback(first))
        await entered.wait()
        try:
            self.assertEqual(lobby.state, 'starting')
            second = self.click(view, 'start')
            await view.start.callback(second)
            second.response.send_message.assert_awaited_once_with(
                'Игра уже запускается или идёт', ephemeral=True)
            for action in ('join', 'leave', 'cancel'):
                i = self.click(view, action)
                await getattr(view, action).callback(i)
                self.assertEqual(i.response.send_message.call_args.args[0],
                                 'Игра уже запускается или идёт')
            new_lobby = interaction(1)
            new_lobby.channel_id = 2
            await Games.game_start.callback(SimpleNamespace(bot=view._bot), new_lobby, 'mafia_lite')
            self.assertIs(game_manager.get(2), lobby)
            mafia.start_game.assert_awaited_once()
        finally:
            release.set()
            await task
        self.assertFalse(game_manager.has_active(2))
        first.message.edit.assert_awaited_once_with(view=None)

    async def test_lobby_buttons_removed_even_when_launch_fails(self):
        lobby, view = self.lobby()
        mafia = SimpleNamespace(start_game=AsyncMock(side_effect=RuntimeError('test')),
                                cancel_game=lambda cid: None)
        view._bot = SimpleNamespace(get_cog=lambda name: mafia)
        i = self.click(view, 'start')
        with self.assertLogs('cogs.games', level='ERROR'):
            with self.assertRaises(RuntimeError):
                await view.start.callback(i)
        self.assertFalse(game_manager.has_active(2))
        i.message.edit.assert_awaited_once_with(view=None)

    async def test_all_phase_channel_failures_clean_up_without_propagation(self):
        cases = [('start_night', 'setup', {}), ('start_day', 'resolving', {}),
                 ('start_vote', 'day', {}), ('resolve_night', 'night', {}),
                 ('resolve_vote', 'vote', {}),
                 ('resolve_vote', 'vote', {1: 5, 2: 6}),
                 ('resolve_vote', 'vote', {1: 5, 2: 5})]
        for method, phase, votes in cases:
            with self.subTest(method=method, votes=votes):
                g = game()
                g.phase = phase
                g.votes = votes
                g.channel = channel()
                g.channel.send.side_effect = http_error()
                cog = Mafia(None)
                cog.games[2] = g
                g.cog = cog
                timers = [asyncio.create_task(asyncio.sleep(1000)) for _ in range(3)]
                g._night_tasks.append(timers[0])
                g._day_tasks.append(timers[1])
                g._vote_tasks.append(timers[2])
                with self.assertLogs('cogs.mafia', level='ERROR'):
                    await getattr(cog, method)(g)
                await asyncio.sleep(0)
                self.assertFalse(cog.has_active_game(2))
                self.assertEqual(g.phase, 'cancelled')
                self.assertEqual(g.channel.send.await_count, 2)
                self.assertTrue(all(timer.cancelled() for timer in timers))
                await asyncio.gather(*timers, return_exceptions=True)

    async def test_abort_from_current_timer_finishes_notification(self):
        g = game()
        g.channel = channel()
        g.channel.send.side_effect = [http_error(), None]
        cog = Mafia(None)
        cog.games[2] = g
        async def timer():
            g._night_tasks.append(asyncio.current_task())
            await cog.resolve_night(g)
        with self.assertLogs('cogs.mafia', level='ERROR'):
            await asyncio.create_task(timer())
        self.assertEqual(g.channel.send.await_count, 2)
        self.assertFalse(cog.has_active_game(2))

    async def test_database_failures_do_not_prevent_game_completion(self):
        g = game()
        g.channel = channel()
        cog = Mafia(None)
        cog.games[2] = g
        with patch('cogs.mafia.record_game_result', new=AsyncMock(side_effect=RuntimeError('db'))):
            with self.assertLogs('cogs.mafia', level='ERROR'):
                await cog.end_game(g, 'mafia')
        self.assertEqual(g.phase, 'ended')
        self.assertFalse(cog.has_active_game(2))
        embed = g.channel.send.call_args.kwargs['embed']
        self.assertIn('Ошибка сохранения', embed.fields[1].value)

    async def test_setup_database_failure_releases_game(self):
        g = game()
        i = interaction(1)
        i.channel_id, i.guild_id, i.channel = 2, 1, channel()
        i.guild = SimpleNamespace(get_member=lambda uid: None)
        cog = Mafia(None)
        with patch('cogs.mafia.ensure_player', new=AsyncMock(side_effect=RuntimeError('db'))):
            with self.assertLogs('cogs.mafia', level='ERROR'):
                await cog.start_game(i, 'lite', [1, 2, 3, 4])
        self.assertFalse(cog.has_active_game(2))
