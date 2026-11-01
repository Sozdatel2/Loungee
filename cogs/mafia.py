import asyncio
import json
import random
import time
import uuid
import logging
import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from utils.roles import get_role
from utils import CHIPS_WIN, CHIPS_LOSE
from utils import embeds as E
from database.db import record_game_result, ensure_player


log = logging.getLogger(__name__)


class GameView(nextcord.ui.View):
    async def validate_game(self, interaction: Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id", "")
        parts = custom_id.split(":")
        current = self.mg.cog.get_game(self.mg.channel_id) if self.mg.cog else self.mg
        if (len(parts) < 2 or parts[1] != self.mg.game_id
                or current is not self.mg):
            await interaction.response.send_message(
                "Это кнопки от старой игры, сэр", ephemeral=True
            )
            return False
        return True


NIGHT_DURATION = 120
DAY_DURATION = 300
VOTE_DURATION = 60


EXECUTION_FLAVORS = [
    "🎩 Дон приказал — и приговор приведён в исполнение.",
    "🔫 Прогремел выстрел в ночи.",
    "🌊 Тело нашли у причала.",
    "🍷 Он отправился на «деловую встречу» и не вернулся.",
    "🚗 Он сел не в ту машину. Больше его не видели.",
    "⚰️ Он узнал слишком много. Увы.",
    "🎻 Он услышал скрипку. Последнюю.",
    "🕴️ Он вошёл в тёмный переулок. Обратно не вышел.",
    "🥀 Судьба настигла его быстрее, чем правосудие.",
    "🎩 Семья вынесла приговор. Обжалованию не подлежит.",
]


# ─────────────────────────────────────────────────────
#  View: ночное действие
# ─────────────────────────────────────────────────────
class NightActionView(GameView):
    def __init__(self, mafia_game, actor_id: int, action: str):
        super().__init__(timeout=NIGHT_DURATION + 30)
        self.mg = mafia_game
        self.round = mafia_game.day
        self.actor_id = actor_id
        self.action = action
        self.chosen = None

        candidates = self.mg.action_targets(action, actor_id)

        for uid in candidates[:25]:
            btn = nextcord.ui.Button(
                label=self.mg.short_name(uid),
                style=nextcord.ButtonStyle.secondary,
                custom_id=f"{action}:{self.mg.game_id}:{uid}",
            )
            btn.callback = self._make_callback(uid)
            self.add_item(btn)

    def _make_callback(self, uid: int):
        async def callback(interaction: Interaction):
            if not await self.validate_game(interaction):
                return
            if interaction.user.id != self.actor_id:
                return await interaction.response.send_message(
                    "Это не ваша кнопка, сэр.", ephemeral=True
                )
            if self.chosen is not None:
                return await interaction.response.send_message(
                    "Вы уже сделали выбор, сэр.", ephemeral=True
                )

            if not self.mg.register_action(self.action, self.actor_id, uid, self.round):
                return await interaction.response.send_message(
                    "Это действие уже недоступно, сэр.", ephemeral=True
                )
            self.chosen = uid
            self.mg.maybe_finish_night()

            if self.action == "kill":
                await interaction.response.send_message(
                    f"🎩 Цель выбрана: **{self.mg.short_name(uid)}**. Ждём остальных.",
                    ephemeral=True,
                )
            elif self.action == "heal":
                await interaction.response.send_message(
                    f"💉 Лечите: **{self.mg.short_name(uid)}**. Ждём остальных.",
                    ephemeral=True,
                )
            elif self.action == "check":
                is_mafia = self.mg.role_of(uid) == "mafia"
                await interaction.response.send_message(
                    embed=E.cop_result_embed(self.mg.short_name(uid), is_mafia),
                    ephemeral=True,
                )

            for item in self.children:
                item.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass


        return callback


# ─────────────────────────────────────────────────────
#  View: день
# ─────────────────────────────────────────────────────
class DayView(GameView):
    def __init__(self, mafia_game):
        super().__init__(timeout=DAY_DURATION + 30)
        self.mg = mafia_game
        self.round = mafia_game.day

        self.to_vote.custom_id = f"day:{self.mg.game_id}:vote"

    @nextcord.ui.button(label="К голосованию", style=nextcord.ButtonStyle.primary, emoji="🗳️")
    async def to_vote(self, button: nextcord.ui.Button, interaction: Interaction):
        if not await self.validate_game(interaction):
            return
        if interaction.user.id != self.mg.host_id:
            return await interaction.response.send_message(
                "Только ведущий может ускорить, сэр.", ephemeral=True
            )
        if not self.mg.accepts("day", self.round):
            return await interaction.response.send_message(
                "Уже не день, сэр.", ephemeral=True
            )
        self.mg._day_finished = True
        for task in self.mg._day_tasks:
            if not task.done():
                task.cancel()
        if self.mg.cog and self.mg.channel:
            asyncio.create_task(self.mg.cog.start_vote(self.mg))
        self.stop()
        await interaction.response.send_message("⏩ Ведущий ускорил обсуждение.", ephemeral=False)


# ─────────────────────────────────────────────────────
#  View: голосование
# ─────────────────────────────────────────────────────
class VoteView(GameView):
    def __init__(self, mafia_game):
        super().__init__(timeout=VOTE_DURATION + 30)
        self.mg = mafia_game
        self.round = mafia_game.day

        for uid in list(self.mg.alive):
            btn = nextcord.ui.Button(
                label=self.mg.short_name(uid),
                style=nextcord.ButtonStyle.secondary,
                custom_id=f"vote:{self.mg.game_id}:{uid}",
            )
            btn.callback = self._make_vote_callback(uid)
            self.add_item(btn)

        abstain = nextcord.ui.Button(
            label="Воздержаться",
            style=nextcord.ButtonStyle.danger,
            emoji="🤐",
            custom_id=f"vote:{self.mg.game_id}:abstain",
        )
        abstain.callback = self._abstain_callback
        self.add_item(abstain)

    def _make_vote_callback(self, target_id: int):
        async def callback(interaction: Interaction):
            if not await self.validate_game(interaction):
                return
            voter_id = interaction.user.id
            if not self.mg.accepts("vote", self.round) or target_id not in self.mg.alive:
                return await interaction.response.send_message("Голосование уже недоступно, сэр.", ephemeral=True)
            if voter_id not in self.mg.alive:
                return await interaction.response.send_message(
                    "Мёртвые не голосуют, сэр.", ephemeral=True
                )
            if voter_id in self.mg.votes:
                return await interaction.response.send_message(
                    "Вы уже голосовали, сэр.", ephemeral=True
                )

            # ─── Голос за себя = воздержание ───
            if target_id == voter_id:
                self.mg.votes[voter_id] = -1
                self.mg.maybe_finish_vote()
                await interaction.response.send_message(
                    "🤐 За себя нельзя, сэр. Ваш голос засчитан как **воздержание**.",
                    ephemeral=True,
                )
                return

            self.mg.votes[voter_id] = target_id
            self.mg.maybe_finish_vote()
            await interaction.response.send_message(
                f"🗳️ Голос за **{self.mg.short_name(target_id)}** принят.",
                ephemeral=True,
            )

        return callback

    async def _abstain_callback(self, interaction: Interaction):
        if not await self.validate_game(interaction):
            return
        voter_id = interaction.user.id
        if not self.mg.accepts("vote", self.round):
            return await interaction.response.send_message("Голосование уже недоступно, сэр.", ephemeral=True)
        if voter_id not in self.mg.alive:
            return await interaction.response.send_message(
                "Мёртвые не голосуют, сэр.", ephemeral=True
            )
        if voter_id in self.mg.votes:
            return await interaction.response.send_message(
                "Вы уже голосовали, сэр.", ephemeral=True
            )
        self.mg.votes[voter_id] = -1
        self.mg.maybe_finish_vote()
        await interaction.response.send_message(
            "🤐 Вы воздержались.", ephemeral=True
        )


# ─────────────────────────────────────────────────────
#  Состояние партии
# ─────────────────────────────────────────────────────
class MafiaGame:
    def __init__(self, mode: str, guild_id: int, channel_id: int, host_id: int, players: list[int]):
        self.game_id: str = uuid.uuid4().hex
        self.mode = mode
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.host_id = host_id
        self.players = list(players)
        self.day = 0
        self.phase = "setup"

        self.created_at = time.time()
        self.finished_at: float | None = None

        self.roles: dict[int, str] = {}
        self.alive: set[int] = set(players)
        self.dead: set[int] = set()
        self.dead_log: list[tuple[int, str]] = []

        self.mafia_votes: dict[int, int] = {}
        self.doctor_target = None
        self.last_self_heal_day = None
        self.cop_checks: dict[int, bool] = {}

        self.votes: dict[int, int] = {}

        self._night_tasks = []
        self._day_tasks = []
        self._vote_tasks = []
        self._night_finished = False
        self._day_finished = False
        self._vote_finished = False

        self.channel = None
        self.cog = None

    def cancel_timers(self) -> None:
        for task in self._night_tasks + self._day_tasks + self._vote_tasks:
            if task is not asyncio.current_task() and not task.done():
                task.cancel()

    # ─── Роли ────────────────────────────────────────
    def assign_roles(self) -> None:
        n = len(self.players)
        shuffled = self.players.copy()
        random.shuffle(shuffled)
        idx = 0
        self.roles = {}

        if self.mode == "lite":
            self.roles[shuffled[idx]] = "mafia"; idx += 1
            for uid in shuffled[idx:]:
                self.roles[uid] = "civilian"

        elif self.mode == "full":
            if n == 7:
                mafia_count = 1
            elif n <= 9:
                mafia_count = 2
            else:
                mafia_count = 3

            for _ in range(mafia_count):
                self.roles[shuffled[idx]] = "mafia"; idx += 1
            self.roles[shuffled[idx]] = "cop"; idx += 1
            self.roles[shuffled[idx]] = "doctor"; idx += 1
            for uid in shuffled[idx:]:
                self.roles[uid] = "civilian"

    # ─── Хелперы ─────────────────────────────────────
    def mafia_ids(self) -> list[int]:
        return [uid for uid, r in self.roles.items() if r == "mafia"]

    def role_of(self, user_id: int) -> str:
        return self.roles.get(user_id, "civilian")

    def is_alive(self, user_id: int) -> bool:
        return user_id in self.alive

    def kill(self, user_id: int, reason: str) -> None:
        self.alive.discard(user_id)
        self.dead.add(user_id)
        self.dead_log.append((user_id, reason))

    def short_name(self, user_id: int) -> str:
        if self.channel and self.channel.guild:
            member = self.channel.guild.get_member(user_id)
            if member:
                return member.display_name[:30]
        return f"User{user_id % 10000}"

    def mention(self, user_id: int) -> str:
        return f"<@{user_id}>"

    def dead_log_formatted(self) -> list[tuple[str, str]]:
        return [(self.mention(uid), reason) for uid, reason in self.dead_log]

    # ─── Ночные действия ─────────────────────────────
    def accepts(self, phase: str, round_number: int) -> bool:
        if self.phase != phase or self.day != round_number:
            return False
        if getattr(self, f"_{phase}_finished", False):
            return False
        return self.cog is None or self.cog.get_game(self.channel_id) is self

    def action_targets(self, action: str, actor_id: int) -> list[int]:
        return [uid for uid in sorted(self.alive)
                if uid != actor_id or (
                    action == "heal" and self.last_self_heal_day != self.day - 1
                )]

    def register_action(self, action: str, actor_id: int, target_id: int,
                        round_number: int | None = None) -> bool:
        if not self.accepts("night", self.day if round_number is None else round_number):
            return False
        role = {"kill": "mafia", "heal": "doctor", "check": "cop"}.get(action)
        if (role is None or actor_id not in self.alive or self.role_of(actor_id) != role
                or target_id not in self.action_targets(action, actor_id)):
            return False
        if action == "kill":
            if actor_id in self.mafia_votes:
                return False
            self.mafia_votes[actor_id] = target_id
        elif action == "heal":
            if self.doctor_target is not None:
                return False
            self.doctor_target = target_id
            if target_id == actor_id:
                self.last_self_heal_day = self.day
        elif action == "check":
            if self.cop_checks:
                return False
            self.cop_checks[target_id] = self.role_of(target_id) == "mafia"
        return True

    def expected_night_actions(self) -> int:
        count = sum(uid in self.alive for uid in self.mafia_ids())
        if self.mode == "full":
            if self._alive_role("cop"):
                count += 1
            if self._alive_role("doctor"):
                count += 1
        return count

    def _alive_role(self, role: str) -> bool:
        return any(uid in self.alive and self.roles.get(uid) == role for uid in self.roles)

    def received_night_actions(self) -> int:
        count = len(self.mafia_votes)
        if self.mode == "full":
            if self._alive_role("cop") and self.cop_checks:
                count += 1
            if self._alive_role("doctor") and self.doctor_target is not None:
                count += 1
        return count

    def maybe_finish_night(self) -> None:
        if not self.accepts("night", self.day):
            return
        if self.received_night_actions() >= self.expected_night_actions():
            self._night_finished = True
            for task in self._night_tasks:
                if not task.done():
                    task.cancel()
            if self.cog and self.channel:
                asyncio.create_task(self.cog.resolve_night(self))

    def maybe_finish_vote(self) -> None:
        if not self.accepts("vote", self.day):
            return
        if len(self.votes) >= len(self.alive):
            self._vote_finished = True
            for task in self._vote_tasks:
                if not task.done():
                    task.cancel()
            if self.cog and self.channel:
                asyncio.create_task(self.cog.resolve_vote(self))


# ─────────────────────────────────────────────────────
#  Ког Мафии
# ─────────────────────────────────────────────────────
class Mafia(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, MafiaGame] = {}

    def get_game(self, channel_id: int):
        return self.games.get(channel_id)

    def remove_game(self, channel_id: int) -> None:
        game = self.games.pop(channel_id, None)
        if game:
            game.cancel_timers()

    def cancel_game(self, channel_id: int) -> bool:
        game = self.get_game(channel_id)
        if game is None or game.phase in ("ended", "cancelled"):
            return False
        game.phase = "cancelled"
        self.remove_game(channel_id)
        return True

    def cog_unload(self):
        for channel_id in tuple(self.games):
            self.cancel_game(channel_id)

    def has_active_game(self, channel_id: int) -> bool:
        return channel_id in self.games

    async def _abort_game(self, game: MafiaGame, error: Exception) -> None:
        log.error(f"Сбой в фазе {game.phase} в канале {game.channel_id}: {error}")
        game.phase = "cancelled"
        # Finish cleanup even when the error occurred inside the current timer.
        game.cancel_timers()
        if self.get_game(game.channel_id) is game:
            self.remove_game(game.channel_id)
        try:
            await game.channel.send(
                "❌ Партия остановлена из-за ошибки Discord или базы данных. "
                "Создайте новое лобби; если ошибка повторяется, сообщите администратору."
            )
        except nextcord.HTTPException:
            log.warning("Не удалось сообщить об остановке игры в канале %s", game.channel_id)

    async def _send_phase(self, game: MafiaGame, *args, **kwargs) -> bool:
        try:
            await game.channel.send(*args, **kwargs)
        except nextcord.HTTPException as e:
            await self._abort_game(game, e)
            return False
        return self.get_game(game.channel_id) is game

    # ─── Запуск партии ───────────────────────────────
    async def start_game(self, interaction: Interaction, mode: str, players: list[int]) -> None:
        channel_id = interaction.channel_id
        if self.has_active_game(channel_id):
            return
        host_id = interaction.user.id
        guild_id = interaction.guild_id

        game = MafiaGame(
            mode=mode,
            guild_id=guild_id,
            channel_id=channel_id,
            host_id=host_id,
            players=players,
        )
        game.assign_roles()
        game.channel = interaction.channel
        game.cog = self

        self.games[channel_id] = game

        guild = interaction.guild
        failed_dm: list[int] = []

        try:
            for uid in players:
                member = guild.get_member(uid)
                username = member.display_name if member else f"User{uid % 10000}"
                await ensure_player(guild_id, uid, username)
        except Exception as e:
            await self._abort_game(game, e)
            return

        for uid in players:
            if self.get_game(channel_id) is not game:
                return
            role_key = game.role_of(uid)
            role = get_role(role_key)
            embed = nextcord.Embed(
                title=f"{role['emoji']} Ваша роль: {role['name']}",
                description=role["desc"],
                color=role["color"],
            )
            embed.set_footer(text=E.footer_text())

            if role_key == "mafia" and mode == "full":
                mates = [m for m in game.mafia_ids() if m != uid]
                if mates:
                    embed.add_field(
                        name="🎩 Ваши сообщники",
                        value="\n".join(f"• <@{m}>" for m in mates),
                        inline=False,
                    )
            try:
                user = guild.get_member(uid) or await self.bot.fetch_user(uid)
                await user.send(embed=embed)
            except nextcord.HTTPException:
                failed_dm.append(uid)

        game.day = 1
        if failed_dm:
            game.phase = "cancelled"
            self.remove_game(channel_id)
            await game.channel.send(
                "❌ Партия отменена: не удалось отправить роли "
                + " ".join(f"<@{uid}>" for uid in failed_dm)
                + ". Откройте ЛС и создайте новое лобби. Роли будут распределены заново."
            )
            return
        await self.start_night(game)

    # ─── НОЧЬ ────────────────────────────────────────
    async def start_night(self, game: MafiaGame, failed_dm: list[int] = None) -> None:
        if game.phase not in ("setup", "resolving_vote") or self.get_game(game.channel_id) is not game:
            return
        game.cancel_timers()
        game.phase = "night"
        game.mafia_votes.clear()
        game.doctor_target = None
        game.cop_checks.clear()
        game._night_finished = False
        game._night_tasks.clear()

        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"
        embed = E.night_announce_embed(game.day, len(game.alive), guild_name=guild_name)
        if not await self._send_phase(game, embed=embed):
            return

        if failed_dm:
            if not await self._send_phase(game,
                "⚠️ " + " ".join(f"<@{u}>" for u in failed_dm) +
                " — откройте ЛС от бота, иначе не сможете играть."
            ):
                return

        for uid in list(game.alive):
            if not game.accepts("night", game.day):
                return
            role = game.role_of(uid)
            try:
                user = game.channel.guild.get_member(uid) or await self.bot.fetch_user(uid)
            except Exception:
                continue

            if role == "mafia":
                mates = [f"<@{m}>" for m in game.mafia_ids() if m != uid and m in game.alive]
                targets = [f"<@{t}>" for t in game.alive if t != uid]
                embed = E.night_mafia_embed(game.day, targets, mates)
                view = NightActionView(game, uid, "kill")
                try:
                    await user.send(embed=embed, view=view)
                except nextcord.HTTPException as e:
                    await self._abort_game(game, e)
                    return

            elif role == "cop":
                embed = E.night_cop_embed(game.day)
                view = NightActionView(game, uid, "check")
                try:
                    await user.send(embed=embed, view=view)
                except nextcord.HTTPException as e:
                    await self._abort_game(game, e)
                    return

            elif role == "doctor":
                embed = E.night_doctor_embed(game.day)
                view = NightActionView(game, uid, "heal")
                try:
                    await user.send(embed=embed, view=view)
                except nextcord.HTTPException as e:
                    await self._abort_game(game, e)
                    return

        if not game.accepts("night", game.day):
            return
        task = asyncio.create_task(self._night_timer(game))
        game._night_tasks.append(task)

    async def _night_timer(self, game: MafiaGame) -> None:
        try:
            await asyncio.sleep(NIGHT_DURATION)
        except asyncio.CancelledError:
            return
        if game.accepts("night", game.day):
            game._night_finished = True
            await self.resolve_night(game)

    # ─── РАЗРЕШЕНИЕ НОЧИ ─────────────────────────────
    async def resolve_night(self, game: MafiaGame) -> None:
        if game.phase != "night" or self.get_game(game.channel_id) is not game:
            return
        game.phase = "resolving"

        victim_id = None
        if game.mafia_votes:
            votes_count = {}
            for target in game.mafia_votes.values():
                votes_count[target] = votes_count.get(target, 0) + 1
            victim_id = max(votes_count, key=votes_count.get)

        saved = victim_id is not None and game.doctor_target == victim_id

        victim_name = None
        if victim_id is not None and not saved and victim_id in game.alive:
            victim_name = game.short_name(victim_id)
            game.kill(victim_id, f"убит ночью {game.day}")

        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"
        morning = E.morning_embed(game.day, victim_name, saved, guild_name=guild_name)
        if not await self._send_phase(game, embed=morning):
            return

        winner = self.check_win(game)
        if winner:
            await self.end_game(game, winner)
            return

        await self.start_day(game)

    # ─── ДЕНЬ ────────────────────────────────────────
    async def start_day(self, game: MafiaGame) -> None:
        if game.phase != "resolving" or self.get_game(game.channel_id) is not game:
            return
        game.cancel_timers()
        game.phase = "day"
        game.votes.clear()
        game._day_finished = False
        game._day_tasks.clear()

        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"
        alive_mentions = [game.mention(uid) for uid in game.alive]
        dead_log = game.dead_log_formatted()
        embed = E.day_embed(game.day, alive_mentions, dead_log, guild_name=guild_name)
        view = DayView(game)
        if not await self._send_phase(game, embed=embed, view=view):
            return

        if not game.accepts("day", game.day):
            return
        task = asyncio.create_task(self._day_timer(game))
        game._day_tasks.append(task)

    async def _day_timer(self, game: MafiaGame) -> None:
        try:
            await asyncio.sleep(DAY_DURATION)
        except asyncio.CancelledError:
            return
        if game.accepts("day", game.day):
            game._day_finished = True
            await self.start_vote(game)

    # ─── ГОЛОСОВАНИЕ ─────────────────────────────────
    async def start_vote(self, game: MafiaGame) -> None:
        if game.phase != "day" or self.get_game(game.channel_id) is not game:
            return
        game.cancel_timers()
        game.phase = "vote"
        game.votes.clear()
        game._vote_finished = False
        game._vote_tasks.clear()

        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"
        embed = E.vote_embed(game.day, len(game.alive), guild_name=guild_name)
        view = VoteView(game)
        if not await self._send_phase(game, embed=embed, view=view):
            return

        if not game.accepts("vote", game.day):
            return
        task = asyncio.create_task(self._vote_timer(game))
        game._vote_tasks.append(task)

    async def _vote_timer(self, game: MafiaGame) -> None:
        try:
            await asyncio.sleep(VOTE_DURATION)
        except asyncio.CancelledError:
            return
        if game.accepts("vote", game.day):
            game._vote_finished = True
            await self.resolve_vote(game)

    # ─── РАЗРЕШЕНИЕ ГОЛОСОВАНИЯ ──────────────────────
    async def resolve_vote(self, game: MafiaGame) -> None:
        if game.phase != "vote" or self.get_game(game.channel_id) is not game:
            return
        game.phase = "resolving_vote"
        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"

        real_votes: dict[int, int] = {}
        for voter, target in game.votes.items():
            if target == -1:
                continue
            real_votes[target] = real_votes.get(target, 0) + 1

        results = {game.short_name(uid): c for uid, c in real_votes.items()}

        if not real_votes:
            if not await self._send_phase(game,
                embed=E.vote_result_no_execution_embed(
                    game.day, None,
                    "🗳️ Никто не голосовал. Казни не будет.",
                    guild_name=guild_name,
                )
            ):
                return
            await self._next_night(game)
            return

        max_votes = max(real_votes.values())
        leaders = [uid for uid, c in real_votes.items() if c == max_votes]

        if len(leaders) > 1:
            if not await self._send_phase(game,
                embed=E.vote_result_no_execution_embed(
                    game.day, results,
                    "🗳️ Голоса разделились. Казни не будет — город в смятении.",
                    guild_name=guild_name,
                )
            ):
                return
            await self._next_night(game)
            return

        victim_id = leaders[0]
        victim_name = game.short_name(victim_id)
        victim_role = game.role_of(victim_id)

        game.kill(victim_id, f"казнён днём {game.day}")
        flavor = random.choice(EXECUTION_FLAVORS)

        if not await self._send_phase(game,
            embed=E.vote_result_execution_embed(
                game.day, results, victim_name, victim_role, flavor,
                guild_name=guild_name,
            )
        ):
            return

        winner = self.check_win(game)
        if winner:
            await self.end_game(game, winner)
            return

        await self._next_night(game)

    async def _next_night(self, game: MafiaGame) -> None:
        if game.phase != "resolving_vote" or self.get_game(game.channel_id) is not game:
            return
        game.day += 1
        await self.start_night(game)

    # ─── Победа ──────────────────────────────────────
    def check_win(self, game: MafiaGame) -> str | None:
        mafia_alive = [u for u in game.alive if game.role_of(u) == "mafia"]
        civ_alive = [u for u in game.alive if game.role_of(u) != "mafia"]

        if not mafia_alive:
            return "civilians"
        if len(mafia_alive) >= len(civ_alive):
            return "mafia"
        return None

    async def end_game(self, game: MafiaGame, winner: str) -> None:
        if game.phase in ("ended", "cancelled") or self.get_game(game.channel_id) is not game:
            return
        game.cancel_timers()
        game.phase = "ended"
        game.finished_at = time.time()
        duration_sec = int(game.finished_at - game.created_at)

        guild_name = game.channel.guild.name if game.channel.guild else "Lounge"

        title = "🎩 Победа МАФИИ!" if winner == "mafia" else "👤 Победа МИРНЫХ!"
        color = E.DARK_RED if winner == "mafia" else E.GREEN

        mafia_side = set(game.mafia_ids())
        winners = mafia_side if winner == "mafia" else (set(game.players) - mafia_side)

        lines = []
        for uid in game.players:
            role_key = game.role_of(uid)
            role = get_role(role_key)
            status = "💀" if uid in game.dead else "✅"
            win_mark = "🏆" if uid in winners else "  "
            lines.append(f"{status} {win_mark} <@{uid}> — {role['emoji']} {role['name']}")

        roster = {str(uid): game.role_of(uid) for uid in game.players}
        roster_json = json.dumps(roster, ensure_ascii=False)
        winner_id = next(iter(winners)) if winners else None

        results_saved = True
        try:
            await record_game_result(
                game_id=game.game_id,
                guild_id=game.guild_id,
                game_type=f"mafia_{game.mode}",
                channel_id=game.channel_id,
                host_id=game.host_id,
                players_json=roster_json,
                winner_id=winner_id,
                duration_sec=duration_sec,
                rewards=[(uid, uid in winners, CHIPS_WIN if uid in winners else CHIPS_LOSE)
                         for uid in game.players],
            )
        except Exception:
            log.exception("Не удалось сохранить результаты игры %s", game.game_id)
            results_saved = False

        mins = duration_sec // 60
        secs = duration_sec % 60
        duration_str = f"{mins} мин {secs} сек" if mins > 0 else f"{secs} сек"

        embed = nextcord.Embed(
            title=title,
            description=(
                f"🏆 **Победившая сторона: {'Мафия' if winner == 'mafia' else 'Мирные жители'}.**\n"
                "Победа засчитывается всей стороне, включая выбывших участников.\n\n"
                + "\n".join(lines)
            ),
            color=color,
        )
        embed.add_field(name="⏱ Длительность", value=duration_str, inline=True)
        embed.add_field(
            name="🪙 Награда",
            value=(f"+{CHIPS_WIN} победителям\n+{CHIPS_LOSE} проигравшим"
                   if results_saved else "Ошибка сохранения: не удалось подтвердить запись результатов и наград."),
            inline=True,
        )
        embed.set_footer(text=E.footer_text(guild_name))

        try:
            await self._send_phase(game, embed=embed)
        finally:
            if self.get_game(game.channel_id) is game:
                self.remove_game(game.channel_id)


def setup(bot: commands.Bot):
    bot.add_cog(Mafia(bot))
