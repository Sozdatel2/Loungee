import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import nextcord
from cogs.developer import Developer
from cogs.games import Games
from cogs.lobby import Lobby
from database.manager import game_manager
from test_mafia import game, interaction
from test_stability import http_error


def request(uid=1):
    i = interaction(uid)
    i.channel_id = 2
    i.guild = SimpleNamespace(name='test', id=1)
    i.bot = SimpleNamespace()
    i.command = SimpleNamespace(name="test")
    i.author = i.user
    i.author.send = AsyncMock()
    i.channel = SimpleNamespace(id=2)
    i.send = AsyncMock()
    i.response.defer = AsyncMock()
    i.followup = SimpleNamespace(send=i.author.send)
    return i


class DeveloperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(is_owner=AsyncMock(return_value=True), guilds=[], get_guild=Mock())
        self.cog = Developer(self.bot)

    async def test_non_owner_cannot_list_find_or_get_invites(self):
        self.bot.is_owner.return_value = False
        for command, args in [(Developer.servers, (1,)), (Developer.get_sid, ('test',)),
                              (Developer.get_inv, ('123',))]:
            i = request()
            if command is Developer.get_sid:
                await command.callback(self.cog, i, name=args[0])
            else:
                await command.callback(self.cog, i, *args)
            self.assertIn('только создателю', i.followup.send.call_args.args[0])
            i.send.assert_not_awaited()
        self.bot.get_guild.assert_not_called()

    async def test_owner_lookup_failure_denies_access(self):
        self.bot.is_owner.side_effect = http_error()
        with self.assertLogs('cogs.developer', level='WARNING'):
            await Developer.servers.callback(self.cog, request(), 1)
        self.bot.get_guild.assert_not_called()

    async def test_server_pages_stay_within_embed_limits(self):
        self.bot.guilds = [SimpleNamespace(name='x' * 100, id=n) for n in range(43)]
        i = request()
        await Developer.servers.callback(self.cog, i, 3)
        embed = i.followup.send.call_args.kwargs['embed']
        self.assertIn('3/3', embed.description)
        self.assertEqual(embed.description.count('•'), 3)
        self.assertLess(len(embed), 6000)
        i.send.assert_not_awaited()

    async def test_duplicate_server_names_are_not_silently_selected(self):
        self.bot.guilds = [SimpleNamespace(name='Test', id=123), SimpleNamespace(name='Test', id=456)]
        i = request()
        await Developer.get_sid.callback(self.cog, i, name=' test ')
        text = i.followup.send.call_args.kwargs['embed'].description
        self.assertIn('123', text)
        self.assertIn('456', text)

    async def test_invalid_server_id_does_not_query_discord(self):
        i = request()
        await Developer.get_inv.callback(self.cog, i, 'invalid')
        self.bot.get_guild.assert_not_called()
        self.assertIn('не найден', i.followup.send.call_args.args[0])

    async def test_invite_returns_existing_link_without_creating_one(self):
        guild = SimpleNamespace(features=[], invites=AsyncMock(return_value=[
            SimpleNamespace(expires_at=None, max_uses=1, uses=1, url='exhausted'),
            SimpleNamespace(expires_at=None, max_uses=0, uses=0, url='https://discord.gg/test')]),
            create_invite=AsyncMock())
        self.bot.get_guild.return_value = guild
        i = request()
        await Developer.get_inv.callback(self.cog, i, '123')
        i.followup.send.assert_awaited_once_with('https://discord.gg/test', allowed_mentions=unittest.mock.ANY)
        guild.create_invite.assert_not_called()

    async def test_missing_invite_permissions_are_explained(self):
        guild = SimpleNamespace(features=[], invites=AsyncMock(side_effect=nextcord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'test')))
        self.bot.get_guild.return_value = guild
        i = request()
        await Developer.get_inv.callback(self.cog, i, '123')
        self.assertIn('Управлять сервером', i.followup.send.call_args.args[0])

    async def test_vanity_link_does_not_need_invite_listing(self):
        guild = SimpleNamespace(features=['VANITY_URL'], vanity_invite=AsyncMock(
            return_value=SimpleNamespace(url='https://discord.gg/vanity')), invites=AsyncMock())
        self.bot.get_guild.return_value = guild
        i = request()
        await Developer.get_inv.callback(self.cog, i, '123')
        guild.invites.assert_not_awaited()
        i.followup.send.assert_awaited_once_with('https://discord.gg/vanity', allowed_mentions=unittest.mock.ANY)


class TransferTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        for g in game_manager.list_active():
            game_manager.remove(g.channel_id)

    def cog(self, current=None):
        mafia = SimpleNamespace(get_game=lambda cid: current)
        return SimpleNamespace(bot=SimpleNamespace(get_cog=lambda name: mafia))

    async def test_only_current_host_can_transfer(self):
        g = game_manager.create('mafia_lite', 1, 2, 1)
        g.players.append(2)
        i = request(3)
        await Games._transfer_host(self.cog(), i, SimpleNamespace(id=2, bot=False))
        self.assertEqual(g.host_id, 1)
        self.assertIn('Только ведущий', i.response.send_message.call_args.args[0])

    async def test_lobby_transfer_preserves_players_and_updates_message(self):
        g = game_manager.create('mafia_lite', 1, 2, 1)
        g.players.append(2)
        g.message_id = 99
        i = request()
        message = SimpleNamespace(edit=AsyncMock())
        i.channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        await Games._transfer_host(self.cog(), i, SimpleNamespace(id=2, bot=False, mention='<@2>'))
        self.assertEqual(g.host_id, 2)
        self.assertEqual(g.players, [1, 2])
        self.assertIn('<@2>', message.edit.call_args.kwargs['embed'].description)
        self.assertNotIn('ephemeral', i.response.send_message.call_args.kwargs)

    async def test_transfer_updates_live_mafia_and_existing_buttons(self):
        from cogs.mafia import DayView, Mafia
        g = game()
        g.phase = 'day'
        mafia = Mafia(None)
        mafia.games[2] = g
        g.cog = mafia
        g.channel = object()
        view = DayView(g)
        await Games._transfer_host(self.cog(g), request(), SimpleNamespace(id=2, bot=False, mention='<@2>'))
        self.assertEqual(g.host_id, 2)
        old = request(1)
        old.data['custom_id'] = view.to_vote.custom_id
        await view.to_vote.callback(old)
        self.assertFalse(g._day_finished)
        new = request(2)
        new.data['custom_id'] = view.to_vote.custom_id
        with patch.object(mafia, 'start_vote', new=AsyncMock()) as vote:
            await view.to_vote.callback(new)
            await asyncio.sleep(0)
            vote.assert_awaited_once()

    async def test_starting_game_nonparticipant_and_bot_are_rejected(self):
        g = game_manager.create('mafia_lite', 1, 2, 1)
        g.players.append(2)
        for state, member in [('starting', SimpleNamespace(id=2, bot=False)),
                              ('lobby', SimpleNamespace(id=3, bot=False)),
                              ('lobby', SimpleNamespace(id=2, bot=True))]:
            g.state = state
            i = request()
            await Games._transfer_host(self.cog(), i, member)
            self.assertEqual(g.host_id, 1)
            self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])

    async def test_transfer_command_uses_shared_handler(self):
        cog = SimpleNamespace(_transfer_host=AsyncMock())
        i, member = request(), object()
        await Games.transfer_host.callback(cog, i, member)
        self.assertEqual(cog._transfer_host.await_count, 1)

    async def test_support_uses_provided_link(self):
        i = request()
        with patch.dict('os.environ', {}, clear=True):
            await Lobby.support.callback(Lobby(None), i)
        self.assertIn('https://discord.gg/dArxQ8GV38', i.response.send_message.call_args.kwargs['embed'].description)
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])
