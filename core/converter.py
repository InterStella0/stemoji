from typing import Annotated

from discord import Interaction
from discord.app_commands import Choice, Transformer
from discord.ext.commands import Converter

from core.models import PersonalEmoji
from core.typings import EInteraction, EContext


class PersonalEmojiConverter(Converter[PersonalEmoji], Transformer):
    async def convert(self, ctx: EContext, argument: str) -> PersonalEmoji:
        return await PersonalEmoji.convert(ctx, argument)

    async def transform(self, interaction: Interaction, value: str, /) -> PersonalEmoji:
        return await PersonalEmoji.transform(interaction, value)

    async def autocomplete(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        return await PersonalEmoji.autocomplete(interaction, current)


PersonalEmojiModel = Annotated[PersonalEmoji, PersonalEmojiConverter]
