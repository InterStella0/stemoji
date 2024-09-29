from __future__ import annotations
import asyncio
import dataclasses
import io
import re
import sys
from collections import defaultdict
from typing import Generator, Self

import asyncpg
import discord
import imagehash
import starlight
from PIL import Image
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.errors import UserInputError
from core.typings import EContext, EInteraction, StellaEmojiBot
from utils.general import emoji_context
from utils.parsers import FuzzyInsensitive


@dataclasses.dataclass
class PersonalEmoji:
    CUSTOM_EMOJI_RE = re.compile(r'<?(?:(?P<animated>a)?:)?(?P<name>[A-Za-z0-9_]+):(?P<id>[0-9]{13,20})>?')
    USED_FORMATTER_RE = re.compile(r'u(?P<used>\d*)')

    def __init__(self, bot: StellaEmojiBot, emoji: discord.Emoji | discord.PartialEmoji):
        self.emoji: discord.Emoji | discord.PartialEmoji = emoji
        self.bot: StellaEmojiBot = bot
        self.db_data: asyncpg.Record | None = None
        self._recent_emoji_usage: dict[int, int] = defaultdict(int)
        self.usages: dict[int, int] = defaultdict(int)
        self.favourites: set[int] = set()
        self.update_tasks: dict[int, asyncio.Task] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self.image_hash: imagehash.ImageHash | None = None
        self.added_by: discord.User | discord.Member | discord.Object = None

    def to_choice_usage(self, user_id: int) -> Choice:
        return Choice(name=f"{self.name}", value=str(self.id))

    async def create_image_hash(self) -> imagehash.ImageHash:
        self.image_hash = await self.to_image_hash(self.emoji)
        return self.image_hash

    def generate_from_hash(self, img_hash: str) -> imagehash.ImageHash:
        self.image_hash = imagehash.hex_to_hash(img_hash)
        return self.image_hash

    @staticmethod
    async def to_image_hash(emoji: discord.Emoji | discord.PartialEmoji | PersonalEmoji) -> imagehash.ImageHash:
        img_byte = await emoji.read()

        def form_hash(_byte):
            with Image.open(io.BytesIO(_byte)) as img:
                return imagehash.phash(img)

        return await asyncio.to_thread(form_hash, img_byte)

    def __str__(self):
        return f"{self.emoji}"

    def __format__(self, format_spec):
        if matched := self.USED_FORMATTER_RE.match(format_spec):
            try:
                used = int(matched.group("used"))
            except ValueError:
                used = 1
            try:
                user = emoji_context.get()
            except LookupError:
                user = None
            if user is None:
                print(f" {self} was used but unable to identify user.", file=sys.stderr)
            else:
                self.used(user, used)
            format_spec = self.USED_FORMATTER_RE.sub("", format_spec)
        return super().__format__(format_spec)

    def __getattr__(self, item):
        return getattr(self.emoji, item)

    async def resolve_owner(self) -> discord.User | discord.Member:
        if self.added_by is None:
            await self.ensure()

        if not isinstance(self.added_by, (discord.User, discord.Member)):
            self.added_by = await self.bot.get_or_fetch_user(self.added_by.id)

        return self.added_by

    async def ensure(self, user: discord.User | discord.Member | discord.Object = None) -> asyncpg.Record:
        if self.db_data:
            return self.db_data

        if user is None:
            data = await self.bot.db.fetch_emoji(self.id)
            if data is not None:
                img_hash = data.hash
                if img_hash != '':
                    self.generate_from_hash(img_hash)
                else:
                    hashs = await self.create_image_hash()
                    await self.bot.db.update_emoji_hash(self.id, str(hashs))
                self.db_data = data
                self.added_by = discord.Object(data.added_by)
                return self.db_data

        added = getattr(user, 'id', self.bot.user.id)
        added_by = discord.Object(added)
        await self.bot.ensure_user(added_by)
        self.added_by = user or added_by
        img_hash = await self.create_image_hash()
        self.db_data = await self.bot.db.create_emoji(self.id, self.name, added, str(img_hash))
        return self.db_data

    def used(self, user: discord.User | discord.Member, value: int = 1) -> None:
        self._recent_emoji_usage[user.id] += value
        self.bot.dispatch('implicit_sent_emoji', user, self)
        if user.id not in self.update_tasks:
            self.update_tasks[user.id] = asyncio.create_task(self._delayed_used(user.id))

    async def user_usage(self, user: discord.User | discord.Member | discord.Object):
        record = await self.bot.db.upsert_emoji_usage(self.id, user.id, 0)
        self.usages[user.id] = record.amount
        return record.amount

    async def _delayed_used(self, user_id: int):
        await asyncio.sleep(5)

        async with self.lock:
            value = self._recent_emoji_usage[user_id]
            del self._recent_emoji_usage[user_id]
            del self.update_tasks[user_id]

        await self.ensure()
        await self.bot.ensure_user(discord.Object(user_id))
        emoji_used = await self.bot.db.upsert_emoji_usage(self.id, user_id, value)
        self.usages[user_id] = emoji_used.amount

    async def rename(self, name: str) -> None:
        new_name = name.strip()
        old_name = self.name
        if new_name == old_name:
            raise ValueError(f"New name is the same as the old name.")

        if " " in new_name:
            raise ValueError("Spaces in names are not allowed.")

        if not (3 <= len(new_name) < 33):
            raise ValueError("Emoji names must be inbetween 3 to 32 characters.")

        self.emoji = await self.emoji.edit(name=new_name)
        await self.bot.db.bulk_update_emoji_names([(self.id, new_name)])

    async def delete(self, user: discord.Member | discord.User) -> None:
        await self.emoji.delete(reason=f"Remove requested by {user}.")
        await self.bot.db.bulk_remove_emojis([self.emoji.id])
        del self.bot.emojis_users[self.emoji.id]

    async def favourite(self, user: discord.Object) -> None:
        await self.bot.db.create_emoji_favourite(self.id, user.id)
        self.favourites.add(user.id)

    async def unfavourite(self, user: discord.Object) -> None:
        await self.bot.db.remove_emoji_favourite(self.id, user.id)
        self.favourites.remove(user.id)

    @classmethod
    def find_all_emojis(cls, bot: StellaEmojiBot, content: str) -> Generator[Self, None, None]:
        founded = set()
        for match in cls.CUSTOM_EMOJI_RE.finditer(content):
            emoji_animated = bool(match.group(1))
            emoji_name = match.group(2)
            emoji_id = int(match.group(3))

            emoji = discord.PartialEmoji.with_state(
                bot._connection, animated=emoji_animated, name=emoji_name, id=emoji_id
            )
            if emoji in founded:
                continue

            founded.add(emoji)
            yield cls(bot, emoji)

    @classmethod
    async def convert(cls, ctx: EContext, argument: str) -> Self:
        return await cls.converting_emoji(ctx.bot, argument)

    @classmethod
    async def converting_emoji(cls, bot: StellaEmojiBot, argument: str) -> Self:
        await bot.emoji_filled.wait()

        try:
            emoji_id = int(argument.strip())
            return bot.emojis_users[emoji_id]
        except (ValueError, KeyError):
            pass

        if (emote := discord.utils.get(bot.emojis_users.values(), name=argument)) is not None:
            return emote
        raise UserInputError(f"No emoji named '{argument}' found!") from None

    @classmethod
    async def transform(cls, interaction: EInteraction, argument: str) -> Self:
        try:
            return await cls.converting_emoji(interaction.client, argument)
        except app_commands.AppCommandError:
            raise
        except Exception as e:
            raise app_commands.AppCommandError(str(e))

    @staticmethod
    async def autocomplete(
            interaction: EInteraction, current: str, *, owner_only: bool = False, fav_only: bool = False,
            mirror: bool = False
    ) -> list[Choice[str]]:
        bot = interaction.client
        user_id = interaction.user.id
        if task := bot.passive_bulk_user_usage(interaction.user):
            await task

        if owner_only and not await bot.is_owner(interaction.user):
            source = [emoji for emoji in bot.emojis_users.values() if emoji.added_by == interaction.user]
        elif fav_only:
            if task := bot.passive_bulk_favourite_user(interaction.user):
                await task

            source = [emoji for emoji in bot.emojis_users.values() if user_id in emoji.favourites]
        else:
            source = [*bot.emojis_users.values()]

        text_search = current.strip()
        if text_search == "":
            source.sort(key=lambda e: e.usages[user_id], reverse=True)
            return [e.to_choice_usage(user_id) for e in source[:25]]

        choices = []
        if mirror:
            choices.append(Choice(name=text_search, value=text_search))

        fuzzy_emojis = starlight.search(source, sort=True, name=FuzzyInsensitive(text_search))
        choices.extend([e.to_choice_usage(user_id) for e in fuzzy_emojis])
        return choices[:25]


class NormalEmoji:
    __slots__ = ('name', 'unicode')

    def __init__(self, name: str, unicode: str) -> None:
        self.name: str = name
        self.unicode: str = unicode
