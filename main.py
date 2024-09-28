import tracemalloc

import discord
from discord import app_commands
from discord.ext import commands

from core.client import StellaEmojiBot
from core.converter import PersonalEmojiModel, FavouriteEmojiModel
from core.typings import EContext
from utils.general import inline_pages
from utils.parsers import env

tracemalloc.start()
bot = StellaEmojiBot()

@bot.hybrid_command()
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def e(ctx: EContext, emoji: PersonalEmojiModel):
    """Emote shortcut instead of a long ass name."""
    await ctx.send(f"{emoji:u}")

@bot.hybrid_command()
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def ef(ctx: EContext, emoji: FavouriteEmojiModel):
    """Emoji Favourite shortcut instead of a long ass name."""
    await ctx.send(f"{emoji:u}")


@bot.command()
@commands.is_owner()
async def sync(ctx: EContext, guild: discord.Guild | None = None):
    """Run this command to register your slash commands on discord."""
    synced = await bot.tree.sync(guild=guild)
    await ctx.send(f"Synced {len(synced)} commands.")


@bot.command()
@commands.is_owner()
async def profiler(ctx: EContext):
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    async for page in inline_pages(top_stats, ctx):
        desc = "\n".join(map(str, page.item.data))
        page.embed.description = f"```\n{desc}\n```"


token = env("BOT_TOKEN")
if not token:
    raise RuntimeError("BOT_TOKEN was not filled. Did you forget to fill it in? This is required.")

bot.starter(token)
