from __future__ import annotations
import asyncio
import datetime
import functools
import json
import logging
import re
from typing import Any

import aiohttp
import discord
import starlight
from discord import app_commands
from discord.ext import commands

from core.db import DbPostgres, DbSqlite
from core.errors import EmojiImageDuplicates
from core.models import PersonalEmoji, NormalEmoji
from core.typings import EContext
from utils.general import emoji_context, slash_context, LOGGER_NAME
from utils.parsers import env

VERSION = "0.0.6"


class StellaEmojiBot(commands.Bot):
    tree: Tree

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = env("MESSAGE_CONTENT_INTENTS", bool)
        intents.members = env("MEMBERS_INTENTS", bool)
        cmd_prefix = env("TEXT_COMMAND_PREFIX")
        if env("TEXT_COMMAND_PREFIX_MENTION"):
            cmd_prefix = commands.when_mentioned_or(cmd_prefix)

        super().__init__(
            cmd_prefix, intents=intents, strip_after_prefix=True, help_command=starlight.MenuHelpCommand(),
            max_messages=None, chunk_guilds_at_startup=False, member_cache_flags=discord.MemberCacheFlags.none(),
            tree_cls=Tree
        )
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
            raise RuntimeError("DATABASE environment variable has an invalid choice.")

        self.check_once(self.called_everywhere)
        self.__get_user_lock: asyncio.Lock = asyncio.Lock()
        self._fetched_user_usage: set[int] = set()
        self._fetched_fav_usage: set[int] = set()
        self._extension_loaded: asyncio.Event = asyncio.Event()
        self.log = logging.getLogger(LOGGER_NAME)
        self.session: aiohttp.ClientSession | None = None

    def passive_bulk_user_usage(self, user: discord.User | discord.Member | discord.Object) -> asyncio.Task | None:
        if user.id in self._fetched_user_usage:
            return

        self._fetched_user_usage.add(user.id)
        return asyncio.create_task(self.ensure_bulk_user_usage(user))

    def passive_bulk_favourite_user(self, user: discord.User | discord.Member | discord.Object) -> asyncio.Task | None:
        if user.id in self._fetched_fav_usage:
            return

        self._fetched_fav_usage.add(user.id)
        return asyncio.create_task(self.ensure_bulk_favourite_user(user))

    async def ensure_bulk_favourite_user(self, user: discord.User | discord.Member | discord.Object) -> None:
        user_id = user.id
        records = await self.db.list_emoji_favourite(user_id)
        for record in records:
            if emoji := self.emojis_users.get(record.emoji_id):
                emoji.favourites.add(user_id)

    async def ensure_bulk_user_usage(self, user: discord.User | discord.Member | discord.Object) -> None:
        usages = await self.db.fetch_user_usages(user.id)
        for usage in usages:
            if emoji := self.emojis_users.get(usage.emoji_id):
                emoji.usages[user.id] = usage.amount

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
        slash_context.set(ctx)
        return True

    async def ensure_user(
            self, user: discord.User | discord.Member | discord.Object, __user_inserted=set()  # noqa, we're keeping state.
    ) -> None:
        if user.id not in __user_inserted:
            await self.db.create_user(user.id)
            __user_inserted.add(user.id)

    async def sync_emojis(self):
        try:
            self.emojis_users = {emoji.id: PersonalEmoji(self, emoji) for emoji in await self.fetch_application_emojis()}
            self.emoji_names = {emoji.name: emoji.id for emoji in self.emojis_users.values()}
            await self.normal_emojis.fill()
            await asyncio.gather(*[emoji.ensure() for emoji in self.emojis_users.values()])
            emojis_records = await self.db.fetch_emojis()
            to_delete = []
            to_update_names = []
            for emoji in emojis_records:
                emoji_id = emoji.id
                if emoji_id not in self.emojis_users:
                    to_delete.append(emoji_id)
                elif emoji.fullname != (emoji_name := self.emojis_users[emoji_id].name):
                    to_update_names.append([emoji_id, emoji_name])

            if to_update_names:
                await self.db.bulk_update_emoji_names(to_update_names)

            if to_delete:
                await self.db.bulk_remove_emojis(to_delete)
        finally:
            self.emoji_filled.set()

    async def setup_hook(self):
        await self.db.init_database()
        await self.bot_metadata()
        _ = asyncio.create_task(self.sync_emojis())
        cogs = ['cogs.emote', 'cogs.reactions', 'cogs.error_handling']
        if env('OWNER_ONLY', bool) and env('MIRROR_PROFILE', bool):
            cogs.append('cogs.mirroring')

        for cog in cogs:
            await self.load_extension(cog)

        self._extension_loaded.set()

    async def append_metadata(self, key: str, data: Any) -> None:
        meta = await self.db.fetch_metadata(VERSION)
        new_meta = meta.data.copy()
        new_meta[key] = data
        self.log.debug(f"Metadata {json.dumps(new_meta, indent=4)}")
        await self.db.update_metadata(meta.id, new_meta)

    async def bot_metadata(self):
        self.log.info(f"Bot's version {VERSION}.")
        meta = await self.db.fetch_metadata(VERSION)
        new_meta = meta.data.copy()

        counter = new_meta.get("start_counter") or 0
        new_meta["start_counter"] = counter + 1

        async def t():
            await self._extension_loaded.wait()
            self.log.info(f"Syncing slash command to discord in 10 seconds.")
            await asyncio.sleep(10)
            slashs = await self.tree.sync()
            self.log.info(f"Synced {len(slashs)} commands.")
        if new_meta.get("first_time") is None or new_meta.get("first_time") is True:
            self.log.info(f"Version change detected.")
            _ = asyncio.create_task(t())
            new_meta["first_time"] = False
        else:
            info = datetime.datetime.now().astimezone().tzinfo
            self.log.info(f"Using {VERSION} since {meta.created_at.astimezone(info)}.")
            self.log.info(f"Bot start counter {new_meta['start_counter']}")
            if meta.data.get("slash_commands") is None:
                self.log.info(f"Unable to find slash metadata.")
                _ = asyncio.create_task(t())
            else:
                self.tree.update_slash_lookup(meta.data["slash_commands"])

        await self.db.update_metadata(meta.id, new_meta)
        self.log.debug(f"Bot metadata updated.")

    async def _starter(self, token: str):
        discord.utils.setup_logging()
        async with self, self.db, aiohttp.ClientSession() as self.session:
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

    async def find_image_duplicates(self, emoji: discord.Emoji | discord.PartialEmoji | bytes) -> list[tuple[PersonalEmoji, int]]:
        find_hash = PersonalEmoji.to_byte_hash if isinstance(emoji, bytes) else PersonalEmoji.to_image_hash
        hasher = await find_hash(emoji)
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
            created_at = last_data.fetched_at
            if created_at > discord.utils.utcnow() + datetime.timedelta(days=5):
                actual_data = await self.fetch()
                is_new = True
            else:
                actual_data = json.loads(last_data.json_data)
        else:
            actual_data = await self.fetch()
            is_new = True

        if is_new:
            await db.create_normal_emojis(actual_data)

        self.mapping = {name: NormalEmoji(name=name, unicode=unicode) for name, unicode in actual_data.items()}

    def get(self, name: str) -> NormalEmoji | None:
        return self.mapping.get(name)


class Tree(app_commands.CommandTree[StellaEmojiBot]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slash_hashes: dict[str, dict[int | None, int]] = {}

    async def interaction_check(self, interaction: discord.Interaction[StellaEmojiBot], /) -> bool:
        emoji_context.set(interaction.user)
        slash_context.set(interaction)
        return True

    def update_slash_lookup(self, app_mapping: dict[list[dict[str, Any]]]):
        self._slash_hashes.clear()
        for scope, apps in app_mapping.items():
            scope: int | None = None if scope in ('null', None) else int(scope)
            for app in map(lambda data: app_commands.AppCommand(data=data, state=self._state), apps):
                scoping = self._slash_hashes.setdefault(app.name, {})
                scoping[scope] = app.id
                for option in app.options:
                    if not isinstance(option, app_commands.AppCommandGroup):
                        continue

                    for sub_option in option.options:
                        if not isinstance(sub_option, app_commands.AppCommandGroup):
                            continue

                        scoping = self._slash_hashes.setdefault(sub_option.qualified_name, {})
                        scoping[scope] = app.id

                    scoping = self._slash_hashes.setdefault(option.qualified_name, {})
                    scoping[scope] = app.id

    def get_command_named(self, command: str, scope: discord.Guild | None, *, fallback=True):
        try:
            return self._slash_hashes[command][getattr(scope, 'id', None)]
        except KeyError:
            if scope is not None and fallback:
                return self.get_command_named(command, None)

    async def sync(self, *, guild: discord.abc.Snowflake | None = None) -> list[app_commands.AppCommand]:
        slashs = await super().sync(guild=guild)
        meta = await self.client.db.fetch_metadata(VERSION)
        d = meta.data.copy()
        slash = d.get("slash_commands", {})
        key = getattr(guild, 'id', None)
        serialize = [slash.to_dict() for slash in slashs]
        slash[key] = serialize
        await self.client.append_metadata("slash_commands", slash)
        self.update_slash_lookup(slash)
        return slashs
