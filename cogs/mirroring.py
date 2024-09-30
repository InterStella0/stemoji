import asyncio
import logging
import tempfile

import discord
from discord import ClientUser
from discord.ext import commands

from core.typings import StellaEmojiBot
from utils.general import LOGGER_NAME
from utils.parsers import env


class FileLock:
    def __init__(self):
        self._unlock = asyncio.Event()
        self.result = asyncio.Future()
        self.folder = None

    def unlock(self):
        self._unlock.set()

    async def get_folder(self):
        if self.folder is None:
            asyncio.create_task(self.create_folder())

        return await self.result

    async def create_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            self.result.set_result(folder)
            with open(f'{folder}/locker.txt', 'w+') as w:
                w.write('lock the file.')
                await self._unlock.wait()


class MirrorCog(commands.Cog):
    def __init__(self, bot: StellaEmojiBot):
        self.bot = bot
        self.bot_suffixes = env("BOT_NAME_SUFFIX")
        self.client_user: ClientUser | None = None
        self.original_client_user: ClientUser | None = None
        self.file_lock = FileLock()
        self.is_avatar_default = None
        self.original_image_path: str = ''
        self.original_client_username: str = ''
        self.is_retainable = None
        self.log = logging.getLogger(f"{LOGGER_NAME}.mirror")

    async def save_original_image(self):
        self.is_avatar_default = self.bot.user.avatar is None
        if self.is_avatar_default:
            return

        folder = await self.file_lock.get_folder()
        self.original_image_path = f'{folder}/bot_name.png'
        await self.bot.user.display_avatar.save(self.original_image_path)

    async def retain_original_profile(self):
        self.log.info("RETAINING ORIGINAL PROFILE. PLEASE DO NOT FORCE SHUTDOWN!")
        if not self.is_avatar_default:
            with open(self.original_image_path, 'rb') as r:
                image_bytes = r.read()
        else:
            image_bytes = None
        await self.bot.user.edit(username=self.original_client_username, avatar=image_bytes)
        self.log.info("DONE :)")

    async def save_original_profile(self):
        await self.save_original_image()
        self.original_client_username = self.bot.user.name
        self.is_retainable = True

    async def _profile_sync(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(90)
        await self.profile_sync()

    async def profile_sync(self):
        bot = self.bot
        if self.client_user is None:
            self.client_user = bot.user
            self.original_client_user = bot.user

        if env("RETAIN_PROFILE", bool):
            await self.save_original_profile()
        info = await bot.application_info()
        owner = info.owner

        await bot.user.edit(avatar=await owner.avatar.read(), username=f"{owner.global_name}{self.bot_suffixes}")

    async def cog_load(self) -> None:
        self.log.info("Profile syncing is enabled. This will override your bot's name and avatar in 90 seconds!")
        self.log.info("Set MIRROR_PROFILE to False if you want this to be disabled.")
        asyncio.create_task(self._profile_sync())

    async def cog_unload(self) -> None:
        if self.is_retainable:
            await self.retain_original_profile()
        self.file_lock.unlock()

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        bot = self.bot
        if not await bot.is_owner(before):
            return

        if before.avatar != after.avatar:
            self.client_user = await bot.user.edit(avatar=await after.avatar.read())
        elif before.global_name != after.global_name:
            self.client_user = await bot.user.edit(username=f"{after.global_name}{self.bot_suffixes}")


async def setup(bot: StellaEmojiBot) -> None:
    await bot.add_cog(MirrorCog(bot))
