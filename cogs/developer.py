"""Private diagnostics for the application owner (not server administrators)."""
import logging
import nextcord
from nextcord import Interaction
from nextcord.ext import commands
from utils.embeds import base_embed
from utils.prefix import PrefixInteraction

log = logging.getLogger(__name__)


class Developer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _authorize(self, interaction: Interaction) -> bool:
        await interaction.response.defer(ephemeral=True)
        try:
            authorized = await self.bot.is_owner(interaction.user)
        except nextcord.HTTPException:
            log.warning("Не удалось проверить владельца приложения")
            authorized = False
        if not authorized:
            await interaction.followup.send("Эта команда доступна только создателю бота, сэр.", ephemeral=True)
        return authorized

    @commands.command(name="servers", help="Создателю: список серверов бота")
    @commands.is_owner()
    async def servers(self, interaction: commands.Context,
                      page: int = 1):
        interaction = PrefixInteraction(interaction)
        if not await self._authorize(interaction):
            return
        guilds = sorted(self.bot.guilds, key=lambda g: (g.name.casefold(), g.id))
        pages = max(1, (len(guilds) + 19) // 20)
        if page < 1 or page > pages:
            return await interaction.followup.send(f"Выберите страницу от 1 до {pages}, сэр.", ephemeral=True)
        lines = [f"• **{nextcord.utils.escape_markdown(g.name[:80])}** — `{g.id}`"
                 for g in guilds[(page - 1) * 20:page * 20]]
        embed = base_embed(title=f"🎩 Серверы Lounge · {len(guilds)}",
                           description=f"Страница {page}/{pages}\n\n" + ("\n".join(lines) or "Бот пока не состоит на серверах."))
        await interaction.followup.send(embed=embed, ephemeral=True,
                                        allowed_mentions=nextcord.AllowedMentions.none())

    @commands.command(name="get-sid", help="Создателю: ID сервера по названию")
    @commands.is_owner()
    async def get_sid(self, interaction: commands.Context,
                      *, name: str):
        interaction = PrefixInteraction(interaction)
        if not await self._authorize(interaction):
            return
        matches = [g for g in self.bot.guilds if g.name.casefold() == name.strip().casefold()]
        if not matches:
            return await interaction.followup.send("Сервер с таким названием не найден среди серверов бота, сэр.", ephemeral=True)
        lines = [f"• {nextcord.utils.escape_markdown(g.name[:80])} — `{g.id}`" for g in matches[:20]]
        text = "\n".join(lines)
        if len(matches) > 1:
            text = "Найдено несколько серверов с одинаковым названием:\n" + text
        if len(matches) > 20:
            text += "\nОстальные доступны через L.servers."
        await interaction.followup.send(embed=base_embed(title="🪪 ID сервера", description=text), ephemeral=True,
                                        allowed_mentions=nextcord.AllowedMentions.none())

    @commands.command(name="get-inv", help="Создателю: существующее приглашение сервера")
    @commands.is_owner()
    async def get_inv(self, interaction: commands.Context,
                      server_id: str):
        interaction = PrefixInteraction(interaction)
        if not await self._authorize(interaction):
            return
        try:
            guild = self.bot.get_guild(int(server_id))
        except ValueError:
            guild = None
        if guild is None:
            return await interaction.followup.send("Сервер не найден. Укажите ID сервера, где состоит бот, сэр.", ephemeral=True)
        try:
            if "VANITY_URL" in guild.features:
                vanity = await guild.vanity_invite()
                if vanity:
                    return await interaction.followup.send(vanity.url, ephemeral=True)
            invites = await guild.invites()
        except nextcord.Forbidden:
            return await interaction.followup.send(
                "Не хватает прав для просмотра приглашений. Боту нужно разрешение «Управлять сервером» на этом сервере.", ephemeral=True)
        except nextcord.HTTPException:
            return await interaction.followup.send("Discord не ответил на запрос приглашений. Попробуйте позже, сэр.", ephemeral=True)
        now = nextcord.utils.utcnow()
        usable = [invite for invite in invites
                  if (invite.expires_at is None or invite.expires_at > now)
                  and (not invite.max_uses or (invite.uses or 0) < invite.max_uses)]
        if not usable:
            return await interaction.followup.send(
                "Действующих приглашений не найдено. Новые ссылки автоматически не создаются, сэр.", ephemeral=True)
        await interaction.followup.send(usable[0].url, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Developer(bot))
