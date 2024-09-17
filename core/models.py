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
        self.update_tasks: dict[int, asyncio.Task] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self.image_hash: imagehash.ImageHash | None = None

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

    async def ensure(self, user: discord.User | discord.Member | discord.Object = None) -> asyncpg.Record:
        if self.db_data:
            return self.db_data

        if user is None:
            data = await self.bot.pool.fetchrow("SELECT * FROM emoji WHERE id=$1", self.id)
            if data is not None:
                img_hash = data['hash']
                if img_hash != '':
                    self.generate_from_hash(img_hash)
                else:
                    hashs = await self.create_image_hash()
                    await self.bot.pool.execute("UPDATE emoji SET hash=$2 WHERE id=$1", self.id, str(hashs))
                self.db_data = data
                return self.db_data

        added = getattr(user, 'id', self.bot.user.id)
        await self.bot.ensure_user(discord.Object(added))
        img_hash = await self.create_image_hash()
        self.db_data = await self.bot.pool.fetchrow(
            "INSERT INTO emoji(id, fullname, added_by, hash) VALUES($1, $2, $3, $4) ON CONFLICT(id) "
            "DO NOTHING RETURNING *",
            self.id, self.name, added, str(img_hash)
        )
        return self.db_data

    def used(self, user: discord.User | discord.Member, value: int = 1) -> None:
        self._recent_emoji_usage[user.id] += value
        self.bot.dispatch('implicit_sent_emoji', user, self)
        if user.id not in self.update_tasks:
            self.update_tasks[user.id] = asyncio.create_task(self._delayed_used(user.id))

    async def user_usage(self, user: discord.User | discord.Member | discord.Object):
        record = await self.bot.pool.fetchrow(
            "SELECT * FROM emoji_used WHERE emoji_id=$1 AND user_id=$2",self.id, user.id
        )
        amount = record['amount'] if record is not None else 0
        self.usages[user.id] = amount
        return amount

    async def _delayed_used(self, user_id: int):
        await asyncio.sleep(5)

        async with self.lock:
            value = self._recent_emoji_usage[user_id]
            del self._recent_emoji_usage[user_id]
            del self.update_tasks[user_id]

        await self.ensure()
        emoji_used = await self.bot.pool.fetchrow(
            """
            INSERT INTO emoji_used (emoji_id, user_id, amount)
            VALUES ($1, $2, $3)
            ON CONFLICT (emoji_id, user_id)
            DO UPDATE SET amount = emoji_used.amount + $3
            RETURNING *
            """,
            self.id, user_id, value
        )
        self.usages[user_id] = emoji_used['amount']

    async def rename(self, name: str) -> None:
        new_name = name.strip()
        old_name = self.name
        if new_name == old_name:
            raise ValueError(f"New name is the same as the old name.")

        if " " in new_name:
            raise ValueError("Spaces in names are not allowed.")

        self.emoji = await self.emoji.edit(name=new_name)

    async def delete(self, bot: StellaEmojiBot) -> None:
        await self.emoji.delete(reason="Remove requested by user.")
        del bot.emojis_users[self.emoji.id]

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
        raise commands.CommandError(f"No {argument} emoji found!") from None

    @classmethod
    async def transform(cls, interaction: EInteraction, argument: str) -> Self:
        try:
            return await cls.converting_emoji(interaction.client, argument)
        except commands.CommandError as e:
            raise app_commands.AppCommandError(str(e)) from None

    @staticmethod
    async def autocomplete(interaction: EInteraction, current: str) -> list[Choice[str]]:
        fuzzy_emojis = starlight.search(
            interaction.client.emojis_users.values(), sort=True, name=FuzzyInsensitive(current)
        )
        return [Choice(name=e.name, value=str(e.id)) for e in fuzzy_emojis[:25]]


@dataclasses.dataclass
class NormalEmoji:
    name: str
    unicode: str
