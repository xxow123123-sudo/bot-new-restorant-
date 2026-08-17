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
# اختيار الرومات - قائمة من البوت نفسه
# =========================

def channel_label(channel):
    category = getattr(channel, "category", None)
    if category:
        return f"{category.name} / {channel.name}"
    return channel.name


class ManualChannelIdModal(discord.ui.Modal):
    def __init__(self, key: str, label: str):
        super().__init__(title=f"تعيين {label}")
        self.setting_key = key
        self.setting_label = label

        self.channel_id = discord.ui.TextInput(
            label="Channel ID",
            placeholder="الصق آيدي الروم هنا",
            required=True,
            max_length=25
        )
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "هذا الخيار يعمل داخل السيرفر فقط.",
                ephemeral=True
            )

        try:
            channel_id = int(str(self.channel_id.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                "آيدي الروم غير صحيح.",
                ephemeral=True
            )

        channel = interaction.guild.get_channel(channel_id)
        if channel is None:
            return await interaction.response.send_message(
                "ما لقيت روم بهذا الآيدي داخل السيرفر.",
                ephemeral=True
            )

        if self.setting_key == "application_ticket_category":
            if not isinstance(channel, discord.CategoryChannel):
                return await interaction.response.send_message(
                    "هذا الإعداد يحتاج **كاتقوري** وليس روم عادي.",
                    ephemeral=True
                )
        else:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
                return await interaction.response.send_message(
                    "نوع هذا الروم غير مدعوم لهذا الإعداد.",
                    ephemeral=True
                )

        await set_setting(
            interaction.guild.id,
            self.setting_key,
            str(channel.id)
        )

        mention = getattr(channel, "mention", channel.name)
        await interaction.response.send_message(
            f"✅ تم تعيين **{self.setting_label}** إلى {mention}",
            ephemeral=True
        )


class ChannelListSelect(discord.ui.Select):
    def __init__(self, key: str, label: str, channels, page: int = 0):
        self.setting_key = key
        self.setting_label = label
        self.all_channels = channels
        self.page = page

        start = page * 25
        chunk = channels[start:start + 25]

        options = []
        for channel in chunk:
            name = channel_label(channel)
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=str(channel.id),
                    description=f"ID: {channel.id}"[:100]
                )
            )

        super().__init__(
            placeholder=f"اختر {label} - صفحة {page + 1}",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        channel_id = int(self.values[0])
        channel = interaction.guild.get_channel(channel_id)

        if channel is None:
            return await interaction.response.send_message(
                "الروم لم يعد موجودًا.",
                ephemeral=True
            )

        await set_setting(
            interaction.guild.id,
            self.setting_key,
            str(channel.id)
        )

        mention = getattr(channel, "mention", channel.name)
        await interaction.response.send_message(
            f"✅ تم تعيين **{self.setting_label}** إلى {mention}",
            ephemeral=True
        )


class ChannelListView(discord.ui.View):
    def __init__(self, key: str, label: str, channels, page: int = 0):
        super().__init__(timeout=180)
        self.key = key
        self.label = label
        self.channels = channels
        self.page = page
        self.max_page = max(0, (len(channels) - 1) // 25)

        self.add_item(ChannelListSelect(key, label, channels, page))

        self.previous.disabled = page <= 0
        self.next.disabled = page >= self.max_page

    @discord.ui.button(label="السابق", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_page = max(0, self.page - 1)
        await interaction.response.edit_message(
            content=f"اختر **{self.label}**:",
            view=ChannelListView(self.key, self.label, self.channels, new_page)
        )

    @discord.ui.button(label="التالي", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        new_page = min(self.max_page, self.page + 1)
        await interaction.response.edit_message(
            content=f"اختر **{self.label}**:",
            view=ChannelListView(self.key, self.label, self.channels, new_page)
        )

    @discord.ui.button(label="إدخال ID", style=discord.ButtonStyle.primary)
    async def manual_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ManualChannelIdModal(self.key, self.label)
        )


class EmptyChannelListView(discord.ui.View):
    def __init__(self, key: str, label: str):
        super().__init__(timeout=180)
        self.key = key
        self.label = label

    @discord.ui.button(label="إدخال ID", style=discord.ButtonStyle.primary)
    async def manual_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ManualChannelIdModal(self.key, self.label)
        )


class ChannelSettingSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key)
            for key, label in CHANNEL_KEYS.items()
        ]

        super().__init__(
            placeholder="اختر إعداد الروم الذي تريد تغييره",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "هذا الخيار يعمل داخل السيرفر فقط.",
                ephemeral=True
            )

        key = self.values[0]
        label = CHANNEL_KEYS[key]

        if key == "application_ticket_category":
            channels = list(interaction.guild.categories)
        else:
            # نبني القائمة من قنوات السيرفر بدل ChannelSelect التلقائي.
            # القنوات النصية أولاً، ثم باقي الأنواع التي قد تستخدمها الإدارة.
            channels = list(interaction.guild.text_channels)

            extra = [
                c for c in interaction.guild.channels
                if isinstance(c, (discord.VoiceChannel, discord.StageChannel, discord.ForumChannel))
                and c not in channels
            ]
            channels.extend(extra)

        channels.sort(key=lambda c: (getattr(c, "position", 0), c.name.lower()))

        if not channels:
            return await interaction.response.send_message(
                f"ما لقيت رومات متاحة لـ **{label}**.\nتقدر تدخل الآيدي يدويًا:",
                view=EmptyChannelListView(key, label),
                ephemeral=True
            )

        await interaction.response.send_message(
            f"اختر **{label}** من القائمة، وإذا ما لقيته استخدم **إدخال ID**:",
            view=ChannelListView(key, label, channels, 0),
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