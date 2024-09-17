import discord

from core.models import PersonalEmoji


class UserInputError(Exception):
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
