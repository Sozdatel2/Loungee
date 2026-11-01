import asyncio
import time
import nextcord
from nextcord import Interaction
from nextcord.ext import commands, tasks
from database.manager import game_manager
from utils.embeds import lobby_embed, error_embed, success_embed, lobby_timeout_embed


LOBBY_TIMEOUT = 900   # 15 минут
CHECK_INTERVAL = 60   # проверяем раз в минуту


# ─────────────────────────────────────────────────────
#  Универсальное лобби
# ─────────────────────────────────────────────────────
class LobbyView(nextcord.ui.View):
    def __init__(self, channel_id: int, host_id: int):
        super().__init__(timeout=None)   # без авто-тайма View — таймером управляет cog
        self.channel_id = channel_id
        self.host_id = host_id
        self._bot = None

    def _game(self):
        return game_manager.get(self.channel_id)

    def _guild_name(self) -> str:
        if self._bot:
            ch = self._bot.get_channel(self.channel_id)
            if ch and ch.guild:
                return ch.guild.name
        return "Lounge"

    def _update_embed(self) -> nextcord.Embed:
        game = self._game()
        host_name = f"<@{game.host_id}>"
        players = [f"<@{pid}>" for pid in game.players]
        return lobby_embed(game.game_type, host_name, players, guild_name=self._guild_name())

    @nextcord.ui.button(label="Присоединиться", style=nextcord.ButtonStyle.success, emoji="✅")
    async def join(self, button: nextcord.ui.Button, interaction: Interaction):
        game = self._game()
        if not game:
            return await interaction.response.send_message(
                embed=error_embed("Лобби уже закрыто."), ephemeral=True
            )

        limits = {
            "mafia_lite": (4, 6),
            "mafia_full": (7, 15),
            "bunker": (4, 16),
        }
        min_p, max_p = limits.get(game.game_type, (2, 30))

        if len(game.players) >= max_p:
            return await interaction.response.send_message(
                embed=error_embed(f"Стол полон, сэр. Максимум {max_p}."), ephemeral=True
            )
        if not game.add_player(interaction.user.id):
            return await interaction.response.send_message(
                embed=error_embed("Ты уже за столом, сэр."), ephemeral=True
            )

        game.refresh_timer(LOBBY_TIMEOUT)   # продлеваем при активности
        await interaction.message.edit(embed=self._update_embed())
        await interaction.response.send_message(
            embed=success_embed(f"{interaction.user.mention} присоединился."), ephemeral=True
        )

    @nextcord.ui.button(label="Выйти", style=nextcord.ButtonStyle.secondary, emoji="🚪")
    async def leave(self, button: nextcord.ui.Button, interaction: Interaction):
        game = self._game()
        if not game:
            return await interaction.response.send_message(
                embed=error_embed("Лобби уже закрыто."), ephemeral=True
            )
        if interaction.user.id == game.host_id:
            return await interaction.response.send_message(
                embed=error_embed("Хост не может выйти. Отмени лобби."), ephemeral=True
            )
        if not game.remove_player(interaction.user.id):
            return await interaction.response.send_message(
                embed=error_embed("Тебя нет за столом."), ephemeral=True
            )
        game.refresh_timer(LOBBY_TIMEOUT)   # продлеваем при активности
        await interaction.message.edit(embed=self._update_embed())
        await interaction.response.send_message(
            embed=success_embed("Ты покинул стол."), ephemeral=True
        )

    @nextcord.ui.button(label="Начать", style=nextcord.ButtonStyle.primary, emoji="▶️")
    async def start(self, button: nextcord.ui.Button, interaction: Interaction):
        game = self._game()
        if not game:
            return await interaction.response.send_message(
                embed=error_embed("Лобби уже закрыто."), ephemeral=True
            )
        if interaction.user.id != game.host_id:
            return await interaction.response.send_message(
                embed=error_embed("Только хост может начать."), ephemeral=True
            )

        n = len(game.players)
        mins = {"mafia_lite": 4, "mafia_full": 7, "bunker": 4}
        min_p = mins.get(game.game_type, 2)

        if n < min_p:
            return await interaction.response.send_message(
                embed=error_embed(
                    f"Мало игроков, сэр. Для **{game.game_type}** минимум **{min_p}**, у вас **{n}**."
                ),
                ephemeral=True,
            )

        # ─── Мафия ─────────────────────────────────
        if game.game_type in ("mafia_lite", "mafia_full"):
            mafia_cog = self._bot.get_cog("Mafia") if self._bot else None
            if not mafia_cog:
                return await interaction.response.send_message(
                    embed=error_embed("Ког Мафии не загружен. Проверь лог."), ephemeral=True
                )

            mode = "lite" if game.game_type == "mafia_lite" else "full"
            players = list(game.players)

            game_manager.remove(self.channel_id)

            await interaction.response.send_message(
                embed=success_embed("🎭 Мафия начинается... роли разлетаются в ЛС.")
            )

            await mafia_cog.start_game(interaction, mode=mode, players=players)

            self.stop()
            try:
                await interaction.message.edit(view=None)
            except Exception:
                pass
            return

        # ─── Другие игры (заглушка) ────────────────
        game.state = "playing"
        await interaction.response.send_message(
            embed=success_embed(f"🎲 Игра **{game.game_type}** началась! (заглушка)")
        )

    @nextcord.ui.button(label="Отменить", style=nextcord.ButtonStyle.danger, emoji="✖️")
    async def cancel(self, button: nextcord.ui.Button, interaction: Interaction):
        game = self._game()
        if not game:
            return await interaction.response.send_message(
                embed=error_embed("Лобби уже закрыто."), ephemeral=True
            )
        if interaction.user.id != game.host_id:
            return await interaction.response.send_message(
                embed=error_embed("Только хост может отменить."), ephemeral=True
            )
        game_manager.remove(self.channel_id)
        await interaction.message.edit(
            embed=error_embed("Лобби отменено хостом."), view=None
        )
        await interaction.response.send_message("Лобби закрыто.", ephemeral=True)


# ─────────────────────────────────────────────────────
#  Ког команд
# ─────────────────────────────────────────────────────
class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lobby_watcher.start()

    def cog_unload(self):
        self._lobby_watcher.cancel()

    # ─── Фоновый таск: проверяем истёкшие лобби ───────
    @tasks.loop(seconds=CHECK_INTERVAL)
    async def _lobby_watcher(self):
        now = time.time()
        expired_channels = []
        for g in game_manager.list_active():
            if g.state == "lobby" and g.expires_at and now > g.expires_at:
                expired_channels.append(g.channel_id)

        for ch_id in expired_channels:
            g = game_manager.get(ch_id)
            if not g:
                continue
            game_manager.remove(ch_id)

            channel = self.bot.get_channel(ch_id)
            if not channel:
                continue
            guild_name = channel.guild.name if channel.guild else "Lounge"
            try:
                if g.message_id:
                    msg = await channel.fetch_message(g.message_id)
                    await msg.edit(embed=lobby_timeout_embed(guild_name), view=None)
                else:
                    await channel.send(embed=lobby_timeout_embed(guild_name))
            except Exception:
                pass

    @_lobby_watcher.before_loop
    async def _before_watcher(self):
        await self.bot.wait_until_ready()

    # ─── Команды ─────────────────────────────────────
    @nextcord.slash_command(name="game-start", description="Создать лобби для настолки")
    async def game_start(
        self,
        interaction: Interaction,
        game: str = nextcord.SlashOption(
            name="игра",
            description="Тип игры",
            choices={
                "🎭 Мафия Lite (4-6)": "mafia_lite",
                "🎭 Мафия Full (7-15)": "mafia_full",
                "🏚️ Бункер (4-16)": "bunker",
                "🎲 Кастом": "custom",
            },
            required=True,
        ),
    ):
        if game_manager.has_active(interaction.channel_id):
            return await interaction.response.send_message(
                embed=error_embed("В этом канале уже идёт лобби или игра."),
                ephemeral=True,
            )

        mafia_cog = self.bot.get_cog("Mafia")
        if mafia_cog and mafia_cog.has_active_game(interaction.channel_id):
            return await interaction.response.send_message(
                embed=error_embed("В этом канале уже идёт Мафия, сэр."),
                ephemeral=True,
            )

        g = game_manager.create(
            game_type=game,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            host_id=interaction.user.id,
        )
        g.refresh_timer(LOBBY_TIMEOUT)

        view = LobbyView(interaction.channel_id, interaction.user.id)
        view._bot = self.bot

        embed = lobby_embed(
            game,
            interaction.user.mention,
            [interaction.user.mention],
            guild_name=interaction.guild.name if interaction.guild else "Lounge",
        )
        await interaction.response.send_message(embed=embed, view=view)

        msg = await interaction.original_message()
        g.message_id = msg.id

    @nextcord.slash_command(name="game-cancel", description="Отменить текущее лобби или Мафию")
    async def game_cancel(self, interaction: Interaction):
        game = game_manager.get(interaction.channel_id)
        mafia_cog = self.bot.get_cog("Mafia")
        mafia_game = mafia_cog.get_game(interaction.channel_id) if mafia_cog else None
        if game is None and mafia_game is not None:
            if interaction.user.id != mafia_game.host_id:
                return await interaction.response.send_message(
                    embed=error_embed("Только хост может отменить."), ephemeral=True
                )
            if mafia_cog.cancel_game(interaction.channel_id):
                return await interaction.response.send_message(
                    embed=success_embed("Мафия отменена. Результаты и фишки не начисляются.")
                )
        if not game:
            return await interaction.response.send_message(
                embed=error_embed("В этом канале нет активной игры."), ephemeral=True
            )
        if interaction.user.id != game.host_id:
            return await interaction.response.send_message(
                embed=error_embed("Только хост может отменить."), ephemeral=True
            )
        game_manager.remove(interaction.channel_id)
        await interaction.response.send_message(embed=success_embed("Игра отменена."))


def setup(bot: commands.Bot):
    bot.add_cog(Games(bot))