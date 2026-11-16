
import random
import asyncio

import nextcord
from nextcord.ext import commands
from nextcord import SlashOption

from utils.deck_data import CARDS


class FatesGame:
    def __init__(self, player1_id, player2_id):
        self.players = [player1_id, player2_id]

        self.boards = {
            player1_id: {"past": [], "present": [], "future": []},
            player2_id: {"past": [], "present": [], "future": []}
        }

        self.hands = {
            player1_id: [],
            player2_id: []
        }

        self.deck = list(CARDS.values())
        self.turn = player1_id

    def deal_cards(self):
        self.deck = list(CARDS.values())
        random.shuffle(self.deck)

        self.hands[self.players[0]] = self.deck[:5]
        self.hands[self.players[1]] = self.deck[5:10]

        self.deck = self.deck[10:]

    def play_card(self, player_id, card_id, row) -> bool:
        if player_id != self.turn or player_id not in self.hands:
            return False

        if row not in ("past", "present", "future"):
            return False

        карта = next(
            (
                текущая_карта
                for текущая_карта in self.hands[player_id]
                if текущая_карта["id"] == card_id
            ),
            None
        )

        if карта is None:
            return False

        self.hands[player_id].remove(карта)
        self.boards[player_id][row].append(карта)

        return True

    def calculate_score(self, player_id) -> int:
        if player_id not in self.boards:
            return 0

        доска = self.boards[player_id]
        очки = 0

        if доска["past"]:
            очки += max(
                карта["power"]
                for карта in доска["past"]
            )

        очки += sum(
            карта["power"]
            for карта in доска["present"]
        )

        очки += sum(
            карта["power"]
            for карта in доска["future"]
        )

        return очки


class RowSelect(nextcord.ui.Select):
    def __init__(self, parent, player, card_id):
        self.parent = parent
        self.player = player
        self.card_id = card_id

        варианты = [
            nextcord.SelectOption(
                label="Прошлое",
                value="past",
                emoji="⏳"
            ),
            nextcord.SelectOption(
                label="Настоящее",
                value="present",
                emoji="⚔️"
            ),
            nextcord.SelectOption(
                label="Будущее",
                value="future",
                emoji="🔮"
            )
        ]

        super().__init__(
            custom_id=f"row_select_{card_id}_{player}",  # ДОБАВИТЬ
            placeholder="Выбери ряд для карты...",
            options=варианты,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: nextcord.Interaction):
        game = self.parent.game
        player = interaction.user.id

        if player != self.player:
            await interaction.response.send_message(
                "Это не твой ход, сэр.",
                ephemeral=True
            )
            return

        if game.turn != player:
            await interaction.response.edit_message(
                content="❌ Время твоего хода истекло, сэр.",
                view=None
            )
            return

        if not any(
            карта["id"] == self.card_id
            for карта in game.hands[player]
        ):
            await interaction.response.edit_message(
                content="❌ Эта карта больше недоступна.",
                view=None
            )
            return

        ряд = self.values[0]

        успех = game.play_card(
            player,
            self.card_id,
            ряд
        )

        if not успех:
            await interaction.response.edit_message(
                content="❌ Не удалось разыграть эту карту, сэр.",
                view=None
            )
            return

        self.parent.cog.передать_ход(game, player)

        await interaction.response.edit_message(
            content="✅ Карта успешно разыграна, сэр.",
            view=None
        )

        await self.parent.cog.update_game(game)


class CardSelect(nextcord.ui.Select):
    def __init__(self, parent, player):
        self.parent = parent
        self.player = player

        рука = parent.game.hands[player]

        варианты = [
            nextcord.SelectOption(
                label=f"{карта['name']} ({карта['power']})",
                value=карта["id"],
                description=f"Сила карты: {карта['power']}"
            )
            for карта in рука
        ]

        super().__init__(
            custom_id=f"card_select_{player}_{len(рука)}",  # ДОБАВИТЬ
            placeholder="Выбери карту из своей руки...",
            options=варианты,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: nextcord.Interaction):
        game = self.parent.game

        if interaction.user.id != self.player:
            await interaction.response.send_message(
                "Это не твоя рука, сэр.",
                ephemeral=True
            )
            return

        if game.turn != self.player:
            await interaction.response.edit_message(
                content="❌ Сейчас уже не твой ход, сэр.",
                view=None
            )
            return

        card_id = self.values[0]

        if not any(
            карта["id"] == card_id
            for карта in game.hands[self.player]
        ):
            await interaction.response.edit_message(
                content="❌ Эта карта больше недоступна.",
                view=None
            )
            return

        row_view = RowSelectView(
            self.parent.cog,
            game,
            self.player,
            card_id
        )

        await interaction.response.edit_message(
            content="🎴 Теперь выбери, куда отправить карту:",
            view=row_view
        )


class PassButton(nextcord.ui.Button):
    def __init__(self, parent):
        self.parent = parent

        super().__init__(
            label="Пас",
            emoji="⏭️",
            style=nextcord.ButtonStyle.secondary,
            custom_id="pass_turn_btn"  # ДОБАВИТЬ
        )

    async def callback(self, interaction: nextcord.Interaction):
        game = self.parent.game
        player = interaction.user.id

        if player not in game.players:
            await interaction.response.send_message(
                "Ты не участвуешь в этой партии.",
                ephemeral=True
            )
            return

        if player != game.turn:
            await interaction.response.send_message(
                "Сейчас не твой ход, сэр.",
                ephemeral=True
            )
            return

        self.parent.cog.передать_ход(game, player)

        await interaction.response.edit_message(
            content="⏭️ Ты пропустил ход, сэр.",
            view=None
        )

        await self.parent.cog.update_game(game)


class RowSelectView(nextcord.ui.View):
    def __init__(self, cog, game, player, card_id):
        super().__init__(timeout=180)

        self.cog = cog
        self.game = game
        self.player = player

        self.add_item(
            RowSelect(self, player, card_id)
        )

        self.add_item(
            PassButton(self)
        )


class CardSelectView(nextcord.ui.View):
    def __init__(self, cog, game, player):
        super().__init__(timeout=180)

        self.cog = cog
        self.game = game
        self.player = player

        self.add_item(
            CardSelect(self, player)
        )

        self.add_item(
            PassButton(self)
        )


class TurnView(nextcord.ui.View):
    def __init__(self, cog, game):
        super().__init__(timeout=None)

        self.cog = cog
        self.game = game

    @nextcord.ui.button(
        label="Сделать ход",
        emoji="🎴",
        style=nextcord.ButtonStyle.primary
    )
    async def make_move(
        self,
        button: nextcord.ui.Button,
        interaction: nextcord.Interaction
    ):
        player = interaction.user.id

        if player not in self.game.players:
            await interaction.response.send_message(
                "Вы не участвуете в этой партии.",
                ephemeral=True
            )
            return

        if player != self.game.turn:
            await interaction.response.send_message(
                "Сейчас очередь другого игрока, сэр.",
                ephemeral=True
            )
            return

        if not self.game.hands[player]:
            await interaction.response.send_message(
                "У тебя больше нет карт, сэр.",
                ephemeral=True
            )
            return

        menu = CardSelectView(
            self.cog,
            self.game,
            player
        )

        await interaction.response.send_message(
            "🎴 Твой ход, сэр. Выбери карту:",
            view=menu,
            ephemeral=True
        )


class DeckOfFates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.GOLD = 0xC5A028

        self.games = {}
        self.game_locks = {}

    def передать_ход(self, game, player):
        другой_игрок = (
            game.players[1]
            if player == game.players[0]
            else game.players[0]
        )

        if game.hands[другой_игрок]:
            game.turn = другой_игрок
        elif game.hands[player]:
            game.turn = player
        else:
            game.turn = другой_игрок

    def create_embed(self, game):
        embed = nextcord.Embed(
            title="🔮 DECK OF FATES",
            description=(
                "Добро пожаловать на поле судьбы, господа.\n"
                "Каждая карта приближает вас к победе."
            ),
            color=self.GOLD
        )

        названия_рядов = {
            "past": "Прошлое",
            "present": "Настоящее",
            "future": "Будущее"
        }

        for i, player in enumerate(game.players, start=1):
            доска = game.boards[player]
            строки = []

            for ряд, название in названия_рядов.items():
                карты = доска[ряд]

                список = (
                    ", ".join(
                        f"{карта['name']} ({карта['power']})"
                        for карта in карты
                    )
                    if карты else "Пусто"
                )

                строки.append(f"**{название}:** {список}")

            очки = game.calculate_score(player)

            embed.add_field(
                name=f"👤 Игрок {i}: <@{player}>",
                value=(
                    "\n".join(строки)
                    + f"\n\n**Очки:** `{очки}`"
                    + f"\n**Карт в руке:** `{len(game.hands[player])}`"
                ),
                inline=False
            )

        embed.add_field(
            name="🎴 Очередь хода",
            value=f"Сейчас ходит: <@{game.turn}>",
            inline=False
        )

        embed.set_footer(
            text="Deck of Fates • Судьба любит смелых"
        )

        return embed

    async def update_game(self, game):
        сообщение = self.games.get(game.players[0])

        if сообщение is None:
            return

        if all(
            not game.hands[игрок]
            for игрок in game.players
        ):
            await self.end_game(game, сообщение)
            return

        await сообщение.edit(
            embed=self.create_embed(game),
            view=TurnView(self, game)
        )

    async def end_game(self, game, message):
        p1, p2 = game.players

        s1 = game.calculate_score(p1)
        s2 = game.calculate_score(p2)

        if s1 > s2:
            результат = f"🏆 Победитель: <@{p1}>!"
        elif s2 > s1:
            результат = f"🏆 Победитель: <@{p2}>!"
        else:
            результат = "🤝 Ничья! Судьба не выбрала фаворита."

        embed = nextcord.Embed(
            title="👑 ИГРА ЗАВЕРШЕНА",
            description=(
                f"{результат}\n\n"
                f"**<@{p1}>:** `{s1}` очков\n"
                f"**<@{p2}>:** `{s2}` очков\n\n"
                "Карты раскрыты. Судьба вынесла свой вердикт."
            ),
            color=self.GOLD
        )

        embed.set_footer(
            text="Deck of Fates • До следующей встречи, господа."
        )

        await message.edit(
            embed=embed,
            view=None
        )

        self.games.pop(p1, None)
        self.games.pop(p2, None)

        self.game_locks.pop(p1, None)
        self.game_locks.pop(p2, None)

    @nextcord.slash_command(
        name="deck-start",
        description="Начать партию в Колоду Судьбы"
    )
    async def deck_start(
        self,
        interaction: nextcord.Interaction,
        opponent: nextcord.Member = SlashOption(
            description="Игрок, с которым ты хочешь сыграть"
        )
    ):
        p1 = interaction.user.id
        p2 = opponent.id

        if p1 == p2 or opponent.bot:
            await interaction.response.send_message(
                "Нельзя играть с самим собой или ботом, сэр.",
                ephemeral=True
            )
            return

        if p1 in self.games or p2 in self.games:
            await interaction.response.send_message(
                "Один из игроков уже участвует в другой партии, сэр.",
                ephemeral=True
            )
            return

        game = FatesGame(p1, p2)
        game.deal_cards()

        self.game_locks[p1] = asyncio.Lock()
        self.game_locks[p2] = self.game_locks[p1]

        embed = self.create_embed(game)

        await interaction.response.send_message(
            embed=embed,
            view=TurnView(self, game)
        )

        message = await interaction.original_message()

        self.games[p1] = message
        self.games[p2] = message

        await interaction.followup.send(
            "🎴 Твой ход, сэр. Выбери карту:",
            view=CardSelectView(self, game, p1),
            ephemeral=True
        )


def setup(bot):
    bot.add_cog(DeckOfFates(bot))
