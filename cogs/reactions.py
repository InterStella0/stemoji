import asyncio
import traceback
from collections import defaultdict, deque

import discord
import starlight
from discord import app_commands
from discord.ext import commands

from core.models import PersonalEmoji
from core.typings import EInteraction, StellaEmojiBot
from core.ui_components import ContextView, ContextViewAuthor


class ReactionCog(commands.Cog):
    def __init__(self):
        self.past_sent = defaultdict(lambda: deque(maxlen=10))

    @commands.Cog.listener()
    async def on_implicit_sent_emoji(self, user: discord.User, emoji: PersonalEmoji) -> None:
        self.past_sent[user.id].append(emoji)


@app_commands.context_menu(name="React This Message")
@app_commands.allowed_contexts(guilds=True, dms=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def react_message_emoji(interaction: EInteraction, message: discord.Message):
    cog: ReactionCog = interaction.client.get_cog(ReactionCog.__cog_name__)
    used_emojis = {emoji.id: emoji for emoji in reversed(cog.past_sent[interaction.user.id])}
    buttons = [discord.ui.Button(emoji=emote.emoji, label=emote.name) for emote in used_emojis.values()]
    emoji_to_react = None
    if buttons:
        view = ContextView()
        for button in buttons:
            view.add_item(button)

        await interaction.response.send_message(
            "Choose an emoji. \n-# You can use /emoji send <emoji>", view=view, ephemeral=True
        )
        async for inter, item in starlight.inline_view(view):
            await inter.response.edit_message(content=f"Reacting {item.emoji}")
            view.stop()
            emoji_to_react = item.emoji
            break

    else:
        await interaction.response.send_message("Use /emoji send <emoji>", ephemeral=True)
        try:
            _, emoji = await interaction.client.wait_for('explicit_sent_emoji', check=lambda u, e: u == interaction.user, timeout=180)
        except asyncio.TimeoutError:
            await interaction.delete_original_response()
            return
        else:
            emoji_to_react = emoji

    try:
        await message.add_reaction(f"{emoji_to_react}")
    except discord.Forbidden:
        await interaction.edit_original_response(content=f"Couldn't react {emoji_to_react}!", view=None)
    else:
        await interaction.edit_original_response(content=f"Reacted {emoji_to_react}", view=None)


async def setup(bot: StellaEmojiBot) -> None:
    bot.tree.add_command(react_message_emoji)
    await bot.add_cog(ReactionCog())


async def teardown(bot: StellaEmojiBot) -> None:
    bot.tree.remove_command(react_message_emoji)