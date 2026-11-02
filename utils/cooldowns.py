"""A shared per-user, per-command cooldown for slash and prefix invocations."""
import time
from collections import OrderedDict


class UserCooldown:
    def __init__(self, seconds=3.0, clock=time.monotonic):
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
        # Slash interactions need an acknowledgement; prefix spam gets one notice per window.
        if context is None or not notified:
            self.entries[key] = (expires, True)
            await interaction.response.send_message(
                f"Не спешите, сэр. Повторите эту команду через {expires - now:.1f} с.",
                ephemeral=True,
            )
        return False
