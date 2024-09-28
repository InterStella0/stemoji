from __future__ import annotations
from typing import TYPE_CHECKING

import discord
from discord.app_commands import AppCommandError
from discord.ext import commands

if TYPE_CHECKING:
    from core.models import PersonalEmoji


class UserInputError(AppCommandError):
    pass


class EmojiImageDuplicates(UserInputError):
    def __init__(self, emoji: discord.Emoji, similars: list[tuple[PersonalEmoji, int]]):
        super().__init__(f"{emoji.name} found {len(similars)} potential duplicate(s)!")
        self.emoji = emoji
        self.similars = similars

class EmojiNameDuplicates(UserInputError):
    def __init__(self, emoji: discord.Emoji, conflict: PersonalEmoji):
        super().__init__(f"{emoji} found a conflict with {conflict.name}({conflict})!")
        self.emoji = emoji
        self.conflict = conflict


class NotEmojiOwner(commands.UserInputError):
    def __init__(self, emoji: PersonalEmoji):
        super().__init__(f"Only {emoji.added_by} can modify {emoji}!")
        self.emoji = emoji


class NotEmojiFavourite(commands.UserInputError):
    def __init__(self, emoji: PersonalEmoji):
        super().__init__(f"{emoji} is not in your favourite list!")
        self.emoji = emoji
