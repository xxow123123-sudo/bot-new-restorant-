import discord
from discord import app_commands
from discord.ext import commands

from database.db import set_setting, get_all_settings

ADMIN_ROLE_ID = 1538165468228223077

async def settings_admin_allowed(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    configured = await __import__("database.db", fromlist=["get_setting"]).get_setting(interaction.guild.id, "admin_role")
    role_id = int(configured) if configured else ADMIN_ROLE_ID
    return any(r.id == role_id for r in interaction.user.roles)



# =========================
# إعدادات الرومات
# =========================

CHANNEL_KEYS = {
    "attendance_log": "لوق الدخول والخروج",
    "invoice_log": "لوق الفواتير",
    "application_review": "طلبات التقديم",
    "application_ticket_category": "كاتقوري تذاكر المقبولين",
    "vacation_review": "طلبات الإجازات",
    "hr_review": "طلبات الموارد البشرية",
    "admin_log": "اللوق الإداري",
    "resignation_review": "طلبات الاستقالات",
    "employee_database_channel": "قاعدة بيانات الموظفين",
}


# =========================
# إعدادات الرتب
# =========================

ROLE_KEYS = {
    "employee_role": "رتبة الموظف",
    "vacation_role": "رتبة الإجازة",
    "admin_role": "رتبة الإدارة",
}


# =========================
# اختيار الروم نفسه
# =========================

class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, key: str, label: str):
        self.setting_key = key
        self.setting_label = label

        # كاتقوري تذاكر المقبولين لازم يكون Category فقط.
        if key == "application_ticket_category":
            super().__init__(
                placeholder=f"اختر {label}",
                channel_types=[discord.ChannelType.category],
                min_values=1,
                max_values=1,
            )
        else:
            # بدون channel_types عشان Discord يعرض كل الرومات المتاحة.
            super().__init__(
                placeholder=f"اختر {label}",
                min_values=1,
                max_values=1,
            )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "هذا الخيار يعمل داخل السيرفر فقط.",
                ephemeral=True
            )
            return

        channel = self.values[0]

        await set_setting(
            interaction.guild.id,
            self.setting_key,
            str(channel.id)
        )

        mention = getattr(channel, "mention", f"#{channel.name}")
        await interaction.response.send_message(
            f"✅ تم تعيين **{self.setting_label}** إلى {mention}",
            ephemeral=True
        )


class ChannelPickerView(discord.ui.View):
    def __init__(self, key: str, label: str):
        super().__init__(timeout=180)
        self.add_item(ChannelPicker(key, label))


# =========================
# اختيار نوع الروم
# =========================

class ChannelSettingSelect(discord.ui.Select):
    def __init__(self):
        options = []

        for key, label in CHANNEL_KEYS.items():
            options.append(
                discord.SelectOption(
                    label=label,
                    value=key
                )
            )

        super().__init__(
            placeholder="اختر إعداد الروم الذي تريد تغييره",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        label = CHANNEL_KEYS[key]

        await interaction.response.send_message(
            f"اختر الروم الخاص بـ **{label}**:",
            view=ChannelPickerView(key, label),
            ephemeral=True
        )


class ChannelSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ChannelSettingSelect())


# =========================
# اختيار الرتبة نفسها
# =========================

class RolePicker(discord.ui.RoleSelect):
    def __init__(self, key: str, label: str):
        self.setting_key = key
        self.setting_label = label

        super().__init__(
            placeholder=f"اختر {label}",
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "هذا الخيار يعمل داخل السيرفر فقط.",
                ephemeral=True
            )
            return

        role = self.values[0]

        await set_setting(
            interaction.guild.id,
            self.setting_key,
            str(role.id)
        )

        await interaction.response.send_message(
            f"✅ تم تعيين **{self.setting_label}** إلى {role.mention}",
            ephemeral=True
        )


class RolePickerView(discord.ui.View):
    def __init__(self, key: str, label: str):
        super().__init__(timeout=180)
        self.add_item(RolePicker(key, label))


# =========================
# اختيار نوع الرتبة
# =========================

class RoleSettingSelect(discord.ui.Select):
    def __init__(self):
        options = []

        for key, label in ROLE_KEYS.items():
            options.append(
                discord.SelectOption(
                    label=label,
                    value=key
                )
            )

        super().__init__(
            placeholder="اختر إعداد الرتبة الذي تريد تغييره",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        label = ROLE_KEYS[key]

        await interaction.response.send_message(
            f"اختر الرتبة الخاصة بـ **{label}**:",
            view=RolePickerView(key, label),
            ephemeral=True
        )


class RoleSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(RoleSettingSelect())


# =========================
# القائمة الرئيسية
# =========================

class SettingsTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="الرومات",
                value="channels",
                emoji="📁"
            ),
            discord.SelectOption(
                label="الرتب",
                value="roles",
                emoji="🏷️"
            ),
            discord.SelectOption(
                label="عرض الإعدادات",
                value="show",
                emoji="⚙️"
            ),
        ]

        super().__init__(
            placeholder="اختر نوع الإعداد",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "هذا الأمر يعمل داخل السيرفر فقط.",
                ephemeral=True
            )
            return

        selected = self.values[0]

        # الرومات
        if selected == "channels":
            await interaction.response.send_message(
                "📁 اختر إعداد الروم الذي تريد تغييره:",
                view=ChannelSettingsView(),
                ephemeral=True
            )

        # الرتب
        elif selected == "roles":
            await interaction.response.send_message(
                "🏷️ اختر إعداد الرتبة الذي تريد تغييره:",
                view=RoleSettingsView(),
                ephemeral=True
            )

        # عرض الإعدادات
        elif selected == "show":
            data = await get_all_settings(interaction.guild.id)

            if not data:
                await interaction.response.send_message(
                    "❌ لا توجد إعدادات محفوظة حتى الآن.",
                    ephemeral=True
                )
                return

            lines = []

            # الرومات
            lines.append("**📁 الرومات**")

            for key, label in CHANNEL_KEYS.items():
                value = data.get(key)

                if value:
                    channel = interaction.guild.get_channel(int(value))

                    if channel:
                        lines.append(
                            f"• {label}: {channel.mention}"
                        )
                    else:
                        lines.append(
                            f"• {label}: `الروم غير موجود`"
                        )
                else:
                    lines.append(
                        f"• {label}: `غير محدد`"
                    )

            lines.append("")
            lines.append("**🏷️ الرتب**")

            # الرتب
            for key, label in ROLE_KEYS.items():
                value = data.get(key)

                if value:
                    role = interaction.guild.get_role(int(value))

                    if role:
                        lines.append(
                            f"• {label}: {role.mention}"
                        )
                    else:
                        lines.append(
                            f"• {label}: `الرتبة غير موجودة`"
                        )
                else:
                    lines.append(
                        f"• {label}: `غير محدد`"
                    )

            await interaction.response.send_message(
                "\n".join(lines),
                ephemeral=True
            )


class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(SettingsTypeSelect())


# =========================
# Cog
# =========================

class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="settings",
        description="تعديل رومات ورتب البوت"
    )
    async def settings(
        self,
        interaction: discord.Interaction
    ):
        if not await settings_admin_allowed(interaction):
            return await interaction.response.send_message("هذا الأمر مخصص للإدارة فقط.", ephemeral=True)
        await interaction.response.send_message(
            "⚙️ **لوحة إعدادات البوت**\nاختر الشيء الذي تريد تعديله:",
            view=SettingsView(),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))