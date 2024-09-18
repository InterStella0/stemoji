import asyncio
import io
import traceback
from typing import Any, TypeVar, Generic

import discord
import starlight

from core import errors
from core.errors import EmojiImageDuplicates, UserInputError
from core.models import PersonalEmoji
from core.typings import EInteraction, EContext
from utils.general import emoji_context
from utils.parsers import VALID_EMOJI_SEMI, VALID_EMOJI_NORMAL


class ContextModal(discord.ui.Modal):
    async def interaction_check(self, interaction: EInteraction, /) -> bool:
        emoji_context.set(interaction.user)
        return await super().interaction_check(interaction)

    async def on_error(self, interaction: EInteraction, error: Exception, /) -> None:
        if isinstance(error, UserInputError):
            error_message = str(error)
        else:
            error_message = "Something went wrong :/"
            traceback.print_exception(error)
        if interaction.response.is_done():
            await interaction.followup.send(error_message)
        else:
            await interaction.response.send_message(error_message)


class ContextView(discord.ui.View):
    async def interaction_check(self, interaction: EInteraction, /) -> bool:
        emoji_context.set(interaction.user)
        return await super().interaction_check(interaction)

    async def on_error(self, interaction: EInteraction, error: Exception, item: discord.ui.Item) -> None:
        if isinstance(error, UserInputError):
            error_message = str(error)
        else:
            error_message = "Something went wrong :/"
            traceback.print_exception(error)
        if interaction.response.is_done():
            await interaction.followup.send(error_message)
        else:
            await interaction.response.send_message(error_message)


class TextEmojiModal(ContextModal, title="Emoji Support"):
    text_to_send = discord.ui.TextInput(label="Text to send", style=discord.TextStyle.long)

    async def on_submit(self, interaction: EInteraction, /) -> None:
        text = self.text_to_send.value
        bot = interaction.client

        def custom_emoji(match):
            if (emoji := bot.get_custom_emoji(match.group('emoji_name'))) is not None:
                return f'{emoji:u}'
            return match.group(0)

        def normal_emoji(match):
            if (emoji := bot.normal_emojis.get(match.group('emoji_name'))) is not None:
                return emoji
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
            self.sent_message = await interaction.original_response()
            self.formatting_view()
            await self.message.edit(view=self)
        else:
            message = self.sent_message
            await interaction.response.defer()
            try:
                self.sent_message = await message.edit(content=f"{message.content} {emoji:u}")
            except discord.NotFound:
                self.sent_message = await interaction.followup.send(content=f"{emoji}")

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
            self.sent_message = await interaction.original_response()
            self.formatting_view()
            await self.message.edit(view=self)
        else:
            message = self.sent_message
            await interaction.response.defer()
            try:
                self.sent_message = await message.edit(content=f"{message.content} {send_emoji}")
            except discord.NotFound:
                self.sent_message = await interaction.followup.send(content=send_emoji)


T = TypeVar('T')
class PaginationContextView(ContextView, starlight.SimplePaginationView, Generic[T]):
    _data_source: T


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


async def saving_emoji_interaction(interaction: EInteraction, target_emoji: discord.Emoji | discord.PartialEmoji) -> PersonalEmoji:
    try:
        emoji = await interaction.client.save_emoji(target_emoji, interaction.user)
    except errors.EmojiImageDuplicates as e:
        ctx = await interaction.client.get_context(interaction)
        emojis = "\n".join([f"- {emoji[0]} ({emoji[0].name})" for emoji in e.similars])
        text = (f"{e}. \n{emojis}"
                f"\n\n**Do you want to add regardless?**")
        file = discord.File(io.BytesIO(await target_emoji.read()), filename='emoji.png')
        embed = discord.Embed(title=f"Stealing Emoji", description=text)
        embed.set_image(url=f"attachment://{file.filename}")
        response = await prompt(ctx, ephemeral=True, embed=embed, file=file)
        if not response:
            return

        emoji = await interaction.client.save_emoji(target_emoji, interaction.user, duplicate_image=True)
    except Exception as e:
        raise e from None

    await interaction.followup.send(f"Downloaded {emoji}. Use *{emoji.name}* to refer to it!", ephemeral=True)
    return emoji


class EmojiDownloadView(PaginationContextView[PersonalEmoji]):
    def __init__(self, emojis: list[PersonalEmoji]):
        super().__init__(emojis, delete_after=True)
        self.emoji_downloaded: dict[int, int] = {}

    @discord.ui.button(label="Save", row=1, style=discord.ButtonStyle.green)
    async def button_save(self, interaction: EInteraction, button: discord.ui.Button):
        await interaction.response.defer()
        button.disabled = True
        target_emoji: PersonalEmoji = self.data_source[self.current_page]
        emoji = await interaction.client.save_emoji(target_emoji, interaction.user, duplicate_image=True)
        await interaction.followup.send(f"Downloaded {emoji}. Use *{emoji.name}* to refer to it!", ephemeral=True)
        self.emoji_downloaded[target_emoji.id] = emoji
        await self.message.edit(view=self)

    @discord.ui.button(label="Save All", row=1, style=discord.ButtonStyle.blurple)
    async def button_save_all(self, interaction: EInteraction, button: discord.ui.Button):
        button.disabled = True
        all_emojis = [emoji for emoji in self.data_source if emoji.id not in self.emoji_downloaded]

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

            self.emoji_downloaded[target_emoji.id] = emoji
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
