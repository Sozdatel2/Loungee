"""Reuse flat slash-command callbacks and their checks for prefix commands."""
import inspect
import nextcord
from nextcord.ext import commands


class PrefixInteraction:
    def __init__(self, ctx):
        self.context = ctx
        self.client = ctx.bot
        self.user = ctx.author
        self.guild = ctx.guild
        self.guild_id = ctx.guild.id if ctx.guild else None
        self.channel = ctx.channel
        self.channel_id = ctx.channel.id
        self.message = ctx.message
        self.application_command = ctx.command
        self.response = self
        self.followup = self
        self._reply = None
        self._done = False

    def is_done(self):
        return self._done

    async def defer(self, **kwargs):
        self._done = True

    async def send_message(self, content=None, *, ephemeral=False, **kwargs):
        kwargs.setdefault('allowed_mentions', nextcord.AllowedMentions.none())
        try:
            if ephemeral:
                message = await self.user.send(content, **kwargs)
            else:
                message = await self.context.send(content, **kwargs)
        except nextcord.Forbidden:
            if not ephemeral:
                raise
            # Never fall back to posting private data in the source channel.
            self.context._lounge_response_sent = True
            await self.context.send('Не удалось отправить ответ в ЛС. Разрешите личные сообщения от бота, сэр.',
                                    allowed_mentions=nextcord.AllowedMentions.none())
            return None
        self.context._lounge_response_sent = True
        self._reply = message
        self._done = True
        return message

    async def send(self, content=None, **kwargs):
        return await self.send_message(content, **kwargs)

    async def original_message(self):
        if self._reply is None:
            raise RuntimeError('No command response has been sent')
        return self._reply

    async def delete_original_message(self):
        if self._reply is not None:
            await self._reply.delete()


def prefix_callback_for(slash):
    parameters = list(inspect.signature(slash.callback, eval_str=True).parameters.values())
    if parameters and parameters[0].name in ('self', 'cls'):
        parameters = parameters[1:]
    parameters = parameters[1:]  # Interaction is replaced by Context.
    specs = {}
    adapted = [inspect.Parameter('ctx', inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    for index, parameter in enumerate(parameters):
        option = parameter.default if isinstance(parameter.default, nextcord.SlashOption) else None
        if option:
            specs[parameter.name] = option
            if option.default is not nextcord.utils.MISSING:
                default = option.default
            elif option.required is False:
                default = None
            else:
                default = inspect.Parameter.empty
        else:
            default = parameter.default
        kind = parameter.kind
        if index == len(parameters) - 1 and parameter.annotation is str:
            kind = inspect.Parameter.KEYWORD_ONLY
        adapted.append(parameter.replace(default=default, kind=kind))

    async def callback(ctx, *args, **kwargs):
        values = dict(zip([p.name for p in adapted[1:] if p.kind != p.KEYWORD_ONLY], args))
        values.update(kwargs)
        for name, option in specs.items():
            value = values.get(name)
            if value is None:
                continue
            if option.choices:
                choices = option.choices
                if isinstance(choices, dict):
                    value = choices.get(value, value)
                    values[name] = value
                    valid = choices.values()
                else:
                    valid = choices
                if value not in valid:
                    raise commands.BadArgument('Допустимые значения: ' + ', '.join(map(str, valid)))
            for limit, invalid in ((option.min_value, lambda x: value < x),
                                   (option.max_value, lambda x: value > x),
                                   (option.min_length, lambda x: len(value) < x),
                                   (option.max_length, lambda x: len(value) > x)):
                if limit is not None and invalid(limit):
                    raise commands.BadArgument(f'Аргумент {name} вне допустимого диапазона')
        interaction = PrefixInteraction(ctx)
        interaction.application_command = slash
        if not slash.is_global and (ctx.guild is None or ctx.guild.id not in slash.guild_ids_to_rollout):
            raise commands.CheckFailure("Команда недоступна на этом сервере")
        if slash.contexts is not None:
            context_type = 0 if ctx.guild else 1
            if context_type not in {context.value for context in slash.contexts}:
                raise commands.CheckFailure("Команда недоступна в этом типе канала")
        permissions = slash.get_default_member_permissions_value()
        if permissions is not None:
            actual = ctx.author.guild_permissions if ctx.guild else nextcord.Permissions.none()
            if not actual.administrator and (permissions == 0 or actual.value & permissions != permissions):
                raise commands.CheckFailure("Недостаточно прав для команды")
        try:
            await slash.can_run(interaction)
        except nextcord.ApplicationCheckFailure as error:
            raise commands.CheckFailure(str(error)) from error
        await slash(interaction, **values)

    callback.__name__ = 'prefix_' + slash.name.replace('-', '_')
    callback.__signature__ = inspect.Signature(adapted)
    return callback


def register_prefix(bot, slash):
    if not isinstance(slash, nextcord.SlashApplicationCommand):
        return
    existing = bot.get_command(slash.name)
    if existing and getattr(existing, '_slash_source', None) is slash:
        return
    if existing:
        raise RuntimeError(f'Prefix command name collision: {slash.name}')
    if slash.children:
        raise RuntimeError('Prefix bridge needs explicit support for slash subcommands')
    command = commands.Command(prefix_callback_for(slash), name=slash.name,
                               help=slash.description, ignore_extra=False)
    command._slash_source = slash
    bot.add_command(command)
