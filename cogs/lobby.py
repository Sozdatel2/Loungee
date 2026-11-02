import os
import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from database.db import get_player, get_top_players
from database.manager import game_manager
from utils.embeds import base_embed
from utils import VERSION, CHIPS_WIN, CHIPS_LOSE, GAME_NAMES, BOT_INVITE_URL

class Lobby(commands.Cog):
    """Общее лобби — приветствие, help, инфо, профиль, топ."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(name="lounge", description="Кто такой Lounge?")
    async def lounge(self, interaction: Interaction):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        embed = base_embed(
            title=f"🎩 Lounge • {VERSION}",
            description=(
                "*Good Games Only.*\n\n"
                "Ваш вечерний распорядитель для настолок.\n"
                "Мафия Lite и Full — присаживайтесь, господа.\n"
                "Бункер и Своя игра пока доступны только как заготовки лобби."
            ),
            guild_name=guild_name,
        )
        embed.add_field(name="🎩 Пригласить Lounge", value=f"[Добавить бота на сервер]({BOT_INVITE_URL})", inline=False)
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="help", description="Справка по категориям команд Lounge")
    async def help_command(self, interaction: Interaction,
                           category: str = nextcord.SlashOption(name="категория", required=False,
                                                                 min_length=1, max_length=32)):
        aliases = {
            "общие": "general", "general": "general", "основное": "general",
            "игры": "games", "games": "games", "game": "games",
            "профиль": "profile", "profile": "profile", "статистика": "profile",
            "поддержка": "support", "support": "support",
            "разработчик": "developer", "developer": "developer", "dev": "developer",
        }
        selected = aliases.get(category.strip().casefold()) if category else None
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        if category and selected is None:
            return await interaction.response.send_message(
                "Категория не найдена, сэр. Доступны: общие, игры, профиль, поддержка, разработчик.", ephemeral=True)
        if selected == "developer":
            await interaction.response.defer(ephemeral=True)
            try:
                owner = await self.bot.is_owner(interaction.user)
            except nextcord.HTTPException:
                owner = False
            if not owner:
                return await interaction.followup.send("Эта категория доступна только создателю бота, сэр.", ephemeral=True)
            embed = base_embed(title="🛠 Справка · Разработчик", description=(
                "Только префиксные команды; ответы приходят в ЛС.\n\n"
                "`L.servers [страница]` — серверы бота и их ID.\n"
                "`L.get-sid Название сервера` — ID по полному названию.\n"
                "`L.get-inv ID` — существующее приглашение; боту нужны права на просмотр приглашений."),
                guild_name=guild_name)
            return await interaction.followup.send(embed=embed, ephemeral=True)
        sections = {
            "general": ("🎩 Общие", "`/lounge` — о боте и приглашение.\n`/help [категория]` — справка.\n`/ping` — задержка соединения."),
            "games": ("🎲 Игры", "`/game-start` — создать лобби.\n`/game-cancel` — отменить лобби или Мафию.\n"
                      "`/transfer-host` — передать ведение.\n`/active` — активные столы.\n`/rules [режим]` — правила Мафии."),
            "profile": ("👤 Профиль", "`/profile [игрок]` — статистика, процент побед и фишки.\n`/top` — рейтинг сервера."),
            "support": ("💬 Поддержка", "`/support` — обратиться в поддержку и сообщить об ошибке."),
        }
        if selected:
            title, text = sections[selected]
            embed = base_embed(title=f"📖 Справка · {title}", description=text, guild_name=guild_name)
        else:
            embed = base_embed(title="📖 Справочник Lounge", description=(
                "Выберите категорию: `L.help игры` или `/help категория:игры`.\n"
                "Все публичные команды работают через `/`, **L.** и **l.**.\n"
                "Аргументы префиксных команд указываются после имени команды; приватные ответы приходят в ЛС."),
                guild_name=guild_name)
            for key, (title, text) in sections.items():
                embed.add_field(name=title, value=f"`L.help {key}`\n{text}", inline=False)
            embed.add_field(name="🛠 Разработчик", value="`L.help developer` — закрытая справка создателя.", inline=False)
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="rules", description="Правила, роли и награды Мафии")
    async def rules(self, interaction: Interaction,
                    mode: str = nextcord.SlashOption(name="режим", required=False, default="all",
                        choices={"Все режимы": "all", "Мафия Lite": "lite", "Мафия Full": "full"})):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        embed = base_embed(title="🎭 Правила Мафии", guild_name=guild_name)
        embed.add_field(
            name="🎭 Режимы и роли",
            value=(
                "**Lite · 4–6 игроков:** мафия и мирные.\n"
                "**Full · 7–15 игроков:** мафия, мирные, комиссар и доктор.\n"
                "🎩 Мафия выбирает жертву ночью.\n"
                "👤 Мирные ищут мафию и голосуют днём.\n"
                "🕵️ Комиссар проверяет одного игрока за ночь.\n"
                "💉 Доктор лечит одного игрока; себя — не две ночи подряд."
            ),
            inline=False,
        )
        embed.add_field(
            name="📖 Как проходит партия",
            value=(
                "Роли приходят в ЛС — разрешите сообщения от бота.\n"
                "Ночь → обсуждение → тайное голосование. Ведущий может ускорить обсуждение.\n"
                "Мирные побеждают, когда мафии не осталось. Мафия — когда её живых "
                "участников не меньше, чем остальных живых игроков.\n"
                "Голос за себя считается воздержанием; при дневной ничьей казни нет."
            ),
            inline=False,
        )
        embed.add_field(
            name="🪙 Награды за завершённую Мафию",
            value=(f"Победителям — **{CHIPS_WIN} фишек**, проигравшим — **{CHIPS_LOSE}**.\n"
                   "При отмене награды не начисляются. Профиль и рейтинг отдельные на каждом сервере."),
            inline=False,
        )
        if mode == "lite":
            embed.title = "🎭 Правила · Мафия Lite"
            embed.set_field_at(0, name="🎭 Режим и роли", value=(
                "**4–6 игроков:** один мафиози, остальные — мирные.\n"
                "🎩 Мафия выбирает жертву ночью.\n👤 Мирные ищут мафию и голосуют днём."), inline=False)
        elif mode == "full":
            embed.title = "🎭 Правила · Мафия Full"
            first = embed.fields[0]
            embed.set_field_at(0, name=first.name, value=first.value.split("\n", 1)[1], inline=False)
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="support", description="Поддержка Lounge и обратная связь")
    async def support(self, interaction: Interaction):
        support_url = os.getenv("LOUNGE_SUPPORT_URL", "https://discord.gg/dArxQ8GV38")
        embed = base_embed(
            title="🎩 Поддержка Lounge",
            description=(f"[Обратиться в поддержку]({support_url})\n\n"
                         "Опишите, что делали, что ожидали и что произошло. "
                         "Добавьте время ошибки и скриншот, если он есть. "
                         "Токены и личную переписку присылать не нужно, сэр."),
            guild_name=interaction.guild.name if interaction.guild else "Lounge",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @nextcord.slash_command(name="profile", description="Карточка игрока")
    async def profile(
        self,
        interaction: Interaction,
        user: nextcord.Member = nextcord.SlashOption(
            name="игрок", description="Чей профиль", required=False
        ),
    ):
        target = user or interaction.user
        guild_name = interaction.guild.name if interaction.guild else "Lounge"

        row = await get_player(interaction.guild_id, target.id)

        if row:
            username, played, won, chips = row
        else:
            username, played, won, chips = target.display_name, 0, 0, 0

        embed = base_embed(
            title=f"🎩 Профиль: {username}",
            description="Ваша история за игровым столом, сэр.",
            guild_name=guild_name,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🎲 Партий", value=f"`{played}`", inline=True)
        embed.add_field(name="🏆 Побед", value=f"`{won}`", inline=True)
        embed.add_field(name="🪙 Фишек", value=f"`{chips}`", inline=True)
        win_rate = f"{won / played * 100:.1f}%" if played else "— (ещё нет партий)"
        embed.add_field(name="📊 Процент побед", value=win_rate, inline=True)

        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="top", description="Топ игроков по фишкам")
    async def top(self, interaction: Interaction):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        rows = await get_top_players(interaction.guild_id, limit=10)

        if not rows:
            return await interaction.response.send_message(
                embed=base_embed(
                    title="🏆 Топ игроков",
                    description="Пока никто не играл, сэр. Самое время открыть первый стол.",
                    guild_name=guild_name,
                )
            )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, username, chips, played, won) in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(
                f"{prefix} **{username}** — 🪙 {chips} "
                f"({won}🏆 / {played}🎲)"
            )

        embed = base_embed(
            title="🏆 Топ игроков",
            description="\n".join(lines),
            guild_name=guild_name,
        )
        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="active", description="Активные игры на сервере")
    async def active(self, interaction: Interaction):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        games = game_manager.list_active(guild_id=interaction.guild_id)

        mafia = self.bot.get_cog("Mafia")
        if mafia:
            games.extend(g for g in mafia.games.values() if g.guild_id == interaction.guild_id)

        if not games:
            return await interaction.response.send_message(
                embed=base_embed(
                    title="🎩 Активные игры",
                    description="Сейчас за столом пусто. Тишина, сэр.",
                    guild_name=guild_name,
                )
            )

        status_names = {
            "lobby": "Сбор игроков",
            "starting": "Запуск игры",
            "playing": "В игре",
            "setup": "Подготовка",
            "night": "Ночь",
            "day": "Обсуждение",
            "vote": "Голосование",
            "resolving": "Итоги ночи",
            "resolving_vote": "Итоги голосования",
            "ended": "Завершена",
            "cancelled": "Отменена",
        }
        lines = []
        for g in games:
            game_type = getattr(g, "game_type", None) or f"mafia_{g.mode}"
            state = getattr(g, "state", None) or g.phase
            game_name = GAME_NAMES.get(game_type, game_type)
            status = status_names.get(state, state)
            lines.append(
                f"• **{game_name}** в <#{g.channel_id}> — "
                f"{len(g.players)} игрок(ов), ведущий <@{g.host_id}>, статус **{status}**"
            )

        embed = base_embed(
            title=f"🎩 Активные игры ({len(games)})",
            description="\n".join(lines),
            guild_name=guild_name,
        )
        await interaction.response.send_message(embed=embed)

def setup(bot: commands.Bot):
    bot.add_cog(Lobby(bot))