from typing import Annotated

import discord
from discord import Interaction
from discord.app_commands import Choice, Transformer
from discord.ext.commands import Converter

from core.errors import NotEmojiOwner
from core.models import PersonalEmoji
from core.typings import EInteraction, EContext


class PersonalEmojiConverter(Converter[PersonalEmoji], Transformer):
    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        return await PersonalEmoji.convert(ctx, argument)

    async def transform(self, interaction: Interaction, value: str, /) -> PersonalEmoji:
        return await PersonalEmoji.transform(interaction, value)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current)


class PrivateEmojiConverter(PersonalEmojiConverter):
    """Only the owner of the emoji OR owner of the bot can get this emoji."""
    async def is_owner(self, user: discord.User, emoji: PersonalEmoji) -> bool:  # noqa
        return user == await emoji.resolve_owner() or await emoji.bot.is_owner(user)

    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        emoji = await PersonalEmoji.convert(ctx, argument)
        if await self.is_owner(ctx.author, emoji):
            return emoji

        raise NotEmojiOwner(emoji)

    async def transform(self, interaction: Interaction, value: str, /) -> PersonalEmoji:
        emoji = await PersonalEmoji.transform(interaction, value)
        if await self.is_owner(interaction.user, emoji):
            return emoji

        raise NotEmojiOwner(emoji)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current, owner_only=True)


PersonalEmojiModel = Annotated[PersonalEmoji, PersonalEmojiConverter]
PrivateEmojiModel = Annotated[PersonalEmoji, PrivateEmojiConverter]
