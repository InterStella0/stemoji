import asyncio

import discord
import starlight
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.client import StellaEmojiBot
from core.converter import PersonalEmojiModel, PrivateEmojiModel, FavouriteEmojiModel, SearchEmojiConverter
from core.errors import UserInputError
from core.models import PersonalEmoji
from core.typings import EInteraction, EContext
from core.ui_components import EmojiDownloadView, RenameEmojiModal, RenameEmojiButton, SendEmojiView, TextEmojiModal, \
    ContextViewAuthor, PaginationContextView, saving_emoji_interaction, SelectEmojiPagination
from utils.general import inline_pages, slash_parse as _S
from utils.parsers import find_latest_unpaired_semicolon, VALID_EMOJI_SEMI, find_latest_unpaired_emoji, \
    VALID_EMOJI_NORMAL, FuzzyInsensitive


@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
class Emoji(commands.GroupCog):
    @commands.hybrid_command()
    async def send(self, ctx: EContext, emoji: PersonalEmojiModel):
        """Choosing how many emoji to send to the user. Text commands just sent the emoji normally."""
        if ctx.interaction:
            view = SendEmojiView(emoji)
            await view.start(ctx, content=emoji, ephemeral=True)
        else:
            await ctx.send(f"{emoji:u}")

        ctx.bot.dispatch('explicit_sent_emoji', ctx.author, emoji)

    @commands.hybrid_command(name="view")
    async def _view(self, ctx: EContext, emoji: PersonalEmojiModel | None = None):
        """Detailed information about each emoji that was stored."""
        if emoji is not None:
            if ctx.interaction:
                view = SendEmojiView(emoji)
                await view.start(ctx, content=emoji, ephemeral=True)
            else:
                await ctx.send(emoji)
            return

        author = ctx.author
        emojis = [*ctx.bot.emojis_users.values()]
        async with ctx.typing(ephemeral=True):
            await ctx.bot.ensure_bulk_user_usage(author)
            emojis.sort(key=lambda emote: emote.usages[author.id], reverse=True)

        async for page in inline_pages(emojis, ctx, per_page=6, cls=PaginationContextView):
            embed = page.embed
            embed.title = "View of emojis"
            embed.colour = ctx.bot.primary_color
            for emoji in page.item.data:
                embed.add_field(
                    name=f"{emoji} {emoji.name}",
                    value=f"**Used:** {emoji.usages[author.id]}\n"
                          f"**Added By:**{await emoji.resolve_owner()}\n"
                          f"**Created At:**{discord.utils.format_dt(emoji.created_at, 'd')}"
                )

    @commands.hybrid_command(name="list")
    async def _list(self, ctx: EContext):
        """Briefly list all the emojis you've used."""
        async with ctx.typing(ephemeral=True):
            await ctx.bot.ensure_bulk_user_usage(ctx.author)

        items = [emoji for emoji in ctx.bot.emojis_users.values()]
        items.sort(key=lambda emoji: emoji.usages[ctx.author.id], reverse=True)
        async for page in inline_pages(items, ctx, per_page=12):
            list_emojis = '\n'.join([f'{emoji}: {emoji.name} [`{emoji.usages[ctx.author.id]}`]'
                                     for emoji in page.item.data])
            embed = page.embed
            embed.title = "List of emojis"
            embed.colour = ctx.bot.primary_color
            embed.description = list_emojis

    @commands.hybrid_command(name="text")
    async def _text(self, ctx: EContext, text: str | None = None) -> None:
        """Send messages using emojis which supports autocomplete of custom emojis."""
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

        def process_emoji(match):
            if (emoji := ctx.bot.get_custom_emoji(match.group('emoji_name'))) is not None:
                return f'{emoji:u}'
            return match.group(0)

        def process_norm_emoji(match):
            if (emoji := ctx.bot.normal_emojis.get(match.group('emoji_name'))) is not None:
                return emoji.unicode
            return match.group(0)

        text = VALID_EMOJI_SEMI.sub(process_emoji, text)
        text = VALID_EMOJI_NORMAL.sub(process_norm_emoji, text)
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
        """Delete emoji that you own."""
        async with ctx.typing(ephemeral=True):
            await emoji.delete(ctx.author)
        await ctx.send(f"Successful deletion of **{emoji.name}**!")

    @commands.hybrid_command()
    async def search(self, ctx: EContext, emoji: SearchEmojiConverter):
        name = getattr(emoji, "name", emoji)
        async with ctx.typing(ephemeral=True):
            ranked = starlight.search(ctx.bot.emojis_users.values(), name=FuzzyInsensitive(name), sort=True)

        per_page = 25
        async for page in inline_pages(ranked, per_page=per_page, ctx=ctx, cls=SelectEmojiPagination):
            page.view.update_select()
            page.embed.title = "Emoji Selection"
            page.embed.description = f"\n".join([
                f"{i}. {emoji} {emoji.name}"
                for i, emoji in
                enumerate(page.item.data, start=page.view.current_page * per_page + 1)
            ])

    @commands.hybrid_command(name='fav')
    async def _fav(self, ctx: EContext, emoji: FavouriteEmojiModel):
        """Exclusively only use your favourite emoji"""
        await ctx.send(f"{emoji:u}")

    @commands.hybrid_group(name='favourite', fallback='list')
    async def fav(self, ctx: EContext):
        """Briefly list all of your favourite emojis!"""
        author = ctx.author
        async with ctx.typing(ephemeral=True):
            records = await ctx.bot.db.list_emoji_favourite(author.id)
            p_emojis = [ctx.bot.emojis_users[record.emoji_id] for record in records]
            await ctx.bot.ensure_bulk_user_usage(ctx.author)
            p_emojis.sort(key=lambda emote: emote.usages[author.id], reverse=True)

        if not records:
            raise UserInputError(_S("No favourite emoji found! Do /emoji favourite add: to add a new emoji."))

        size_list = len(p_emojis)
        PER_PAGE = 5
        async for page in inline_pages(p_emojis, ctx, PER_PAGE, cache_page=True):
            data = page.item.data
            offset = page.view.current_page * PER_PAGE
            list_emojis = "\n".join([
                f'{i}. {emote} {emote.name}[{emote.usages[author.id]}]'
                for i, emote in enumerate(data, start=offset)
            ])
            embed = page.embed
            embed.title = f"List of favourite emojis [`{size_list}`]"
            embed.description = list_emojis

    @fav.command('add')
    async def fav_add(self, ctx: EContext, emoji: PersonalEmojiModel):
        """Add an emoji into your favourite list."""
        async with ctx.typing(ephemeral=True):
            await emoji.favourite(ctx.author)
        await ctx.send(f"Favourited {emoji}")

    @fav.command('remove')
    async def fav_remove(self, ctx: EContext, emoji: FavouriteEmojiModel):
        """Remove an emoji from your favourite list."""
        async with ctx.typing(ephemeral=True):
            await emoji.unfavourite(ctx.author)
        await ctx.send(f"Unfavourited {emoji}")

    @commands.hybrid_command()
    async def rename(self, ctx: EContext, emoji: PrivateEmojiModel, new_name: str | None = None):
        """Rename emoji that you own."""
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
            try:
                await emoji.rename(new_name)
            except ValueError as e:
                raise UserInputError(str(e)) from None

            await ctx.send(f"Sucessfully renamed **{old_name}** to **{new_name}**.", ephemeral=True)

@app_commands.context_menu(name="Reply Emoji")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def replying_emoji(interaction: EInteraction, message: discord.Message):
    await interaction.response.send_message(_S("Waiting for an emoji to be sent. Use /emoji send:"), ephemeral=True)

    def check(user, _):
        return user == interaction.user

    try:
        _, emoji = await interaction.client.wait_for('explicit_sent_emoji', check=check, timeout=180)
    except asyncio.TimeoutError:
        await interaction.delete_original_response()
        return
    else:
        if interaction.guild:
            emote = f"{emoji:u}"
            try:
                await message.reply(f"-# {interaction.user} sent\n{emote}")
            except discord.Forbidden:
                await interaction.edit_original_response(content=f"Failed to send message.")
        else:
            await interaction.followup.send(f"{emoji:u}")
            await interaction.delete_original_response()


@app_commands.context_menu(name="Steal Emoji")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def steal_emoji(interaction: EInteraction, message: discord.Message):
    """Find custom emojis from a message and stores it into the bot."""
    await interaction.response.defer(ephemeral=True)
    bot = interaction.client
    ctx = await bot.get_context(interaction)
    emojis = [*PersonalEmoji.find_all_emojis(bot, message.content)]
    if not emojis:
        raise UserInputError("No custom emoji found!")
    elif len(emojis) > 1:
        emoji_dups = {emoji.id: asyncio.create_task(bot.find_image_duplicates(emoji)) for emoji in emojis}
        async for page in inline_pages(emojis, ctx, cls=EmojiDownloadView, per_page=1):
            item = page.item
            emoji, = item.data
            file = await emoji.to_file(filename=f"{emoji.name}_emoji.png")
            dups = await emoji_dups[emoji.id]
            embed = discord.Embed(title=emoji.name).set_image(url=f"attachment://{file.filename}")
            if dups:
                found_dups = '\n'.join([f'- {emote} ({emote.name})' for emote, _score in dups])
                embed.description = f"Possible duplicates:\n{found_dups}"
            view = page.view
            view.button_save.disabled = emoji.id in view.emoji_downloaded
            if page.iteration == 0:
                item.format(embed=embed, file=file)
            else:
                item.format(embed=embed, attachments=[file])

    else:
        target_emoji = emojis[0]
        await saving_emoji_interaction(interaction, target_emoji)


async def setup(bot: StellaEmojiBot) -> None:
    bot.tree.add_command(steal_emoji)
    bot.tree.add_command(replying_emoji)
    await bot.add_cog(Emoji())

async def teardown(bot: StellaEmojiBot) -> None:
    bot.tree.remove_command(steal_emoji)
    bot.tree.remove_command(replying_emoji)
