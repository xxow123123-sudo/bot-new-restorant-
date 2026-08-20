import secrets
from datetime import datetime, timezone

import discord
from discord.ext import commands

from database.db import (
    get_external_application,
    get_pending_external_applications,
    set_external_application_status,
    claim_acceptance_code,
    release_acceptance_code,
    finalize_acceptance_code,
    get_setting,
)


async def admin_allowed(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("هذا الخيار يعمل داخل السيرفر فقط.", ephemeral=True)
        return False

    if interaction.user.guild_permissions.administrator:
        return True

    role_id = await get_setting(interaction.guild.id, "admin_role")
    if role_id and any(role.id == int(role_id) for role in interaction.user.roles):
        return True

    await interaction.response.send_message("هذا الخيار مخصص للإدارة فقط.", ephemeral=True)
    return False


def application_status(row):
    # external_applications column index: 10=status
    return row[10] if row else None


def make_acceptance_code() -> str:
    return f"BM-{secrets.randbelow(900000) + 100000}"


class ExternalApplicationReviewView(discord.ui.View):
    def __init__(self, application_id: int):
        super().__init__(timeout=None)
        self.application_id = int(application_id)

        accept = discord.ui.Button(
            label="قبول",
            style=discord.ButtonStyle.success,
            custom_id=f"webapp:accept:{self.application_id}",
        )
        reject = discord.ui.Button(
            label="رفض",
            style=discord.ButtonStyle.danger,
            custom_id=f"webapp:reject:{self.application_id}",
        )
        accept.callback = self.accept_application
        reject.callback = self.reject_application
        self.add_item(accept)
        self.add_item(reject)

    async def accept_application(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        row = await get_external_application(self.application_id)
        if not row:
            return await interaction.response.send_message("الطلب غير موجود.", ephemeral=True)
        if application_status(row) != "pending":
            return await interaction.response.send_message("تمت مراجعة هذا الطلب مسبقًا.", ephemeral=True)

        # Very low collision probability. UNIQUE in SQLite is an extra safeguard.
        for _ in range(5):
            code = make_acceptance_code()
            try:
                await set_external_application_status(
                    self.application_id,
                    "accepted",
                    datetime.now(timezone.utc).isoformat(),
                    interaction.user.id,
                    code,
                )
                break
            except Exception:
                code = None
        if not code:
            return await interaction.response.send_message("تعذر إنشاء رقم قبول. حاول مرة ثانية.", ephemeral=True)

        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(title="طلب تقديم من الموقع")
        embed.add_field(
            name="الحالة",
            value=f"تم القبول بواسطة {interaction.user.mention}",
            inline=False,
        )
        if interaction.message:
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            "تم قبول الطلب. رقم القبول ورابط السيرفر سيظهران للمتقدم في الموقع.",
            ephemeral=True,
        )

    async def reject_application(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        row = await get_external_application(self.application_id)
        if not row:
            return await interaction.response.send_message("الطلب غير موجود.", ephemeral=True)
        if application_status(row) != "pending":
            return await interaction.response.send_message("تمت مراجعة هذا الطلب مسبقًا.", ephemeral=True)

        await set_external_application_status(
            self.application_id,
            "rejected",
            datetime.now(timezone.utc).isoformat(),
            interaction.user.id,
        )

        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed(title="طلب تقديم من الموقع")
        embed.add_field(
            name="الحالة",
            value=f"تم الرفض بواسطة {interaction.user.mention}",
            inline=False,
        )
        if interaction.message:
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message("تم رفض الطلب.", ephemeral=True)


class JoinCodeModal(discord.ui.Modal, title="طلب انضمام"):
    code = discord.ui.TextInput(
        label="رقم القبول",
        placeholder="مثال: BM-583214",
        required=True,
        min_length=6,
        max_length=20,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("هذا الخيار يعمل داخل السيرفر فقط.", ephemeral=True)

        category_id = await get_setting(interaction.guild.id, "application_ticket_category")
        category = interaction.guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "كاتقوري تذاكر المقبولين غير مضبوط. تواصل مع الإدارة.",
                ephemeral=True,
            )

        code = str(self.code.value).strip().upper()
        app_id, result = await claim_acceptance_code(
            interaction.guild.id,
            code,
            interaction.user.id,
        )

        if result != "ok":
            messages = {
                "invalid": "رقم القبول غير صحيح أو غير مرتبط بحساب Discord الخاص بك.",
                "not_accepted": "هذا الطلب غير مقبول.",
                "used": "تم استخدام رقم القبول مسبقًا.",
            }
            return await interaction.response.send_message(messages.get(result, "تعذر التحقق من رقم القبول."), ephemeral=True)

        guild = interaction.guild
        applicant = interaction.user
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            applicant: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
            ),
        }

        admin_role_id = await get_setting(guild.id, "admin_role")
        if admin_role_id:
            admin_role = guild.get_role(int(admin_role_id))
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        safe_name = "".join(
            c for c in applicant.display_name.lower().replace(" ", "-")
            if c.isalnum() or c == "-"
        )[:35] or str(applicant.id)

        try:
            ticket = await guild.create_text_channel(
                name=f"تقديم-{safe_name}",
                category=category,
                overwrites=overwrites,
                reason=f"طلب انضمام من الموقع #{app_id}",
            )
        except discord.HTTPException:
            await release_acceptance_code(app_id, applicant.id)
            return await interaction.response.send_message(
                "تعذر فتح التذكرة. تواصل مع الإدارة.",
                ephemeral=True,
            )

        try:
            from cogs.panels import TicketControlView

            await ticket.send(
                content=applicant.mention,
                embed=discord.Embed(
                    title="استكمال إجراءات التوظيف",
                    description=(
                        f"أهلًا {applicant.mention}\n"
                        "تم التحقق من رقم قبولك بنجاح. استكمل إجراءاتك مع الإدارة هنا."
                    ),
                    timestamp=datetime.now(timezone.utc),
                ),
                view=TicketControlView(),
            )
            await finalize_acceptance_code(app_id, applicant.id)
        except Exception:
            await release_acceptance_code(app_id, applicant.id)
            try:
                await ticket.delete(reason="فشل إكمال طلب الانضمام")
            except discord.HTTPException:
                pass
            raise

        await interaction.response.send_message(
            f"تم التحقق من رقم القبول وفتح تذكرتك: {ticket.mention}",
            ephemeral=True,
        )


class JoinApplicationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="طلب انضمام",
            style=discord.ButtonStyle.success,
            custom_id="panel:web_join",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(JoinCodeModal())


class ExternalApplicationsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Re-register review buttons for pending website applications after a restart.
        rows = await get_pending_external_applications()
        for (application_id,) in rows:
            self.bot.add_view(ExternalApplicationReviewView(application_id))


async def setup(bot: commands.Bot):
    await bot.add_cog(ExternalApplicationsCog(bot))
