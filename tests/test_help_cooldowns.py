import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from nextcord.ext import commands
from cogs.lobby import Lobby
from main import Lounge
from utils.cooldowns import UserCooldown
from test_mafia import interaction
import test_prefix as prefix_cases


class CooldownTests(unittest.IsolatedAsyncioTestCase):
    def request(self, user=1, name='help', prefix=False):
        i = interaction(user)
        i.application_command = SimpleNamespace(name=name)
        if prefix:
            i.context = SimpleNamespace()
        return i

    async def test_users_are_independent_across_servers(self):
        limiter = UserCooldown(clock=lambda: 10)
        first = self.request()
        self.assertTrue(await limiter.allow(first))
        first.guild_id = 99
        self.assertFalse(await limiter.allow(first))
        self.assertTrue(await limiter.allow(self.request(user=2)))
        self.assertTrue(await limiter.allow(self.request(name='rules')))

    async def test_window_expires_and_attempts_do_not_extend_it(self):
        now = [0.0]
        limiter = UserCooldown(clock=lambda: now[0])
        self.assertTrue(await limiter.allow(self.request()))
        now[0] = 2.0
        self.assertFalse(await limiter.allow(self.request()))
        now[0] = 3.0
        self.assertTrue(await limiter.allow(self.request()))

    async def test_prefix_notice_is_not_repeated_on_spam(self):
        limiter = UserCooldown(clock=lambda: 1)
        i = self.request(prefix=True)
        self.assertTrue(await limiter.allow(i))
        for _ in range(5):
            self.assertFalse(await limiter.allow(i))
        i.response.send_message.assert_awaited_once()
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])

    async def test_expired_entries_are_removed(self):
        now = [0.0]
        limiter = UserCooldown(clock=lambda: now[0])
        for uid in range(100):
            await limiter.allow(self.request(user=uid))
        now[0] = 4.0
        await limiter.allow(self.request(user=1000))
        self.assertEqual(len(limiter.entries), 1)


class HelpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(is_owner=AsyncMock(return_value=False))
        self.cog = Lobby(self.bot)

    def request(self):
        i = interaction(1)
        i.guild = SimpleNamespace(name='test')
        i.response.defer = AsyncMock()
        i.followup = SimpleNamespace(send=AsyncMock())
        return i

    async def test_categories_and_aliases(self):
        for category in (None, 'игры', 'GAMES', 'профиль', 'поддержка', 'общие'):
            i = self.request()
            await Lobby.help_command.callback(self.cog, i, category)
            embed = i.response.send_message.call_args.kwargs['embed']
            self.assertLess(len(embed), 6000)
            self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
            self.assertFalse(any(field.name == '🎭 Режимы и роли' for field in embed.fields))

    async def test_unknown_category_has_private_explanation(self):
        i = self.request()
        await Lobby.help_command.callback(self.cog, i, 'missing')
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])

    async def test_developer_category_is_owner_only_and_private(self):
        i = self.request()
        await Lobby.help_command.callback(self.cog, i, 'developer')
        self.assertIn('только создателю', i.followup.send.call_args.args[0])
        self.bot.is_owner.return_value = True
        i = self.request()
        await Lobby.help_command.callback(self.cog, i, 'разработчик')
        self.assertIn('L.servers', i.followup.send.call_args.kwargs['embed'].description)
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])

    async def test_rules_modes_are_separate_from_help(self):
        for mode in ('all', 'lite', 'full'):
            i = self.request()
            await Lobby.rules.callback(self.cog, i, mode)
            embed = i.response.send_message.call_args.kwargs['embed']
            self.assertIn('Правила', embed.title)
            self.assertLess(len(embed), 6000)
            if mode == 'lite':
                self.assertNotIn('Комиссар', embed.fields[0].value)
            elif mode == 'full':
                self.assertNotIn('Lite', embed.fields[0].value)


class PrefixCooldownIntegration(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = prefix_cases.PrefixTests.asyncSetUp
    asyncTearDown = prefix_cases.PrefixTests.asyncTearDown
    context = prefix_cases.PrefixTests.context
    async def test_slash_and_prefix_share_user_bucket(self):
        ctx = await self.context('L.help игры')
        await ctx.command.invoke(ctx)
        slash = next(c for c in self.bot.get_application_commands(rollout=True) if c.name == 'help')
        i = interaction(self.author.id)
        i.application_command = slash
        self.assertFalse(await self.bot._slash_cooldown(i))
        again = await self.context('l.help games')
        with self.assertRaises(commands.CheckFailure):
            await again.command.invoke(again)

    async def test_prefix_rules_and_category_arguments(self):
        ctx = await self.context('L.help игры')
        await ctx.command.invoke(ctx)
        self.assertIn('/rules', ctx.send.call_args.kwargs['embed'].description)
        ctx = await self.context('L.rules full')
        await ctx.command.invoke(ctx)
        self.assertIn('Мафия Full', ctx.send.call_args.kwargs['embed'].title)
