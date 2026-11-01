import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.mafia import Mafia, MafiaGame, NightActionView, VoteView, DayView
from cogs.lobby import Lobby


def game():
    g = MafiaGame('full', 1, 2, 1, list(range(1, 8)))
    g.roles = {1: 'mafia', 2: 'mafia', 3: 'doctor', 4: 'cop',
               5: 'civilian', 6: 'civilian', 7: 'civilian'}
    g.day = 1
    g.phase = 'night'
    return g


def interaction(uid):
    return SimpleNamespace(user=SimpleNamespace(id=uid),
                           response=SimpleNamespace(send_message=AsyncMock()),
                           message=SimpleNamespace(edit=AsyncMock()))


class MafiaTests(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_self_heal_not_consecutive(self):
        g = game()
        self.assertIn(3, [int(button.custom_id.split(':')[1])
                          for button in NightActionView(g, 3, 'heal').children])
        self.assertTrue(g.register_action('heal', 3, 3))
        g.day = 2
        g.doctor_target = None
        self.assertNotIn(3, g.action_targets('heal', 3))
        self.assertFalse(g.register_action('heal', 3, 3))
        self.assertTrue(g.register_action('heal', 3, 5))
        g.day = 3
        g.doctor_target = None
        self.assertTrue(g.register_action('heal', 3, 3))

    async def test_dead_mafia_does_not_block_night(self):
        g = game()
        g.kill(2, 'test')
        self.assertEqual(g.expected_night_actions(), 3)
        self.assertTrue(g.register_action('kill', 1, 5))
        self.assertTrue(g.register_action('heal', 3, 5))
        self.assertTrue(g.register_action('check', 4, 1))
        g.maybe_finish_night()
        self.assertTrue(g._night_finished)

    async def test_invalid_actions_do_not_mutate_state(self):
        g = game()
        for action, actor, target in [('kill', 5, 6), ('heal', 1, 6),
                                       ('check', 4, 99), ('kill', 1, 1)]:
            self.assertFalse(g.register_action(action, actor, target))
        g.kill(1, 'test')
        self.assertFalse(g.register_action('kill', 1, 5))
        self.assertEqual(g.mafia_votes, {})
        self.assertEqual(g.cop_checks, {})
        self.assertIsNone(g.doctor_target)

    async def test_old_night_button_rejected_in_next_round(self):
        g = game()
        view = NightActionView(g, 1, 'kill')
        g.day = 2
        await view._make_callback(5)(interaction(1))
        self.assertEqual(g.mafia_votes, {})

    async def test_night_button_rejected_after_completion(self):
        g = game()
        view = NightActionView(g, 1, 'kill')
        g._night_finished = True
        await view._make_callback(5)(interaction(1))
        self.assertEqual(g.mafia_votes, {})

    async def test_old_vote_and_abstention_rejected(self):
        g = game()
        g.phase = 'vote'
        view = VoteView(g)
        g.day = 2
        await view._make_vote_callback(5)(interaction(1))
        await view._abstain_callback(interaction(2))
        self.assertEqual(g.votes, {})

    async def test_dead_target_and_duplicate_vote_rejected(self):
        g = game()
        g.phase = 'vote'
        view = VoteView(g)
        g.kill(5, 'test')
        await view._make_vote_callback(5)(interaction(1))
        self.assertEqual(g.votes, {})
        await view._make_vote_callback(6)(interaction(1))
        await view._abstain_callback(interaction(1))
        self.assertEqual(g.votes, {1: 6})

    async def test_removed_game_rejects_buttons(self):
        g = game()
        g.cog = Mafia(None)
        view = NightActionView(g, 1, 'kill')
        await view._make_callback(5)(interaction(1))
        self.assertEqual(g.mafia_votes, {})

    async def test_vote_transition_only_once(self):
        g = game()
        cog = Mafia(None)
        cog.games[g.channel_id] = g
        g.cog = cog
        g.phase = 'day'
        g.channel = SimpleNamespace(guild=SimpleNamespace(name='test', get_member=lambda uid: None), send=AsyncMock())
        with patch('cogs.mafia.VOTE_DURATION', 1000):
            await asyncio.gather(cog.start_vote(g), cog.start_vote(g))
        self.assertEqual(g.channel.send.await_count, 1)
        self.assertEqual(len(g._vote_tasks), 1)
        cog.remove_game(g.channel_id)
        await asyncio.sleep(0)

    async def test_stale_day_button_cannot_skip_new_day(self):
        g = game()
        g.phase = 'day'
        view = DayView(g)
        g.day = 2
        await view.to_vote.callback(interaction(1))
        self.assertFalse(g._day_finished)

    async def test_active_includes_mafia(self):
        g = game()
        cog = Mafia(None)
        cog.games[g.channel_id] = g
        lobby = Lobby(SimpleNamespace(get_cog=lambda name: cog))
        i = interaction(1)
        i.guild_id = 1
        i.guild = SimpleNamespace(name='test')
        await Lobby.active.callback(lobby, i)
        embed = i.response.send_message.call_args.kwargs['embed']
        self.assertIn('mafia_full', embed.description)
        self.assertIn('night', embed.description)

    async def test_failed_role_delivery_cancels_start(self):
        import nextcord
        member = SimpleNamespace(display_name='test', send=AsyncMock())
        member.send.side_effect = nextcord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'closed DMs')
        i = interaction(1)
        i.channel_id = 2
        i.guild_id = 1
        i.guild = SimpleNamespace(get_member=lambda uid: member)
        i.channel = SimpleNamespace(send=AsyncMock())
        cog = Mafia(None)
        with patch('cogs.mafia.ensure_player', new=AsyncMock()):
            await cog.start_game(i, 'lite', [1, 2, 3, 4])
        self.assertFalse(cog.has_active_game(2))
        self.assertIn('Партия отменена', i.channel.send.call_args.args[0])

    async def test_night_resolution_only_once(self):
        g = game()
        cog = Mafia(None)
        g.cog = cog
        cog.games[2] = g
        g.channel = SimpleNamespace(guild=SimpleNamespace(name='test', get_member=lambda uid: None), send=AsyncMock())
        g.mafia_votes = {1: 5, 2: 5}
        with patch.object(cog, 'start_day', new=AsyncMock()) as start_day:
            await asyncio.gather(cog.resolve_night(g), cog.resolve_night(g))
        self.assertEqual(g.dead_log, [(5, 'убит ночью 1')])
        start_day.assert_awaited_once()

    async def test_vote_resolution_only_once(self):
        g = game()
        cog = Mafia(None)
        g.cog = cog
        cog.games[2] = g
        g.phase = 'vote'
        g.channel = SimpleNamespace(guild=SimpleNamespace(name='test', get_member=lambda uid: None),
                                    send=AsyncMock())
        g.votes = {1: 5, 2: 5, 3: 5}
        with patch.object(cog, '_next_night', new=AsyncMock()) as next_night:
            await asyncio.gather(cog.resolve_vote(g), cog.resolve_vote(g))
        self.assertEqual(g.dead_log, [(5, 'казнён днём 1')])
        next_night.assert_awaited_once()

    async def test_day_double_click_only_schedules_one_vote(self):
        g = game()
        g.phase = 'day'
        cog = Mafia(None)
        g.cog = cog
        cog.games[2] = g
        g.channel = object()
        view = DayView(g)
        with patch.object(cog, 'start_vote', new=AsyncMock()) as start_vote:
            await asyncio.gather(view.to_vote.callback(interaction(1)),
                                 view.to_vote.callback(interaction(1)))
            await asyncio.sleep(0)
            start_vote.assert_awaited_once()

    async def test_cancel_stops_timers_and_rejects_old_actions(self):
        g = game()
        cog = Mafia(None)
        g.cog = cog
        cog.games[2] = g
        timer = asyncio.create_task(asyncio.sleep(1000))
        g._night_tasks.append(timer)
        self.assertTrue(cog.cancel_game(2))
        await asyncio.sleep(0)
        self.assertTrue(timer.cancelled())
        self.assertEqual(g.phase, 'cancelled')
        self.assertFalse(g.register_action('kill', 1, 5))
        self.assertFalse(cog.cancel_game(2))

    async def test_cancel_command_only_allows_host(self):
        from cogs.games import Games
        g = game()
        cog = Mafia(None)
        g.cog = cog
        cog.games[2] = g
        commands = SimpleNamespace(bot=SimpleNamespace(get_cog=lambda name: cog))
        outsider = interaction(5)
        outsider.channel_id = 2
        await Games.game_cancel.callback(commands, outsider)
        self.assertTrue(cog.has_active_game(2))
        host = interaction(1)
        host.channel_id = 2
        await Games.game_cancel.callback(commands, host)
        self.assertFalse(cog.has_active_game(2))
        self.assertIn('Мафия отменена', host.response.send_message.call_args.kwargs['embed'].description)


if __name__ == '__main__':
    unittest.main()
