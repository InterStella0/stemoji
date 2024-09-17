import os

import discord
from discord import app_commands
from discord.ext import commands

from core.client import StellaEmojiBot
from core.converter import PersonalEmojiModel
from core.typings import EContext
from utils.parsers import env

bot = StellaEmojiBot()

@bot.hybrid_command()
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def e(ctx: EContext, emoji: PersonalEmojiModel):
    await ctx.send(f"{emoji:u}")


@bot.command()
@commands.is_owner()
async def sync(ctx: EContext, guild: discord.Guild | None = None):
    synced = await bot.tree.sync(guild=guild)
    await ctx.send(f"OK {len(synced):,}")

token = env("BOT_TOKEN")
if not token:
    raise RuntimeError("BOT_TOKEN was not filled. Did you forget to fill it in? This is required.")

bot.starter(token)
