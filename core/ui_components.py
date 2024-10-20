import asyncio
import io
import re
import traceback
from typing import Any, TypeVar, Generic, Sequence, List

import discord
import starlight

from core import errors
from core.errors import EmojiImageDuplicates, UserInputError
from core.models import PersonalEmoji, DownloadedEmoji
from core.typings import EInteraction, EContext
from utils.general import emoji_context, slash_context
from utils.parsers import VALID_EMOJI_SEMI, VALID_EMOJI_NORMAL


class ContextModal(discord.ui.Modal):
    async def interaction_check(self, interaction: EInteraction, /) -> bool:
        emoji_context.set(interaction.user)
        slash_context.set(interaction)
        return await super().interaction_check(interaction)

    async def on_error(self, interaction: EInteraction, error: Exception, /) -> None:
        if isinstance(error, UserInputError):
            error_message = str(error)
        else:
            error_message = "Something went wrong :/"
            traceback.print_exception(error)
        if interaction.response.is_done():
            await interaction.followup.send(error_message, ephemeral=True)
        else:
            await interaction.response.send_message(error_message, ephemeral=True)


class ContextView(discord.ui.View):
    async def interaction_check(self, interaction: EInteraction, /) -> bool:
        emoji_context.set(interaction.user)
        slash_context.set(interaction)
        return await super().interaction_check(interaction)

    async def on_error(self, interaction: EInteraction, error: Exception, item: discord.ui.Item) -> None:
        if isinstance(error, UserInputError):
            error_message = str(error)
        else:
            error_message = "Something went wrong :/"
            traceback.print_exception(error)
        if interaction.response.is_done():
            await interaction.followup.send(error_message, ephemeral=True)
        else:
            try:
                await interaction.response.send_message(error_message, ephemeral=True)
            except discord.NotFound:
                await interaction.followup.send(error_message, ephemeral=True)


class TextEmojiModal(ContextModal, title="Emoji Support Text"):
    text_to_send = discord.ui.TextInput(label="Text to send", style=discord.TextStyle.long)

    async def on_submit(self, interaction: EInteraction, /) -> None:
        text = self.text_to_send.value
        bot = interaction.client
        if text.strip() == "":
            raise UserInputError("You didn't write anything in the modal.")

        def custom_emoji(match: re.Match) -> str:
            if (emoji := bot.get_custom_emoji(match.group('emoji_name'))) is not None:
                return f'{emoji:u}'
            return match.group(0)

        def normal_emoji(match: re.Match) -> str:
            if (emoji := bot.normal_emojis.get(match.group('emoji_name'))) is not None:
                return emoji.unicode
            return match.group(0)

        text = VALID_EMOJI_SEMI.sub(custom_emoji, text)
        text = VALID_EMOJI_NORMAL.sub(normal_emoji, text)
        await interaction.response.send_message(text)


class RenameEmojiModal(ContextModal, title="Emoji Edit"):
    name = discord.ui.TextInput(label="New Name")

    def __init__(self, emoji: PersonalEmoji):
        super().__init__()
        self.name.placeholder = emoji.name
        self.personal_emoji = emoji

    async def on_error(self, interaction: EInteraction, error: Exception, /) -> None:
        if interaction.response.is_done():
            await interaction.response.send_message(error, ephemeral=True)
        else:
            await interaction.followup.send(error, ephemeral=True)

    async def on_submit(self, interaction: EInteraction, /) -> None:
        await interaction.response.defer()
        personal_emoji = self.personal_emoji
        old_name = personal_emoji.name
        new_name = self.name.value.strip()
        try:
            await personal_emoji.rename(new_name)
        except ValueError as e:
            raise UserInputError(str(e)) from None
        await interaction.followup.send(f'Successfully renamed **{old_name}** to **{new_name}**', ephemeral=True)


class RenameEmojiButton(discord.ui.Button):
    def __init__(self, emoji: PersonalEmoji):
        super().__init__(emoji=emoji.emoji, label="Rename")
        self.personal_emoji = emoji

    async def callback(self, interaction: EInteraction) -> Any:
        await interaction.response.send_modal(RenameEmojiModal(self.personal_emoji))


class ContextViewAuthor(ContextView, starlight.ViewAuthor):
    pass


class SendEmojiView(ContextViewAuthor):
    def __init__(self, emoji: PersonalEmoji):
        super().__init__(delete_after=True)
        self.emoji: PersonalEmoji = emoji
        self.send_message_button.emoji = emoji.emoji
        self.send_messagex3_button.emoji = emoji.emoji
        self.remove_item(self.delete_sent_message)
        self.sent_message: discord.Message | None = None
        self.content_over_limit = False

    def formatting_view(self):
        if self.sent_message is not None:
            self.send_message_button.label = "+1"
            self.send_messagex3_button.label = "+3"
            self.add_item(self.delete_sent_message)
        else:
            self.send_message_button.label = "Send"
            self.send_messagex3_button.label = "Send x3"
            self.remove_item(self.delete_sent_message)

    @discord.ui.button(label="Send", style=discord.ButtonStyle.blurple)
    async def send_message_button(self, interaction: EInteraction, button: discord.ui.Button):
        emoji = self.emoji
        if self.sent_message is None:
            await interaction.response.send_message(f"{emoji:u}")
            self.content_over_limit = False
            self.sent_message = await interaction.original_response()
            self.formatting_view()
            await self.message.edit(view=self)
        else:
            message = self.sent_message
            await interaction.response.defer()
            if not self.content_over_limit:
                try:
                    self.sent_message = await message.edit(content=f"{message.content} {emoji:u}")
                except discord.NotFound:
                    self.sent_message = await interaction.followup.send(content=f"{emoji}")
                except discord.HTTPException as e:
                    TEXT_OVER_2000 = 50035
                    if e.code == TEXT_OVER_2000:
                        self.content_over_limit = True
                        return
                    else:
                        raise

                self.content_over_limit = False

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_sent_message(self, interaction: EInteraction, button: discord.ui.Button):
        await self.sent_message.delete(delay=0)
        self.sent_message = None
        self.formatting_view()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Send x3", style=discord.ButtonStyle.blurple)
    async def send_messagex3_button(self, interaction: EInteraction, button: discord.ui.Button):
        emoji = self.emoji
        send_emoji = f"{emoji:u3} " * 3
        if self.sent_message is None:
            await interaction.response.send_message(send_emoji)
            self.content_over_limit = False
            self.sent_message = await interaction.original_response()
            self.formatting_view()
            await self.message.edit(view=self)
        else:
            message = self.sent_message
            await interaction.response.defer()
            if not self.content_over_limit:
                try:
                    self.sent_message = await message.edit(content=f"{message.content} {send_emoji}")
                except discord.NotFound:
                    self.sent_message = await interaction.followup.send(content=send_emoji)
                except discord.HTTPException as e:
                    TEXT_OVER_2000 = 50035
                    if e.code == TEXT_OVER_2000:
                        self.content_over_limit = True
                        return
                    else:
                        raise

                self.content_over_limit = False


T = TypeVar('T')


class PaginationContextView(ContextView, starlight.SimplePaginationView, Generic[T]):
    _data_source: List[T]

    def __init__(self, data_source: Sequence[T], /, *, cache_page: bool = False, delete_after=True, **kwargs):
        super().__init__(data_source, cache_page=cache_page, delete_after=delete_after, **kwargs)
        self.remove_item(self.stop_button)

    @discord.ui.button(emoji="<:backward:1059315483599446156>")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.to_start(interaction)

    @discord.ui.button(emoji="<:left:1059315476737572904>")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.to_previous(interaction)

    @discord.ui.button(emoji="<:Right:1059315473369538570>")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.to_next(interaction)

    @discord.ui.button(emoji="<:forward:1059315487017808014>")
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.to_end(interaction)


async def author_prompter(view, text: str, ctx: EContext, ephemeral=False) -> bool | None:
    asyncio.create_task(view.start(ctx, content=text, ephemeral=ephemeral))
    async for interaction, item in starlight.inline_view(view):
        yield interaction, item


async def prompt(ctx: EContext, ephemeral=False, **kwargs) -> bool | None:
    view = ContextViewAuthor(delete_after=True)
    view.add_item(discord.ui.Button(label="Yes"))
    view.add_item(discord.ui.Button(label="No"))
    asyncio.create_task(view.start(ctx, ephemeral=ephemeral, **kwargs))
    async for interaction, item in starlight.inline_view(view):
        await interaction.response.defer()
        view.stop()
        return item.label == "Yes"


async def saving_emoji_interaction(
        ctx_or_inter: EInteraction | EContext, target_emoji: discord.Emoji | discord.PartialEmoji | DownloadedEmoji
) -> PersonalEmoji:
    ctx = ctx_or_inter
    if isinstance(ctx, EInteraction):
        ctx = await ctx_or_inter.client.get_context(ctx_or_inter)

    bot = ctx.bot
    try:
        emoji = await bot.save_emoji(target_emoji, ctx.author)
    except errors.EmojiImageDuplicates as e:
        emojis = "\n".join([f"- {emoji[0]} ({emoji[0].name})" for emoji in e.similars])
        text = (f"{e}. \n{emojis}"
                f"\n\n**Do you want to add regardless?**")
        file = discord.File(io.BytesIO(await target_emoji.read()), filename='emoji.png')
        embed = discord.Embed(title=f"Target Emoji", description=text)
        embed.set_image(url=f"attachment://{file.filename}")
        response = await prompt(ctx, ephemeral=True, embed=embed, file=file)
        if not response:
            return

        emoji = await bot.save_emoji(target_emoji, ctx.author, duplicate_image=True)
    except Exception as e:
        raise e from None

    await ctx.send(f"Downloaded {emoji}. Use *{emoji.name}* to refer to it!", ephemeral=True)
    return emoji


EMOJI_TARGET = PersonalEmoji | discord.Emoji | discord.PartialEmoji | DownloadedEmoji


class SaveButton(discord.ui.Button[ContextView]):
    def __init__(self, target_emoji: EMOJI_TARGET | None = None, **kwargs):
        super().__init__(label="Save", style=discord.ButtonStyle.green, emoji="\U0001f4be", **kwargs)
        self.target_emoji: EMOJI_TARGET | None = target_emoji
        self.emoji_downloaded: dict[int, int] = {}

    async def callback(self, interaction: EInteraction) -> None:
        await interaction.response.defer()
        self.disabled = True
        target_emoji = self.target_emoji
        emoji = await interaction.client.save_emoji(target_emoji, interaction.user, duplicate_image=True)
        await interaction.followup.send(f"Downloaded {emoji}. Use *{emoji.name}* to refer to it!", ephemeral=True)
        self.emoji_downloaded[target_emoji.id] = emoji
        await interaction.edit_original_response(view=self.view)


class EmojiDownloadView(PaginationContextView[PersonalEmoji]):
    def __init__(self, emojis: list[list[PersonalEmoji]]):
        super().__init__(emojis, delete_after=True)
        self.save_button = SaveButton(row=1)
        self.add_item(self.save_button)

    @discord.ui.button(label="Save All", row=1, style=discord.ButtonStyle.blurple)
    async def button_save_all(self, interaction: EInteraction, button: discord.ui.Button):
        # TODO: Add pagination for long emoji downloads.
        button.disabled = True
        self.save_button.disabled = True
        all_emojis = [emoji for emoji, in self.data_source if emoji.id not in self.save_button.emoji_downloaded]

        saved = []
        saved_mapping = set()
        await interaction.response.send_message(f"Saving `{len(all_emojis)}` emojis...", ephemeral=True)
        await self.message.edit(view=self)
        dups = []
        for target_emoji in all_emojis:
            try:
                emoji = await interaction.client.save_emoji(target_emoji, interaction.user)
            except EmojiImageDuplicates as e:
                dups.append(e)
                continue
            except Exception as e:
                traceback.print_exc()
                continue

            self.save_button.emoji_downloaded[target_emoji.id] = emoji
            saved_mapping.add(target_emoji.id)
            saved.append(emoji)
        non_error_set = {*saved_mapping, *[emote.emoji.id for emote in dups]}
        failed = [emoji for emoji in all_emojis if emoji.id not in non_error_set]
        extras = ["", ""]
        if failed:
            failures = '\n'.join([f"- {e.name}" for e in failed])
            extras = [
                f" and failed to download {len(failed)} emoji(s).",
                f"\n\n**List of failed downloads:**\n{failures}"
            ]

        if dups:
            duplicates = "\n".join([f"- {err.emoji.name}" for err in dups])
            extras[1] += (f"\nFound `{len(dups)}` duplicate(s)! Refusing to add them. "
                          f"You can manually save them by pressing the save button!. \n**List of duplicates:**\n{duplicates}")

        if saved:
            success = '\n'.join([f"- {e}: {e.name}" for e in saved])
            content = (f"Downloaded {len(saved)} emojis{extras[0]}\n"
                       f"**List of downloaded emojis:**\n{success}{extras[1]}")
        else:
            if not failed:
                extras[0] = "."

            content = f"No emoji was successfully saved{extras[0]}{extras[1]}"
        await interaction.edit_original_response(content=content)


class SelectEmojiPagination(PaginationContextView):
    selector: discord.ui.Select

    def update_select(self):
        emojis = self.data_source[self.current_page]
        options = [discord.SelectOption(label=emoji.name, value=str(emoji.id), emoji=emoji.emoji) for emoji in emojis]
        self.selector.options = options

    @discord.ui.select(placeholder="Select an emoji")
    async def selector(self, interaction: EInteraction, select: discord.ui.Select) -> None:
        emoji_id, = select.values
        emoji = interaction.client.get_custom_emoji(int(emoji_id))
        await interaction.response.send_message(f"{emoji:u}")
