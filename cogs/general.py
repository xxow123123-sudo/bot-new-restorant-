import discord
from discord import app_commands
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="مسح", description="مسح عدد من الرسائل")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, العدد: app_commands.Range[int, 1, 100]):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("هذا الأمر يعمل في الشاتات النصية فقط.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=العدد)
        await interaction.followup.send(f"تم مسح {len(deleted)} رسالة.", ephemeral=True)

    @app_commands.command(name="قفل", description="قفل الشات الحالي على الأعضاء")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("هذا الأمر يعمل في الشاتات النصية فقط.", ephemeral=True)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 تم قفل الشات.")

    @app_commands.command(name="فتح", description="فتح الشات الحالي للأعضاء")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("هذا الأمر يعمل في الشاتات النصية فقط.", ephemeral=True)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 تم فتح الشات.")

async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
