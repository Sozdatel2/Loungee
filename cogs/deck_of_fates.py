import random
import nextcord
from nextcord.ext import commands
from nextcord import SlashOption
from utils.deck_data import CARDS

class FatesGame:
    def __init__(self, player1_id, player2_id):
        self.players = [player1_id, player2_id]

        self.boards = {
            player1_id: {
                "past": [],
                "present": [],
                "future": []
            },
            player2_id: {
                "past": [],
                "present": [],
                "future": []
            }
        }

        self.hands = {
            player1_id: [],
            player2_id: []
        }

        self.deck = list(CARDS.values())
        self.turn = player1_id

    def deal_cards(self):
        """Shuffles the deck and deals 5 cards to each player."""
        self.deck = list(CARDS.values())
        random.shuffle(self.deck)

        self.hands[self.players[0]] = self.deck[:5]
        self.hands[self.players[1]] = self.deck[5:10]

        self.deck = self.deck[10:]

    def play_card(self, player_id, card_id, row) -> bool:
        """Plays a card and passes the turn."""
        if player_id != self.turn:
            return False

        if player_id not in self.hands:
            return False

        if row not in ("past", "present", "future"):
            return False

        card = None
        for current_card in self.hands[player_id]:
            if current_card["id"] == card_id:
                card = current_card
                break

        if card is None:
            return False

        self.hands[player_id].remove(card)
        self.boards[player_id][row].append(card)

        if player_id == self.players[0]:
            self.turn = self.players[1]
        else:
            self.turn = self.players[0]

        return True

    def calculate_score(self, player_id) -> int:
        """Calculates the player's total score."""
        if player_id not in self.boards:
            return 0

        score = 0
        board = self.boards[player_id]

        # Past: only the max power card counts
        if board["past"]:
            score += max(card["power"] for card in board["past"])

        # Present: sum of all cards
        score += sum(card["power"] for card in board["present"])

        # Future: sum of all cards
        score += sum(card["power"] for card in board["future"])

        return score

class RowSelect(nextcord.ui.Select):
    def __init__(self, view, player, card_id):
        self.view = view
        self.player = player
        self.card_id = card_id

        options = [
            nextcord.SelectOption(label="Прошлое", value="past", emoji="⏳"),
            nextcord.SelectOption(label="Настоящее", value="present", emoji="⚔️"),
            nextcord.SelectOption(label="Будущее", value="future", emoji="🔮")
        ]

        super().__init__(
            placeholder="Выбери ряд для карты...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.player:
            await interaction.response.send_message("Это не твой ход, сэр.", ephemeral=True)
            return

        row = self.values[0]
        success = self.view.cog.game_play_card(self.view.game, self.player, self.card_id, row)

        if not success:
            await interaction.response.edit_message(content="❌ Не удалось разыграть эту карту, сэр.", view=None)
            return

        await interaction.response.edit_message(content="✅ Карта успешно разыграна, сэр.", view=None)
        await self.view.cog.update_game(self.view.game)

class CardSelect(nextcord.ui.Select):
    def __init__(self, view, player):
        self.view = view
        self.player = player
        hand = view.game.hands[player]

        options = [
            nextcord.SelectOption(
                label=f"{card['name']} ({card['power']})",
                value=card["id"],
                description=f"Сила карты: {card['power']}"
            )
            for card in hand
        ]

        super().__init__(
            placeholder="Выбери карту из своей руки...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.player:
            await interaction.response.send_message("Это не твоя рука, сэр.", ephemeral=True)
            return

        card_id = self.values[0]
        row_view = RowSelectView(self.view.cog, self.view.game, self.player, card_id)

        await interaction.response.edit_message(
            content="🎴 Теперь выбери, куда отправить карту:",
            view=row_view
        )

class PassButton(nextcord.ui.Button):
    def __init__(self, view):
        self.view = view
        super().__init__(label="Пас", emoji="⏭️", style=nextcord.ButtonStyle.secondary)

    async def callback(self, interaction: nextcord.Interaction):
        game = self.view.game
        player = interaction.user.id

        if player != game.turn:
            await interaction.response.send_message("Сейчас не твой ход, сэр.", ephemeral=True)
            return

        if player not in game.players:
            await interaction.response.send_message("Ты не участвуешь в этой партии.", ephemeral=True)
            return

        if player == game.players[0]:
            game.turn = game.players[1]
        else:
            game.turn = game.players[0]

        await interaction.response.edit_message(content="⏭️ Ты пропустил ход, сэр.", view=None)
        await self.view.cog.update_game(game)

class RowSelectView(nextcord.ui.View):
    def __init__(self, cog, game, player, card_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.game = game
        self.player = player
        self.add_item(RowSelect(self, player, card_id))
        self.add_item(PassButton(self))

class TurnView(nextcord.ui.View):
    def __init__(self, cog, game):
        super().__init__(timeout=None)
        self.cog = cog
        self.game = game

    @nextcord.ui.button(label="Сделать ход", emoji="🎴", style=nextcord.ButtonStyle.primary)
    async def make_move(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        player = interaction.user.id

        if player != self.game.turn:
            await interaction.response.send_message("Сейчас очередь другого игрока, сэр.", ephemeral=True)
            return

        if player not in self.game.players:
            await interaction.response.send_message("Вы не участвуете в этой партии.", ephemeral=True)
            return

        hand = self.game.hands[player]

        if not hand:
            await interaction.response.send_message("У тебя больше нет карт, сэр.", ephemeral=True)
            return

        menu = CardSelectView(self.cog, self.game, player)
        await interaction.response.send_message("🎴 Твой ход, сэр. Выбери карту:", view=menu, ephemeral=True)

class CardSelectView(nextcord.ui.View):
    def __init__(self, cog, game, player):
        super().__init__(timeout=180)
        self.cog = cog
        self.game = game
        self.player = player
        self.add_item(CardSelect(self, player))
        self.add_item(PassButton(self))

class DeckOfFates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.GOLD = 0xC5A028
        self.games = {} # {player1_id: message, player2_id: message}

    def game_play_card(self, game, player, card_id, row):
        """Helper to call the game's play_card method."""
        return game.play_card(player, card_id, row)

    def create_embed(self, game):
        embed = nextcord.Embed(
            title="🔮 DECK OF FATES",
            description="Добро пожаловать на поле судьбы, господа.\nКаждая карта приближает вас к победе.",
            color=self.GOLD
        )

        for i, player in enumerate(game.players, start=1):
            board = game.boards[player]
            rows_text = []
            row_names = {"past": "Past", "present": "Present", "future": "Future"}

            for row, name in row_names.items():
                cards = board[row]
                if cards:
                    card_list = ", ".join(f"{c['name']} ({c['power']})" for c in cards)
                else:
                    card_list = "Пусто"
                rows_text.append(f"**{name}:** {card_list}")

            score = game.calculate_score(player)
            embed.add_field(
                name=f"👤 Игрок {i}: <@{player}>",
                value="\n".join(rows_text) + f"\n\n**Очки:** `{score}`\n**Карт в руке:** `{len(game.hands[player])}`",
                inline=False
            )

        embed.add_field(name="🎴 Очередь хода", value=f"Сейчас ходит: <@{game.turn}>", inline=False)
        embed.set_footer(text="Deck of Fates • Судьба любит смелых")
        return embed

    async def update_game(self, game):
        message = self.games.get(game.players[0])
        if message is None:
            return

        if all(len(game.hands[p]) == 0 for p in game.players):
            await self.end_game(game, message)
            return

        embed = self.create_embed(game)
        await message.edit(embed=embed, view=TurnView(self, game))

    async def end_game(self, game, message):
        p1, p2 = game.players
        s1 = game.calculate_score(p1)
        s2 = game.calculate_score(p2)

        if s1 > s2:
            result = f"🏆 Победитель: <@{p1}>!"
        elif s2 > s1:
            result = f"🏆 Победитель: <@{p2}>!"
        else:
            result = "🤝 Ничья! Судьба не выбрала фаворита."

        embed = nextcord.Embed(
            title="👑 ИГРА ЗАВЕРШЕНА",
            description=f"{result}\n\n**<@{p1}>:** `{s1}` очков\n**<@{p2}>:** `{s2}` очков\n\nКарты раскрыты. Судьба вынесла свой вердикт.",
            color=self.GOLD
        )
        embed.set_footer(text="Deck of Fates • До следующей встречи, господа.")

        await message.edit(embed=embed, view=None)
        self.games.pop(p1, None)
        self.games.pop(p2, None)

    @nextcord.slash_command(name="deck-start", description="Начать партию в Колоду Судьбы")
    async def deck_start(self, interaction: nextcord.Interaction, opponent: nextcord.Member = SlashOption(description="Игрок, с которым ты хочешь сыграть")):
        p1 = interaction.user.id
        p2 = opponent.id

        if p1 == p2:
            await interaction.response.send_message("Нельзя играть самому с собой, сэр.", ephemeral=True)
            return
        if opponent.bot:
            await interaction.response.send_message("Боты не умеют распоряжаться судьбой, сэр.", ephemeral=True)
            return
        if p1 in self.games or p2 in self.games:
            await interaction.response.send_message("Один из игроков уже участвует в другой партии.", ephemeral=True)
            return

        game = FatesGame(p1, p2)
        game.deal_cards()

        embed = self.create_embed(game)
        await interaction.response.send_message(embed=embed, view=TurnView(self, game))
        
        message = await interaction.original_message()
        self.games[p1] = message
        self.games[p2] = message

        await interaction.followup.send("🎴 Твой ход, сэр. Выбери карту:", view=CardSelectView(self, game, p1), ephemeral=True)

def setup(bot):
    bot.add_cog(DeckOfFates(bot))