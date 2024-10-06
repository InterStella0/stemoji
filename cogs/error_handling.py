import traceback

from discord import app_commands
from discord.app_commands import TransformerError
from discord.ext import commands

from core.client import StellaEmojiBot
from core.converter import PersonalEmojiConverter
from core.errors import UserInputError
from core.typings import EContext, EInteraction


class ErrorCog(commands.Cog):
    def __init__(self, bot: StellaEmojiBot):
        self.bot: StellaEmojiBot = bot
        self.__original_tree_on_error = None

    async def cog_load(self) -> None:
        self.__original_tree_on_error = self.bot.tree.on_error
        self.bot.tree.on_error = self.on_tree_command_error

    async def cog_unload(self) -> None:
        self.bot.tree.on_error = self.__original_tree_on_error

    async def on_tree_command_error(self, interaction: EInteraction, error: app_commands.AppCommandError):
        intentional_error = (UserInputError,)
        error_message = str(error)
        if not isinstance(error, intentional_error):
            traceback.print_exception(error)

        if not interaction.response.is_done():
            await interaction.response.send_message(error_message, ephemeral=True)
        else:
            await interaction.followup.send(error_message, ephemeral=True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: EContext, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return

        error = getattr(error, 'original', error)
        error_message = str(error)
        intentional_error = (UserInputError,)
        if not isinstance(error, intentional_error):
            traceback.print_exception(error)
        await ctx.send(f"{error_message}", ephemeral=True)


async def setup(bot: StellaEmojiBot) -> None:
    await bot.add_cog(ErrorCog(bot))
