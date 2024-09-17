import asyncio

import discord
import starlight
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.client import StellaEmojiBot
from core.converter import PersonalEmojiModel, PrivateEmojiModel
from core.models import PersonalEmoji
from core.typings import EInteraction, EContext
from core.ui_components import EmojiDownloadView, RenameEmojiModal, RenameEmojiButton, SendEmojiView, TextEmojiModal, \
    ContextViewAuthor, PaginationContextView, saving_emoji_interaction
from utils.general import iter_pagination
from utils.parsers import find_latest_unpaired_semicolon, VALID_EMOJI_SEMI, find_latest_unpaired_emoji, \
    VALID_EMOJI_NORMAL, FuzzyInsensitive


@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
class Emoji(commands.GroupCog):
    @commands.hybrid_command()
    async def send(self, ctx: EContext, emoji: PersonalEmojiModel):
        if ctx.interaction:
            view = SendEmojiView(emoji)
            await view.start(ctx, content=emoji, ephemeral=True)
        else:
            await ctx.send(emoji)

        ctx.bot.dispatch('explicit_sent_emoji', ctx.author, emoji)

    @commands.hybrid_command(name="view")
    async def _view(self, ctx: EContext, emoji: PersonalEmojiModel | None = None):
        if emoji is not None:
            if ctx.interaction:
                view = SendEmojiView(emoji)
                await view.start(ctx, content=emoji, ephemeral=True)
            else:
                await ctx.send(emoji)
            return

        author = ctx.author
        emojis = [*ctx.bot.emojis_users.values()]
        coros = [asyncio.create_task(emoji.user_usage(author)) for emoji in emojis]
        async with ctx.typing(ephemeral=True):
            await asyncio.gather(*coros)

        emojis.sort(key=lambda emote: emote.usages[author.id], reverse=True)
        emojis = discord.utils.as_chunks(emojis, 12)
        async for i, item in iter_pagination(PaginationContextView(emojis), context=ctx):
            embed = discord.Embed(title="View of emojis", color=ctx.bot.primary_color)
            for emoji in item.data:
                emoji: PersonalEmoji
                embed.add_field(
                    name=f"{emoji} {emoji.name}",
                    value=f"**Used:** {emoji.usages[author.id]}\n"
                          f"**Added By:**{await emoji.resolve_owner()}\n"
                          f"**Created At:**{discord.utils.format_dt(emoji.created_at, 'd')}"
                )
            if i == 0:
                item.format(embed=embed, ephemeral=True)
            else:
                item.format(embed=embed)

    @commands.hybrid_command(name="list")
    async def _list(self, ctx: EContext):
        coros = [asyncio.create_task(emoji.user_usage(ctx.author)) for emoji in ctx.bot.emojis_users.values()]
        async with ctx.typing(ephemeral=True):
            await asyncio.gather(*coros)

        items = [emoji for emoji in ctx.bot.emojis_users.values()]
        items.sort(key=lambda emoji: emoji.usages[ctx.author.id], reverse=True)
        emojis = discord.utils.as_chunks(items, 12)
        async for i, item in iter_pagination(PaginationContextView(emojis), context=ctx):
            list_emojis = '\n'.join([f'{emoji}: {emoji.name} [`{emoji.usages[ctx.author.id]}`]' for emoji in item.data])
            eph = {'ephemeral': True} if i == 0 else {}
            item.format(embed=discord.Embed(
                title="List of emojis",
                color=ctx.bot.primary_color,
                description=list_emojis
            ), **eph)

    @commands.hybrid_command(name="text")
    async def _text(self, ctx: EContext, text: str | None = None) -> None:
        if text is None:
            if ctx.interaction:
                await ctx.interaction.response.send_modal(TextEmojiModal())
                return

            view = ContextViewAuthor(delete_after=True)
            view.add_item(discord.ui.Button(label="Text"))
            asyncio.create_task(view.start(ctx, content="What do I send?"))  # noqa
            async for interaction, item in starlight.inline_view(view):
                await interaction.response.send_modal(TextEmojiModal())
            return

        def custom_emoji(match):
            if (emoji := ctx.bot.get_custom_emoji(match.group('emoji_name'))) is not None:
                return f'{emoji:u}'
            return match.group(0)

        def normal_emoji(match):
            if (emoji := ctx.bot.normal_emojis.get(match.group('emoji_name'))) is not None:
                return emoji.unicode
            return match.group(0)

        text = VALID_EMOJI_SEMI.sub(custom_emoji, text)
        text = VALID_EMOJI_NORMAL.sub(normal_emoji, text)
        await ctx.send(text)

    @_text.autocomplete('text')
    async def find_nearest_emoji(self, interaction: EInteraction, current: str) -> list[Choice[str]]:
        if not current:
            return []
        if len(current) > 100:
            return []

        default = [app_commands.Choice(name=current, value=current)]
        for func, border in ((find_latest_unpaired_semicolon, ';'), (find_latest_unpaired_emoji, ':')):
            emoji_to_find = func(current)
            if emoji_to_find is None:
                continue

            emoji_name = emoji_to_find.lstrip(border)
            to_append_text = current.rstrip(emoji_to_find)
            choices = []
            if border == ';':
                choices = await PersonalEmoji.autocomplete(interaction, emoji_name)
                for choice in choices:
                    choice.value = to_append_text + f'{border}{choice.name}{border}'
                    choice.name = choice.value
            elif border == ':':
                values = interaction.client.normal_emojis.emojis
                ranked = starlight.search(values, name=FuzzyInsensitive(emoji_name), sort=True)
                choices = [Choice(
                    name=to_append_text + f'{border}{emoji.name}{border}',
                    value=to_append_text + f'{border}{emoji.name}{border}',
                ) for emoji in ranked]

            default.extend(choices)
        return default[:25]

    @commands.hybrid_command()
    async def delete(self, ctx: EContext, emoji: PrivateEmojiModel):
        async with ctx.typing(ephemeral=True):
            await emoji.delete(ctx.bot)
            await ctx.send(f"Successful deletion of **{emoji.name}**!")

    @commands.hybrid_command()
    async def rename(self, ctx: EContext, emoji: PrivateEmojiModel, new_name: str | None = None):
        if new_name is None:
            if interaction := ctx.interaction:
                await interaction.response.send_modal(RenameEmojiModal(emoji))
            else:
                view = ContextViewAuthor(delete_after=True)
                view.add_item(RenameEmojiButton(emoji))
                await view.start(ctx, content=emoji)

            return

        async with ctx.typing(ephemeral=True):
            old_name = emoji.name
            await emoji.rename(new_name)
            await ctx.send(f"Sucessfully renamed **{old_name}** to **{new_name}**.", ephemeral=True)

@app_commands.context_menu(name="Steal Emoji")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def steal_emoji(interaction: EInteraction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client
    ctx = await bot.get_context(interaction)
    emojis = [*PersonalEmoji.find_all_emojis(bot, message.content)]
    if not emojis:
        raise app_commands.AppCommandError("No custom emoji found!")
    elif len(emojis) > 1:
        view = EmojiDownloadView(emojis)
        emoji_dups = {emoji.id: asyncio.create_task(bot.find_image_duplicates(emoji)) for emoji in emojis}
        async for i, item in iter_pagination(view, context=ctx):
            emoji: PersonalEmoji = item.data
            file = await emoji.to_file(filename=f"{emoji.name}_emoji.png")
            dups = await emoji_dups[emoji.id]
            embed = discord.Embed(title=emoji.name).set_image(url=f"attachment://{file.filename}")
            if dups:
                found_dups = '\n'.join([f'- {emote} ({emote.name})' for emote, _score in dups])
                embed.description = f"Possible duplicates:\n{found_dups}"

            view.button_save.disabled = emoji.id in view.emoji_downloaded
            if i == 0:
                item.format(embed=embed, file=file)
            else:
                item.format(embed=embed, attachments=[file])

    else:
        target_emoji = emojis[0]
        await saving_emoji_interaction(interaction, target_emoji)


async def setup(bot: StellaEmojiBot) -> None:
    bot.tree.add_command(steal_emoji)
    await bot.add_cog(Emoji())

async def teardown(bot: StellaEmojiBot) -> None:
    bot.tree.remove_command(steal_emoji)

