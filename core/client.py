import asyncio
import datetime
import functools
import json
import re

import aiohttp
import asyncpg
import discord
import starlight
from discord.ext import commands

from core.db import DbPostgres, DbSqlite
from core.errors import EmojiImageDuplicates
from core.models import PersonalEmoji, NormalEmoji
from core.typings import EContext
from utils.general import emoji_context
from utils.parsers import env


class StellaEmojiBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = env("MESSAGE_CONTENT_INTENTS", bool)
        intents.members = env("MEMBERS_INTENTS", bool)
        cmd_prefix = env("TEXT_COMMAND_PREFIX")
        if env("TEXT_COMMAND_PREFIX_MENTION"):
            cmd_prefix = commands.when_mentioned_or(cmd_prefix)

        super().__init__(cmd_prefix, intents=intents, strip_after_prefix=True, help_command=starlight.MenuHelpCommand())
        self.emojis_users: dict[int, PersonalEmoji] = {}
        self.emoji_names: dict[str, int] = {}
        self.emoji_filled: asyncio.Event = asyncio.Event()
        self.primary_color: int = 0xffcccb
        self.normal_emojis: NormalDiscordEmoji = NormalDiscordEmoji(self)
        conn_string = env("DATABASE_DSN")
        if env('DATABASE') == 'postgres':
            self.db: DbPostgres = DbPostgres(conn_string)
        elif env("DATABASE") == 'sqlite':
            self.db: DbSqlite = DbSqlite(conn_string)
        else:
            raise RuntimeError("DATABASE environment variable is not valid.")

        self.check_once(self.called_everywhere)
        self.__get_user_lock: asyncio.Lock = asyncio.Lock()

    async def get_or_fetch_user(
            self, user_id: int, *, __user_cached={}  # noqa
    ):
        """I need to get or fetch and auto cache."""

        if (user := self.get_user(user_id)) is None:
            async with self.__get_user_lock:
                if (user := __user_cached.get(user_id)) is None:
                    user = await self.fetch_user(user_id)
                    __user_cached[user.id] = user

        return user

    def called_everywhere(self, ctx: EContext): # noqa
        emoji_context.set(ctx.author)
        return True

    async def ensure_user(
            self, user: discord.User | discord.Member | discord.Object, __user_inserted={}  # noqa, we're keeping state.
    ) -> asyncpg.Record:
        if (d := __user_inserted.get(user.id, discord.utils.MISSING)) is not discord.utils.MISSING:
            return d

        data = await self.db.create_user(user.id)
        __user_inserted[user.id] = data
        return data

    async def sync_emojis(self):
        self.emojis_users = {emoji.id: PersonalEmoji(self, emoji) for emoji in await self.fetch_application_emojis()}
        self.emoji_names = {emoji.name: emoji.id for emoji in self.emojis_users.values()}
        await self.normal_emojis.fill()
        await asyncio.gather(*[emoji.ensure() for emoji in self.emojis_users.values()])
        emojis_records = await self.db.fetch_emojis()
        to_delete = []
        for emoji in emojis_records:
            if emoji.id not in self.emojis_users:
                to_delete.append(emoji.id)

        await self.db.bulk_remove_emojis(to_delete)

    async def setup_hook(self):
        await self.db.init_database()
        await self.sync_emojis()
        self.emoji_filled.set()
        cogs = ['cogs.emote', 'cogs.reactions', 'cogs.error_handling']
        if env('OWNER_ONLY', bool) and env('MIRROR_PROFILE', bool):
            cogs.append('cogs.mirroring')

        for cog in cogs:
            await self.load_extension(cog)

    async def _starter(self, token: str):
        discord.utils.setup_logging()
        async with self, self.db:
            await self.start(token)

        if self.normal_emojis.http:
            await self.normal_emojis.http.close()

    def starter(self, token: str):
        asyncio.run(self._starter(token))

    def get_custom_emoji(self, hasher: int | str) -> PersonalEmoji | None:
        if isinstance(hasher, int):
            return self.emojis_users.get(hasher)
        elif isinstance(hasher, str):
            emoji_id = self.emoji_names.get(hasher)
            return self.emojis_users.get(emoji_id)

    async def find_image_duplicates(self, emoji: discord.Emoji | discord.PartialEmoji) -> list[tuple[PersonalEmoji, int]]:
        hasher = await PersonalEmoji.to_image_hash(emoji)
        similarity_emoji = [(emoji, hasher - emoji.image_hash) for emoji in self.emojis_users.values()]
        similarity_emoji.sort(key=lambda sim: sim[1])
        return [e for e in similarity_emoji if e[1] < 9][:5]

    async def save_emoji(
            self, emoji: discord.PartialEmoji | discord.Emoji | PersonalEmoji, user: discord.Object, *,
            duplicate_image=False, increment=True
    ) -> PersonalEmoji:
        img_bytes = await emoji.read()
        emoji_name = None
        if increment:
            emoji_name = emoji.name
            while True:
                personal_emoji = self.get_custom_emoji(emoji_name)
                if personal_emoji is None:
                    break

                pattern_number_end = re.compile(r'^(?P<name>.+?)(?P<number>\d*)$')
                emoji_num = pattern_number_end.match(emoji_name)
                try:
                    increment_value = int(emoji_num.group('number')) + 1
                    emoji_name = f'{emoji_num.group("name")}{increment_value}'
                except ValueError:
                    emoji_name = f'{emoji_name}1'

        if not duplicate_image:
            value = await self.find_image_duplicates(emoji)
            if value:
                raise EmojiImageDuplicates(emoji, value)

        emoji = await self.create_application_emoji(name=emoji_name or emoji.name, image=img_bytes)
        new_emoji = PersonalEmoji(self, emoji)
        await new_emoji.ensure(user)
        self.emojis_users[emoji.id] = new_emoji
        self.emoji_names[new_emoji.name] = emoji.id
        return new_emoji


class NormalDiscordEmoji:
    URL = "https://gist.githubusercontent.com/Vexs/629488c4bb4126ad2a9909309ed6bd71/raw/emoji_map.json"

    def __init__(self, bot: StellaEmojiBot) -> None:
        self.mapping: dict[str, NormalEmoji] = {}
        self.bot: StellaEmojiBot = bot
        self.http: aiohttp.ClientSession | None = None

    async def fetch(self) -> dict[str, str]:
        if self.http is None:
            self.http = aiohttp.ClientSession()

        async with self.http.get(self.URL) as resp:
            return await resp.json(content_type='text/plain')

    @functools.cached_property
    def emojis(self) -> list[NormalEmoji]:
        return [*self.mapping.values()]

    async def fill(self) -> None:
        db = self.bot.db
        last_data = await db.fetch_latest_normal_emoji()
        is_new = False
        if last_data:
            created_at = last_data['fetched_at']
            if created_at > discord.utils.utcnow() + datetime.timedelta(days=5):
                actual_data = await self.fetch()
                is_new = True
            else:
                actual_data = json.loads(last_data['json_data'])
        else:
            actual_data = await self.fetch()
            is_new = True

        if is_new:
            await db.create_normal_emojis(actual_data)

        self.mapping = {name: NormalEmoji(name=name, unicode=unicode) for name, unicode in actual_data.items()}

    def get(self, name: str) -> NormalEmoji | None:
        return self.mapping.get(name)
