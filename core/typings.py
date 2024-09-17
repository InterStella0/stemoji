from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core.client import StellaEmojiBot
    EContext = commands.Context[StellaEmojiBot]
    EInteraction = discord.Interaction[StellaEmojiBot]
else:
    StellaEmojiBot = commands.Bot
    EContext = commands.Context
    EInteraction = discord.Interaction
