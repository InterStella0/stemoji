from typing import Annotated

import discord
from discord.app_commands import Choice, Transformer
from discord.ext.commands import Converter

from core.errors import NotEmojiOwner, NotEmojiFavourite, UserInputError
from core.models import PersonalEmoji
from core.typings import EInteraction, EContext


class PersonalEmojiConverter(Converter[PersonalEmoji], Transformer):
    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        return await PersonalEmoji.convert(ctx, argument)

    async def transform(self, interaction: EInteraction, value: str, /) -> PersonalEmoji:
        return await PersonalEmoji.transform(interaction, value)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current)

class SearchEmojiConverter(Converter[PersonalEmoji], Transformer):
    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji | str:
        try:
            return await PersonalEmoji.convert(ctx, argument)
        except UserInputError:
            return argument

    async def transform(self, interaction: EInteraction, value: str, /) -> PersonalEmoji:
        try:
            return await PersonalEmoji.transform(interaction, value)
        except UserInputError:
            return value

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current, mirror=True)


class PrivateEmojiConverter(PersonalEmojiConverter):
    """Only the owner of the emoji OR owner of the bot can get this emoji."""
    async def is_owner(self, user: discord.User, emoji: PersonalEmoji) -> bool:  # noqa
        return user == await emoji.resolve_owner() or await emoji.bot.is_owner(user)

    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        emoji = await PersonalEmoji.convert(ctx, argument)
        if await self.is_owner(ctx.author, emoji):
            return emoji

        raise NotEmojiOwner(emoji)

    async def transform(self, interaction: EInteraction, value: str, /) -> PersonalEmoji:
        emoji = await PersonalEmoji.transform(interaction, value)
        if await self.is_owner(interaction.user, emoji):
            return emoji

        raise NotEmojiOwner(emoji)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current, owner_only=True)


class FavouriteEmojiConverter(PersonalEmojiConverter):
    """Only the owner of the emoji OR owner of the bot can get this emoji."""
    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        user = ctx.author
        emoji = await PersonalEmoji.convert(ctx, argument)
        await ctx.bot.ensure_bulk_favourite_user(user)
        if user.id in emoji.favourites:
            return emoji

        raise NotEmojiFavourite(emoji)

    async def transform(self, interaction: EInteraction, value: str, /) -> PersonalEmoji:
        user = interaction.user
        emoji = await PersonalEmoji.transform(interaction, value)
        await interaction.client.ensure_bulk_favourite_user(user)
        if user.id in emoji.favourites:
            return emoji

        raise NotEmojiFavourite(emoji)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current, fav_only=True)


PersonalEmojiModel = Annotated[PersonalEmoji, PersonalEmojiConverter]
FavouriteEmojiModel = Annotated[PersonalEmoji, FavouriteEmojiConverter]
PrivateEmojiModel = Annotated[PersonalEmoji, PrivateEmojiConverter]
SearchEmojiModel = Annotated[PersonalEmoji | str, SearchEmojiConverter]
