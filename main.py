import os
import logging
import traceback
import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from dotenv import load_dotenv
from database.db import init_db
from utils.embeds import footer_text

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Lounge")

class Lounge(commands.Bot):
    def __init__(self):
        intents = nextcord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="l.", intents=intents, help_command=None)

bot = Lounge()

_initialized = False

@bot.event
async def on_ready():
    global _initialized

    log.info(f"🎩 Lounge на месте. Вошёл как {bot.user}")
    log.info(f"   ID: {bot.user.id}")
    log.info(f"   Серверов: {len(bot.guilds)}")
    for g in bot.guilds:
        log.info(f"   • {g.name} ({g.id})")

    if not _initialized:
        _initialized = True

        try:
            await init_db()
            log.info("🗄️  База данных инициализирована")
        except Exception as e:
            log.error(f"❌ Ошибка БД: {type(e).__name__}: {e}")
            traceback.print_exc()

        for cog in ["cogs.lobby", "cogs.games", "cogs.mafia"]:
            try:
                bot.load_extension(cog)
                log.info(f"✅ Загружен ког: {cog}")
            except Exception as e:
                log.error(f"❌ Ког {cog} НЕ загружен: {type(e).__name__}: {e}")
                traceback.print_exc()

        try:
            await bot.sync_application_commands()
            log.info("🔄 Слэш-команды синкнуты глобально")
        except Exception as e:
            log.error(f"❌ Ошибка синка: {type(e).__name__}: {e}")
            traceback.print_exc()

    await bot.change_presence(
        activity=nextcord.Activity(
            type=nextcord.ActivityType.watching,
            name="Good Games Only 🎲"
        )
    )

@bot.event
async def on_guild_join(guild: nextcord.Guild):
    """При добавлении на новый сервер — приветствие и логирование."""
    log.info(f"➕ Бот добавлен на сервер: {guild.name} ({guild.id})")

    target = guild.system_channel
    if target and target.permissions_for(guild.me).send_messages:
        embed = nextcord.Embed(
            title="🎩 Lounge прибыл",
            description=(
                "*Good Games Only.*\n\n"
                "Ваш вечерний распорядитель для настолок.\n"
                "Попробуйте `/lounge` — там всё."
            ),
            color=0xC5A028,
        )
        embed.set_footer(text=footer_text(guild.name))
        try:
            await target.send(embed=embed)
        except Exception as e:
            log.warning(f"Не смог написать приветствие на {guild.name}: {e}")

@bot.slash_command(name="ping", description="Проверка связи с Lounge")
async def ping(interaction: Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(
        f"🎩 К вашим услугам, сэр. Пинг: `{latency}ms`"
    )

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ DISCORD_TOKEN не найден в .env")
    bot.run(TOKEN)