"""A shared per-user, per-command cooldown for slash and prefix invocations."""
import time
from collections import OrderedDict
import nextcord

class UserCooldown:
    def __init__(self, seconds=5.0, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self.entries = OrderedDict()

    async def allow(self, interaction):
        now = self.clock()
        while self.entries and next(iter(self.entries.values()))[0] <= now:
            self.entries.popitem(last=False)
        
        name = interaction.application_command.name
        key = (interaction.user.id, name)
        previous = self.entries.get(key)
        
        if previous is None:
            self.entries[key] = (now + self.seconds, False)
            return True
            
        expires, notified = previous
        context = getattr(interaction, 'context', None)
        if context is not None:
            context._lounge_response_sent = True
            
        # Отправляем сообщение один раз за окно кулдауна
        if context is None or not notified:
            self.entries[key] = (expires, True)
            
            embed = nextcord.Embed(
                title="⏳ Не так быстро, сэр",
                description=f"Повторите эту команду через **{expires - now:.1f}** сек.",
                color=0xC5A028 # Фирменный золотой Lounge
            )
            embed.set_footer(text="Lounge • Good Games Only")

            # Если это слэш-команда (нет context)
            if context is None:
                await interaction.response.send_message(embed=embed, ephemeral=False)
            # Если это префиксная команда (есть context)
            else:
                try:
                    await context.send(embed=embed)
                except Exception:
                    pass
            
        return False