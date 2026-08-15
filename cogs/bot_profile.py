import asyncio
import discord
from discord import app_commands
from discord.ext import commands


def is_image(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    return (
        content_type.startswith("image/")
        or attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    )


class ChangeNameModal(discord.ui.Modal, title="تغيير اسم البوت"):
    new_name = discord.ui.TextInput(
        label="الاسم الجديد",
        placeholder="اكتب اسم البوت الجديد",
        min_length=2,
        max_length=32,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.client.user.edit(username=str(self.new_name.value).strip())
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"تعذر تغيير اسم البوت حاليًا. قد يكون بسبب حد التغييرات في Discord.\n`{e}`",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"تم تغيير اسم البوت إلى **{self.new_name.value}**.",
            ephemeral=True,
        )


class BotSettingsView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180)
        self.bot = bot

    @discord.ui.button(label="تغيير الاسم", style=discord.ButtonStyle.primary)
    async def change_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeNameModal())

    @discord.ui.button(label="تغيير الصورة", style=discord.ButtonStyle.primary)
    async def change_avatar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "أرسل **الصورة الجديدة للبوت** في نفس الشات خلال دقيقتين.",
            ephemeral=True,
        )

        def check(message: discord.Message):
            return (
                message.author.id == interaction.user.id
                and message.channel.id == interaction.channel_id
                and len(message.attachments) > 0
                and is_image(message.attachments[0])
            )

        try:
            message = await self.bot.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            return await interaction.followup.send(
                "انتهى الوقت. اضغط **تغيير الصورة** وحاول مرة ثانية.",
                ephemeral=True,
            )

        attachment = message.attachments[0]

        try:
            image_bytes = await attachment.read()
            await self.bot.user.edit(avatar=image_bytes)
        except discord.HTTPException as e:
            return await interaction.followup.send(
                f"تعذر تغيير صورة البوت حاليًا. قد يكون بسبب حد التغييرات في Discord.\n`{e}`",
                ephemeral=True,
            )

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        await interaction.followup.send(
            "تم تغيير صورة البوت بنجاح.",
            ephemeral=True,
        )

    @discord.ui.button(label="عرض الحالي", style=discord.ButtonStyle.secondary)
    async def show_current(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = self.bot.user
        embed = discord.Embed(title="إعدادات البوت الحالية")
        embed.add_field(name="الاسم", value=user.name, inline=False)
        embed.add_field(name="ID", value=str(user.id), inline=False)
        if user.display_avatar:
            embed.set_thumbnail(url=user.display_avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class BotProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="تعديل-البوت",
        description="تغيير اسم وصورة البوت"
    )
    @app_commands.default_permissions(administrator=True)
    async def edit_bot(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="إعدادات البوت",
            description="اختر ما تريد تعديله من الأزرار بالأسفل."
        )
        await interaction.response.send_message(
            embed=embed,
            view=BotSettingsView(self.bot),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BotProfileCog(bot))
