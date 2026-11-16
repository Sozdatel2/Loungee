import random
import nextcord
from nextcord.ext import commands
from nextcord import SlashOption
from database import db

class Casino(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.GOLD = 0xC5A028
        self.SYMBOLS = ["🍒", "🍋", "🔔", "💎", "7️⃣"]

    @nextcord.slash_command(name="slots", description="Крутить барабаны (Слоты)")
    async def slots(
        self,
        interaction: nextcord.Interaction,
        bet: int = SlashOption(
            description="Сколько фишек поставить", default=10, min_value=1
        )
    ):
        guild_id = interaction.guild_id
        user_id = interaction.user.id

        player = await db.get_player(guild_id, user_id)

        if player is None:
            embed = nextcord.Embed(
                title="♠ Казино джентльменов",
                description="Прошу прощения, сэр, но вы пока не зарегистрированы за нашим столом.",
                color=self.GOLD
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        username, games_played, games_won, chips = player

        if chips < bet:
            await interaction.response.send_message(
                "🎩 Недостаточно фишек, сэр. Фортуна требует вложений.", ephemeral=True
            )
            return

        reels = [random.choice(self.SYMBOLS) for _ in range(3)]

        if reels[0] == reels[1] == reels[2]:
            multiplier = 10
            result_title = "🏆 ДЖЕКПОТ! Фортуна улыбнулась вам!"
            result_description = "Три одинаковых символа! Изумительный ход, сэр."
            won = True
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            multiplier = 2
            result_title = "🥂 Изящная победа!"
            result_description = "Два совпадения! Дом снимает шляпу перед вами."
            won = True
        else:
            multiplier = 0
            result_title = "🎩 Дом выигрывает"
            result_description = "Совпадений нет. Фортуна сегодня не в вашу пользу."
            won = False

        if won:
            winnings = bet * multiplier
            await db.add_chips(guild_id, user_id, winnings)
            net_result = winnings
        else:
            winnings = 0
            await db.add_chips(guild_id, user_id, -bet)
            net_result = -bet

        new_balance = chips + net_result

        slot_display = (
            f"╔══════════════════════╗\n"
            f"     [ {' | '.join(reels)} ]\n"
            f"╚══════════════════════╝"
        )

        embed = nextcord.Embed(
            title="♠ Джентельменское казино ♠",
            description=(
                "```ansi\n"
                "\u001b[33m"
                "      ✦ КОРОЛЕВСКИЙ СЛОТ ✦\n"
                "\u001b[0m"
                "```\n"
                f"**{interaction.user.mention}**, ваши барабаны остановились...\n\n"
                f"```{slot_display}```\n"
                f"**{result_title}**\n"
                f"{result_description}"
            ),
            color=self.GOLD
        )

        embed.add_field(name="🎲 Ваша ставка", value=f"`{bet:,}` фишек", inline=True)
        embed.add_field(name="💰 Множитель", value=f"`{multiplier}x`", inline=True)
        embed.add_field(
            name="😎 Ваш выигрыш",
            value=(f"`+{winnings:,}` фишек" if won else f"`-{bet:,}` фишек"),
            inline=True
        )
        embed.add_field(name="💳 Ваш баланс", value=f"**{new_balance:,}** фишек", inline=False)

        embed.set_footer(text="Lounge Casino • Фортуна любит смелых.")
        await interaction.response.send_message(embed=embed)

def setup(bot: commands.Bot):
    bot.add_cog(Casino(bot))