import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from database.db import get_player, ensure_player, get_top_players
from database.manager import game_manager
from utils.embeds import base_embed, GOLD

class Lobby(commands.Cog):
    """Общее лобби — приветствие, help, инфо, профиль, топ."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @nextcord.slash_command(name="lounge", description="Кто такой Lounge?")
    async def lounge(self, interaction: Interaction):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        embed = base_embed(
            title="🎩 Lounge",
            description=(
                "*Good Games Only.*\n\n"
                "Ваш вечерний распорядитель для настолок.\n"
                "Мафия, Бункер и прочие игры — присаживайтесь, господа."
            ),
            guild_name=guild_name,
        )
        embed.add_field(
            name="📜 Доступные команды",
            value=(
                "`/lounge` — эта справка\n"
                "`/ping` — проверить связь\n"
                "`/game-start` — создать лобби\n"
                "`/game-cancel` — отменить лобби\n"
                "`/profile` — карточка игрока\n"
                "`/top` — топ по фишкам\n"
                "`/active` — активные игры на сервере"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

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
            description="Джентльмен за столом.",
            guild_name=guild_name,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🎲 Партий", value=f"`{played}`", inline=True)
        embed.add_field(name="🏆 Побед", value=f"`{won}`", inline=True)
        embed.add_field(name="🪙 Фишек", value=f"`{chips}`", inline=True)

        await interaction.response.send_message(embed=embed)

    @nextcord.slash_command(name="top", description="Топ игроков по фишкам")
    async def top(self, interaction: Interaction):
        guild_name = interaction.guild.name if interaction.guild else "Lounge"
        rows = await get_top_players(interaction.guild_id, limit=10)

        if not rows:
            return await interaction.response.send_message(
                embed=base_embed(
                    title="🏆 Топ игроков",
                    description="Пока никто не играл. Тишина, сэр.",
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

        game_names = {
            "mafia_lite": "Мафия Lite",
            "mafia_full": "Мафия Full",
            "bunker": "Бункер",
            "custom": "Своя игра",
        }
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
            game_name = game_names.get(game_type, game_type)
            status = status_names.get(state, state)
            lines.append(
                f"• **{game_name}** в <#{g.channel_id}> — "
                f"{len(g.players)} игрок(ов), хост <@{g.host_id}>, статус **{status}**"
            )

        embed = base_embed(
            title=f"🎩 Активные игры ({len(games)})",
            description="\n".join(lines),
            guild_name=guild_name,
        )
        await interaction.response.send_message(embed=embed)

def setup(bot: commands.Bot):
    bot.add_cog(Lobby(bot))