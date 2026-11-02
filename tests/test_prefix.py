import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import nextcord
from nextcord.ext import commands

from main import Lounge
from utils.prefix import PrefixInteraction
from database.manager import game_manager


class PrefixTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Lounge()
        self.bot._connection.user = SimpleNamespace(id=999)
        from cogs.lobby import Lobby
        from cogs.games import Games
        from cogs.mafia import Mafia
        from cogs.developer import Developer
        for cog in (Lobby, Games, Mafia, Developer):
            self.bot.add_cog(cog(self.bot))
        self.author = SimpleNamespace(id=111111111111111111, bot=False,
                                      display_name='Tester', mention='<@111111111111111111>',
                                      send=AsyncMock(), display_avatar=SimpleNamespace(url='https://example.com/avatar.png'))
        self.other = Mock(spec=nextcord.Member)
        self.other.id = 222222222222222222
        self.other.bot = False
        self.other.mention = '<@222222222222222222>'
        self.guild = SimpleNamespace(id=1, name='Test Server',
                                     get_member=lambda uid: self.other if uid == self.other.id else self.author)
        self.channel = SimpleNamespace(id=2)

    async def asyncTearDown(self):
        for name in tuple(self.bot.cogs):
            self.bot.remove_cog(name)
        await self.bot.close()
        for game in game_manager.list_active():
            game_manager.remove(game.channel_id)

    async def context(self, text):
        message = SimpleNamespace(content=text, author=self.author, channel=self.channel,
                                  guild=self.guild, _state=self.bot._connection, attachments=[], mentions=[self.other])
        ctx = await self.bot.get_context(message)
        ctx.send = AsyncMock(return_value=SimpleNamespace(id=10, delete=AsyncMock()))
        return ctx

    async def test_registry_excludes_owner_slashes_and_removed_alias(self):
        slash = {c.name for c in self.bot.get_application_commands(rollout=True)}
        self.assertFalse({'servers', 'get-sid', 'get-inv', 'host-transfer'} & slash)
        self.assertIsNone(self.bot.get_command('host-transfer'))
        self.assertTrue(slash <= set(self.bot.all_commands))
        self.assertTrue({'servers', 'get-sid', 'get-inv'} <= set(self.bot.all_commands))

    async def test_upper_and_lower_prefix_help_work(self):
        for text in ('L.help', 'l.help'):
            self.bot.command_cooldown.entries.clear()
            ctx = await self.context(text)
            await ctx.command.invoke(ctx)
            embed = ctx.send.call_args.kwargs['embed']
            self.assertIn('Справочник', embed.title)
            self.assertTrue(any('/transfer-host' in field.value for field in embed.fields))
            self.assertLess(len(embed), 6000)

    async def test_optional_profile_argument_defaults_to_self(self):
        ctx = await self.context('L.profile')
        with patch('cogs.lobby.get_player', new=AsyncMock(return_value=None)) as lookup:
            await ctx.command.invoke(ctx)
        lookup.assert_awaited_once_with(1, self.author.id)
        self.assertIn('Tester', ctx.send.call_args.kwargs['embed'].title)

    async def test_member_conversion_and_transfer(self):
        lobby = game_manager.create('mafia_lite', 1, 2, self.author.id)
        lobby.players.append(self.other.id)
        ctx = await self.context('L.transfer-host <@222222222222222222>')
        await ctx.command.invoke(ctx)
        self.assertEqual(lobby.host_id, self.other.id)

    async def test_game_choice_validation(self):
        ctx = await self.context('L.game-start invalid')
        with self.assertRaises(commands.BadArgument):
            await ctx.command.invoke(ctx)
        self.assertFalse(game_manager.has_active(2))

    async def test_prefix_lobby_posts_buttons_and_records_response_id(self):
        ctx = await self.context('L.game-start mafia_lite')
        await ctx.command.invoke(ctx)
        lobby = game_manager.get(2)
        self.assertEqual(lobby.message_id, 10)
        self.assertIn('view', ctx.send.call_args.kwargs)

    async def test_native_owner_check_blocks_before_callback(self):
        self.bot.is_owner = AsyncMock(return_value=False)
        for text in ('L.servers', 'L.get-sid Test Server', 'L.get-inv 123'):
            ctx = await self.context(text)
            with self.assertRaises(commands.NotOwner):
                await ctx.command.invoke(ctx)
        self.author.send.assert_not_awaited()

    async def test_owner_multiword_lookup_and_private_response(self):
        self.bot.is_owner = AsyncMock(return_value=True)
        self.bot._connection._guilds = {1: self.guild}
        ctx = await self.context('L.get-sid Test Server')
        await ctx.command.invoke(ctx)
        self.assertIn('Test Server', self.author.send.call_args.kwargs['embed'].description)
        ctx.send.assert_not_awaited()

    async def test_closed_dms_never_publish_private_data(self):
        self.author.send.side_effect = nextcord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'test')
        ctx = await self.context('L.support')
        await PrefixInteraction(ctx).send_message('sensitive invite', ephemeral=True)
        self.assertNotIn('sensitive', str(ctx.send.call_args))
        self.assertIn('ЛС', ctx.send.call_args.args[0])

    async def test_application_checks_also_apply_to_prefix(self):
        slash = next(c for c in self.bot.get_application_commands(rollout=True) if c.name == 'lounge')
        with patch.object(slash, 'checks', [lambda interaction: False]):
            ctx = await self.context('L.lounge')
            with self.assertRaises(commands.CheckFailure):
                await ctx.command.invoke(ctx)
        ctx.send.assert_not_awaited()

    async def test_new_slash_automatically_gets_prefix_variant(self):
        @self.bot.slash_command(name='future', description='future command')
        async def future(interaction, count: int):
            await interaction.response.send_message(str(count))
        self.bot.add_all_application_commands()
        ctx = await self.context('L.future 7')
        await ctx.command.invoke(ctx)
        self.assertEqual(ctx.send.call_args.args[0], '7')

    async def test_reload_removes_old_prefix_wrappers(self):
        from cogs.lobby import Lobby
        self.bot.remove_cog('Lobby')
        self.bot.add_cog(Lobby(self.bot))
        ctx = await self.context('L.help')
        await ctx.command.invoke(ctx)
        self.assertIn('Справочник', ctx.send.call_args.kwargs['embed'].title)

    async def test_prefix_is_blocked_until_initialization(self):
        import main
        self.bot.add_check(main.prefix_ready)
        ctx = await self.context('L.lounge')
        with patch.object(main, '_initialized', False):
            with self.assertRaises(commands.CheckFailure):
                await ctx.command.invoke(ctx)
        self.assertIn('готовится', ctx.send.call_args.args[0])

    async def test_new_command_permissions_cannot_be_bypassed_by_prefix(self):
        @self.bot.slash_command(name='restricted', description='restricted',
                               default_member_permissions=nextcord.Permissions(manage_guild=True))
        async def restricted(interaction):
            await interaction.response.send_message('secret')
        self.bot.add_all_application_commands()
        self.author.guild_permissions = nextcord.Permissions.none()
        ctx = await self.context('L.restricted')
        with self.assertRaises(commands.CheckFailure):
            await ctx.command.invoke(ctx)
        ctx.send.assert_not_awaited()
