import nextcord

GOLD = 0xC5A028
DARK_RED = 0x8B0000
GREEN = 0x2ECC71
BLUE = 0x3498DB
PURPLE = 0x9B59B6
ORANGE = 0xE67E22
GREY = 0x95A5A6


def footer_text(guild_name: str = "Lounge") -> str:
    """Return the shared Lounge branding and license footer."""
    return (
        f"🎩 {guild_name} • Good Games Only ㅤ‧ㅤ 2026 Lounge Team ©\n"
        "Код защищён лицензией MIT ㅤ‧ㅤ Копирование лора — моветон"
    )


def base_embed(
    title: str = None,
    description: str = None,
    color: int = GOLD,
    guild_name: str = "Lounge",
) -> nextcord.Embed:
    embed = nextcord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=footer_text(guild_name))
    return embed


def lobby_embed(
    game_type: str,
    host_name: str,
    players: list[str],
    guild_name: str = "Lounge",
) -> nextcord.Embed:
    icons = {
        "mafia_lite": "🎭", "mafia_full": "🎭", "mafia": "🎭",
        "bunker": "🏚️", "spyfall": "🕵️", "custom": "🎲",
    }
    labels = {
        "mafia_lite": "Мафия Lite", "mafia_full": "Мафия Full", "mafia": "Мафия",
        "bunker": "Bunker", "spyfall": "Spyfall", "custom": "Custom",
    }
    icon = icons.get(game_type, "🎲")
    label = labels.get(game_type, game_type.capitalize())

    hint = ""
    if game_type == "mafia_lite":
        hint = "\n*Режим 4–6 игроков. Минимум: 4.*"
    elif game_type == "mafia_full":
        hint = "\n*Режим 7–15 игроков. Минимум: 7.*"
    elif game_type == "bunker":
        hint = "\n*Режим 4–16 игроков.*"

    embed = base_embed(
        title=f"{icon} Лобби: {label}",
        description=(
            f"Хост: **{host_name}**\n\nПрисаживайтесь, господа.{hint}\n\n"
            "*⏱ Лобби закроется через 15 минут бездействия.*"
        ),
        guild_name=guild_name,
    )
    embed.add_field(
        name=f"👥 Игроки ({len(players)})",
        value="\n".join(f"• {p}" for p in players) if players else "_пусто_",
        inline=False,
    )
    return embed


def error_embed(text: str, guild_name: str = "Lounge") -> nextcord.Embed:
    return base_embed(title="❌ Ошибка", description=text, color=DARK_RED, guild_name=guild_name)


def success_embed(text: str, guild_name: str = "Lounge") -> nextcord.Embed:
    return base_embed(title="✅ Готово", description=text, color=GREEN, guild_name=guild_name)


def info_embed(title: str, text: str, guild_name: str = "Lounge") -> nextcord.Embed:
    return base_embed(title=title, description=text, color=BLUE, guild_name=guild_name)


# ─── Ночные эмбеды (ЛС) ───────────────────────────────
def night_mafia_embed(day: int, targets: list[str], mates: list[str]) -> nextcord.Embed:
    embed = nextcord.Embed(
        title=f"🌙 Ночь {day} — Мафия",
        description="Выберите жертву. Голосуйте тихо, господа.\n\n⏱ У вас 2 минуты.",
        color=DARK_RED,
    )
    if mates:
        embed.add_field(
            name="🎩 Ваши сообщники",
            value="\n".join(f"• {m}" for m in mates),
            inline=False,
        )
    embed.set_footer(text=footer_text())
    return embed


def night_cop_embed(day: int) -> nextcord.Embed:
    return nextcord.Embed(
        title=f"🌙 Ночь {day} — Комиссар",
        description="Выберите, кого проверить. Правда — ваше оружие.\n\n⏱ У вас 2 минуты.",
        color=BLUE,
    ).set_footer(text=footer_text())


def night_doctor_embed(day: int) -> nextcord.Embed:
    return nextcord.Embed(
        title=f"🌙 Ночь {day} — Доктор",
        description="Выберите, кого лечить. Жизнь — ваша профессия.\n\n⏱ У вас 2 минуты.",
        color=GREEN,
    ).set_footer(text=footer_text())


def cop_result_embed(target_name: str, is_mafia: bool) -> nextcord.Embed:
    if is_mafia:
        return base_embed(
            title="🕵️ Результат проверки",
            description=f"**{target_name}** — это **МАФИЯ** 🎩\n\nБудьте осторожны, сэр.",
            color=DARK_RED,
        )
    return base_embed(
        title="🕵️ Результат проверки",
        description=f"**{target_name}** — **не мафия** 👤\n\nИщите дальше, сэр.",
        color=BLUE,
    )


def night_announce_embed(day: int, alive_count: int, guild_name: str = "Lounge") -> nextcord.Embed:
    return nextcord.Embed(
        title=f"🌙 Ночь {day}",
        description=(
            f"Город засыпает. Живых: **{alive_count}**.\n\n"
            "*Роли получили инструкции в ЛС. У вас 2 минуты.*"
        ),
        color=0x2C3E50,
    ).set_footer(text=footer_text(guild_name))


def morning_embed(day: int, victim_name: str | None, saved: bool, guild_name: str = "Lounge") -> nextcord.Embed:
    if victim_name:
        desc = f"🌅 **День {day}**\n\nСегодня ночью убит: **{victim_name}** 💀\n\nМир праху его."
    elif saved:
        desc = f"🌅 **День {day}**\n\nВсе выжили этой ночью — доктор спас! 💉\n\nУдача, господа."
    else:
        desc = f"🌅 **День {day}**\n\nСтранная ночь — никто не пострадал. 🤔"

    return nextcord.Embed(
        title="☀️ Утро",
        description=desc,
        color=GOLD,
    ).set_footer(text=footer_text(guild_name))


# ─── Дневные эмбеды ──────────────────────────────────
def day_embed(
    day: int,
    alive_mentions: list[str],
    dead_log: list[tuple[str, str]] | None = None,
    guild_name: str = "Lounge",
) -> nextcord.Embed:
    embed = nextcord.Embed(
        title=f"☀️ День {day} — Обсуждение",
        description=(
            "Город просыпается. У вас **5 минут**, чтобы обсудить, кто мафия.\n"
            "Когда будете готовы — хост может нажать **«К голосованию»**."
        ),
        color=GOLD,
    )
    embed.add_field(
        name=f"👥 Живые ({len(alive_mentions)})",
        value="\n".join(f"• {m}" for m in alive_mentions) if alive_mentions else "_пусто_",
        inline=False,
    )
    if dead_log:
        dead_lines = [f"• {name} — {reason}" for name, reason in dead_log]
        embed.add_field(
            name=f"🪦 Мёртвые ({len(dead_log)})",
            value="\n".join(dead_lines),
            inline=False,
        )
    embed.set_footer(text=footer_text(guild_name))
    return embed


def vote_embed(day: int, alive_count: int, guild_name: str = "Lounge") -> nextcord.Embed:
    return nextcord.Embed(
        title=f"🗳️ Голосование — День {day}",
        description=(
            f"Живых: **{alive_count}**.\n"
            "Выберите, кого казнить. Голос **тайный**, видите только вы.\n"
            "Можно воздержаться.\n\n⏱ У вас 1 минута."
        ),
        color=ORANGE,
    ).set_footer(text=footer_text(guild_name))


def vote_result_execution_embed(
    day: int,
    results: dict[str, int],
    victim_name: str,
    victim_role: str,
    flavor: str,
    guild_name: str = "Lounge",
) -> nextcord.Embed:
    role_data = {
        "mafia": ("🎩", "Мафия"),
        "cop": ("🕵️", "Комиссар"),
        "doctor": ("💉", "Доктор"),
        "civilian": ("👤", "Мирный"),
    }
    emoji, role_label = role_data.get(victim_role, ("👤", "Мирный"))

    lines = []
    for name, count in sorted(results.items(), key=lambda x: -x[1]):
        lines.append(f"• **{name}** — {count} голос(ов)")

    embed = nextcord.Embed(
        title=f"⚖️ Голосование — День {day}",
        description="\n".join(lines) + f"\n\n{flavor}",
        color=DARK_RED,
    )
    embed.add_field(
        name=f"Казнён: {victim_name}",
        value=f"Он был... {emoji} **{role_label}**",
        inline=False,
    )
    embed.set_footer(text=footer_text(guild_name))
    return embed


def vote_result_no_execution_embed(
    day: int,
    results: dict[str, int] | None,
    reason: str,
    guild_name: str = "Lounge",
) -> nextcord.Embed:
    lines = []
    if results:
        for name, count in sorted(results.items(), key=lambda x: -x[1]):
            lines.append(f"• **{name}** — {count} голос(ов)")

    desc = ("\n".join(lines) + "\n\n" if lines else "") + reason

    return nextcord.Embed(
        title=f"⚖️ Голосование — День {day}",
        description=desc,
        color=ORANGE,
    ).set_footer(text=footer_text(guild_name))


def lobby_timeout_embed(guild_name: str = "Lounge") -> nextcord.Embed:
    return nextcord.Embed(
        title="⏱ Лобби закрыто",
        description="Прошло 15 минут бездействия. Лобби автоматически закрыто.",
        color=GREY,
    ).set_footer(text=footer_text(guild_name))