import os
import logging
import asyncio
import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from dotenv import load_dotenv
from database.db import init_db
from utils.embeds import footer_text
from utils.prefix import register_prefix, PrefixInteraction
from utils.cooldowns import UserCooldown

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
        super().__init__(command_prefix=("LL.", "ll."), intents=intents, help_command=None)
        self.command_cooldown = UserCooldown()
        self.add_application_command_check(self._slash_cooldown)
        self.add_check(self._prefix_cooldown)

    async def _slash_cooldown(self, interaction):
        return await self.command_cooldown.allow(interaction)

    async def _prefix_cooldown(self, ctx):
        if getattr(ctx.command, "_slash_source", None) is not None:
            return True  # The common slash check charges bridged commands exactly once.
        return await self.command_cooldown.allow(PrefixInteraction(ctx))

    def add_application_command(self, command, **kwargs):
        super().add_application_command(command, **kwargs)
        if hasattr(self, "all_commands"):
            register_prefix(self, command)

    def remove_cog(self, name):
        cog = self.get_cog(name)
        if cog is None:
            return super().remove_cog(name)
        for command in list(self.commands):
            source = getattr(command, "_slash_source", None)
            if source is not None and source.parent_cog is cog:
                self.remove_command(command.name)
        return super().remove_cog(name)


bot = Lounge()

_initialized = False
_initialization_lock = asyncio.Lock()


async def initialize_bot():
    global _initialized
    async with _initialization_lock:
        if _initialized:
            return
        await init_db()
        log.info("🗄️ База данных инициализирована")
        for extension in ("cogs.lobby", "cogs.games", "cogs.mafia", "cogs.developer"):
            if extension not in bot.extensions:
                bot.load_extension(extension)
                log.info("✅ Загружен модуль: %s", extension)
        await bot.sync_application_commands()
        _initialized = True
        log.info("🔄 Инициализация и синхронизация команд завершены")


@bot.application_command_check
async def require_initialization(interaction: Interaction):
    if not _initialized:
        await interaction.response.send_message(
            "🎩 Lounge ещё готовится к приёму гостей. Попробуйте чуть позже, сэр.",
            ephemeral=True,
        )
        return False
    return True


@bot.check
async def prefix_ready(ctx):
    if not _initialized:
        ctx._lounge_response_sent = True
        await ctx.send("🎩 Lounge ещё готовится к приёму гостей. Попробуйте чуть позже, сэр.")
        return False
    return True


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.NotOwner):
        await ctx.send("Эта команда доступна только создателю бота, сэр.")
    elif isinstance(error, commands.UserInputError):
        await ctx.send(f"Не удалось разобрать аргументы. Посмотрите L.help, сэр. {str(error)[:300]}",
                       allowed_mentions=nextcord.AllowedMentions.none())
    elif isinstance(error, commands.CheckFailure):
        if not getattr(ctx, "_lounge_response_sent", False):
            await ctx.send("Эта команда сейчас недоступна или у вас нет прав, сэр.")
    else:
        log.error("Ошибка префиксной команды %s", ctx.command, exc_info=(type(error), error, error.__traceback__))
        await ctx.send("Не удалось выполнить команду, сэр. Попробуйте позже.")


@bot.event
async def on_application_command_error(interaction, error):
    if isinstance(error, nextcord.ApplicationCheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Эта команда сейчас недоступна или у вас нет прав, сэр.", ephemeral=True)
        return
    original = getattr(error, "original", error)
    log.error("Ошибка slash-команды", exc_info=(type(original), original, original.__traceback__))
    if not interaction.response.is_done():
        await interaction.response.send_message("Не удалось выполнить команду, сэр. Попробуйте позже.", ephemeral=True)


@bot.event
async def on_ready():

    log.info(f"🎩 Lounge на месте. Вошёл как {bot.user}")
    log.info(f"   ID: {bot.user.id}")
    log.info(f"   Серверов: {len(bot.guilds)}")
    for g in bot.guilds:
        log.info(f"   • {g.name} ({g.id})")

    try:
        await initialize_bot()
    except Exception:
        log.exception("❌ Инициализация не завершена; бот отключается во избежание частичной работы")
        await bot.close()
        return

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