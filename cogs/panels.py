from cogs.external_applications import JoinApplicationButton
from datetime import datetime, timezone
import asyncio
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands

from database.db import (
    get_setting, get_points, get_active_attendance, get_all_active_attendance,
    start_attendance, finish_attendance, force_finish_attendance, add_invoice,
    add_points, set_points, reset_all_points, add_task, get_all_employee_stats, get_employee_stats,
    save_employee_profile, get_employee_profile, search_employee_profiles, list_employee_profiles, remove_employee_profile,
)

def format_points(value: float) -> str:
    value = round(float(value), 2)
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")

def format_duration(seconds: int) -> str:
    hours, rem = divmod(max(0, int(seconds)), 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} ساعة و {minutes} دقيقة"
    if hours:
        return f"{hours} ساعة"
    return f"{minutes} دقيقة"

async def employee_allowed(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
        return False
    role_id = await get_setting(interaction.guild.id, "employee_role")
    if not role_id:
        return True
    if any(role.id == int(role_id) for role in interaction.user.roles):
        return True
    await interaction.response.send_message("هذا الزر مخصص للموظفين فقط.", ephemeral=True)
    return False

ADMIN_ROLE_ID = 1538165468228223077

async def admin_allowed(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    role_id = await get_setting(interaction.guild.id, "admin_role")
    role_id = int(role_id) if role_id else ADMIN_ROLE_ID
    if any(role.id == role_id for role in interaction.user.roles):
        return True
    await interaction.response.send_message("هذا الزر مخصص للإدارة فقط.", ephemeral=True)
    return False

async def request_image(interaction: discord.Interaction, prompt: str):
    await interaction.response.send_message(f"{prompt}\nأرسل الصورة الآن في نفس الشات خلال دقيقتين.", ephemeral=True)
    def check(message: discord.Message):
        if message.author.id != interaction.user.id or message.channel.id != interaction.channel_id or not message.attachments:
            return False
        a = message.attachments[0]
        ctype = a.content_type or ""
        return ctype.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
    try:
        message = await interaction.client.wait_for("message", timeout=120, check=check)
        return message, message.attachments[0]
    except asyncio.TimeoutError:
        await interaction.followup.send("انتهى الوقت. اضغط الزر وحاول مرة ثانية.", ephemeral=True)
        return None, None

async def get_log_channel(interaction: discord.Interaction, setting_key: str):
    if not interaction.guild:
        return None
    channel_id = await get_setting(interaction.guild.id, setting_key)
    if not channel_id:
        return None
    channel = interaction.guild.get_channel(int(channel_id))
    return channel if isinstance(channel, discord.TextChannel) else None

async def send_image_to_log(log_channel, attachment, embed):
    image_bytes = await attachment.read()
    filename = attachment.filename or "image.png"
    file = discord.File(BytesIO(image_bytes), filename=filename)
    embed.set_image(url=f"attachment://{filename}")
    msg = await log_channel.send(embed=embed, file=file)

    # بعض رسائل Discord تعرض الصورة داخل الـ embed بدون أن ترجعها في
    # msg.attachments. لا نوقف العملية بسبب ذلك؛ نستخدم رابط الرسالة كمرجع.
    if msg.attachments:
        return msg.attachments[0].url
    return msg.jump_url

async def send_admin_log(interaction, title, description):
    channel = await get_log_channel(interaction, "admin_log")
    if channel:
        embed = discord.Embed(title=title, description=description, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="الإداري", value=interaction.user.mention, inline=False)
        await channel.send(embed=embed)

class CheckInButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="تسجيل دخول", emoji="🟢", style=discord.ButtonStyle.success, custom_id="employee:checkin")
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        if await get_active_attendance(interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("أنت مسجل دخول بالفعل.", ephemeral=True)
        log_channel = await get_log_channel(interaction, "attendance_log")
        if not log_channel:
            return await interaction.response.send_message("روم لوق الدخول والخروج غير محدد. خلي الإدارة تضبطه من `/settings`.", ephemeral=True)
        source_message, attachment = await request_image(interaction, "أرسل **صورة المخزون** لتأكيد تسجيل الدخول.")
        if not attachment: return
        now = datetime.now(timezone.utc)
        embed = discord.Embed(title="🟢 تسجيل دخول", timestamp=now)
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="الوقت", value=f"<t:{int(now.timestamp())}:F>", inline=False)
        try:
            log_url = await send_image_to_log(log_channel, attachment, embed)
        except discord.HTTPException:
            return await interaction.followup.send("تعذر رفع الصورة إلى اللوق.", ephemeral=True)
        # إذا وصل اللوق بنجاح نسجل الدوام حتى لو Discord لم يرجع رابط attachment.
        log_url = log_url or source_message.attachments[0].url
        try:
            await start_attendance(interaction.guild.id, interaction.user.id, now.isoformat(), log_url)
        except Exception as exc:
            print(f"❌ Check-in database error: {type(exc).__name__}: {exc}")
            return await interaction.followup.send(
                "تم رفع الصورة للوق لكن تعذر تسجيل الدخول في قاعدة البيانات. راجع Console البوت.",
                ephemeral=True
            )
        try: await source_message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass
        await interaction.followup.send("تم تسجيل دخولك بنجاح.", ephemeral=True)

class CheckOutButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="تسجيل خروج", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="employee:checkout")
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        active = await get_active_attendance(interaction.guild.id, interaction.user.id)
        if not active: return await interaction.response.send_message("أنت غير مسجل دخول حاليًا.", ephemeral=True)
        log_channel = await get_log_channel(interaction, "attendance_log")
        if not log_channel:
            return await interaction.response.send_message("روم لوق الدخول والخروج غير محدد. خلي الإدارة تضبطه من `/settings`.", ephemeral=True)
        source_message, attachment = await request_image(interaction, "أرسل **صورة المخزون** لتأكيد تسجيل الخروج.")
        if not attachment: return
        session_id, check_in_at, _ = active
        started = datetime.fromisoformat(check_in_at)
        now = datetime.now(timezone.utc)
        worked = max(0, int((now - started).total_seconds()))
        earned = round((worked / 3600) * 5, 2)
        embed = discord.Embed(title="🔴 تسجيل خروج", timestamp=now)
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="مدة العمل", value=format_duration(worked), inline=True)
        embed.add_field(name="النقاط المكتسبة", value=f"{format_points(earned)} نقطة", inline=True)
        embed.add_field(name="وقت الخروج", value=f"<t:{int(now.timestamp())}:F>", inline=False)
        try: log_url = await send_image_to_log(log_channel, attachment, embed)
        except discord.HTTPException: return await interaction.followup.send("تعذر رفع الصورة إلى اللوق.", ephemeral=True)
        log_url = log_url or source_message.attachments[0].url
        try:
            await finish_attendance(session_id, interaction.guild.id, interaction.user.id, now.isoformat(), log_url, worked, earned)
        except Exception as exc:
            print(f"❌ Check-out database error: {type(exc).__name__}: {exc}")
            return await interaction.followup.send(
                "تم رفع الصورة للوق لكن تعذر تسجيل الخروج في قاعدة البيانات. راجع Console البوت.",
                ephemeral=True
            )
        try: await source_message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass
        await interaction.followup.send(f"تم تسجيل خروجك. حصلت على **{format_points(earned)} نقطة**.", ephemeral=True)

class InvoiceButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="إنشاء فاتورة", emoji="🧾", style=discord.ButtonStyle.primary, custom_id="employee:invoice")
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        if not await get_active_attendance(interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("لازم تكون مسجل دخول عشان تنشئ فاتورة.", ephemeral=True)
        log_channel = await get_log_channel(interaction, "invoice_log")
        if not log_channel:
            return await interaction.response.send_message("روم لوق الفواتير غير محدد. خلي الإدارة تضبطه من `/settings`.", ephemeral=True)
        source_message, attachment = await request_image(interaction, "أرسل **صورة الفاتورة** الآن.")
        if not attachment: return
        now = datetime.now(timezone.utc)
        embed = discord.Embed(title="🧾 فاتورة جديدة", timestamp=now)
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="النقاط", value="+1 نقطة", inline=False)
        try: log_url = await send_image_to_log(log_channel, attachment, embed)
        except discord.HTTPException: return await interaction.followup.send("تعذر رفع صورة الفاتورة إلى اللوق.", ephemeral=True)
        log_url = log_url or source_message.attachments[0].url
        await add_invoice(interaction.guild.id, interaction.user.id, now.isoformat(), log_url)
        try: await source_message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass
        await interaction.followup.send("تم احتساب الفاتورة وإضافة **1 نقطة**.", ephemeral=True)

class MyPointsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="نقاطي", emoji="⭐", style=discord.ButtonStyle.secondary, custom_id="employee:points")
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        points = await get_points(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(f"**{format_points(points)} نقطة**", ephemeral=True)

class EmployeePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CheckInButton()); self.add_item(CheckOutButton()); self.add_item(InvoiceButton()); self.add_item(MyPointsButton())

class MemberPicker(discord.ui.UserSelect):
    def __init__(self, action):
        self.action = action
        super().__init__(placeholder="اختر الموظف", min_values=1, max_values=1)
    async def callback(self, interaction):
        member = self.values[0]
        if self.action == "force":
            active = await get_active_attendance(interaction.guild.id, member.id)
            if not active: return await interaction.response.send_message("هذا الموظف غير مسجل دخول.", ephemeral=True)
            session_id, check_in_at, _ = active
            now = datetime.now(timezone.utc)
            started = datetime.fromisoformat(check_in_at)
            worked = max(0, int((now-started).total_seconds()))
            earned = round((worked/3600)*5, 2)
            await force_finish_attendance(session_id, interaction.guild.id, member.id, now.isoformat(), worked, earned, interaction.user.id)
            await interaction.response.send_message(f"تم تسجيل خروج {member.mention} إجباريًا.\nالمدة: **{format_duration(worked)}**\nالنقاط: **{format_points(earned)}**", ephemeral=True)
            await send_admin_log(interaction, "🔴 خروج إجباري", f"الموظف: {member.mention}\nالمدة: {format_duration(worked)}\nالنقاط: {format_points(earned)}")
        elif self.action in ("add", "remove"):
            await interaction.response.send_modal(PointsModal(member.id, member.mention, self.action))
        elif self.action == "task":
            await interaction.response.send_modal(TaskModal(member.id, member.mention))
        elif self.action == "fire":
            await interaction.response.send_modal(FireEmployeeModal(member.id, member.mention))
        elif self.action == "stats":
            stats = await get_employee_stats(interaction.guild.id, member.id)
            points, seconds, invoices, tasks = stats
            active = await get_active_attendance(interaction.guild.id, member.id)
            status = "🟢 مسجل دخول" if active else "🔴 غير مسجل"
            embed = discord.Embed(title=f"إحصائيات {member.display_name}")
            embed.add_field(name="النقاط", value=format_points(points))
            embed.add_field(name="ساعات العمل", value=format_duration(seconds))
            embed.add_field(name="الفواتير", value=str(invoices))
            embed.add_field(name="المهام", value=str(tasks))
            embed.add_field(name="الحالة", value=status, inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.action == "reset":
            old = await get_points(interaction.guild.id, member.id)
            await set_points(interaction.guild.id, member.id, 0, "تصفير نقاط موظف", datetime.now(timezone.utc).isoformat(), interaction.user.id)
            await interaction.response.send_message(f"تم تصفير نقاط {member.mention}. كانت **{format_points(old)}** وأصبحت **0**.", ephemeral=True)
            await send_admin_log(interaction, "♻️ تصفير نقاط موظف", f"الموظف: {member.mention}\nالنقاط السابقة: {format_points(old)}\nالنقاط الجديدة: 0")

class MemberPickerView(discord.ui.View):
    def __init__(self, action):
        super().__init__(timeout=120)
        self.add_item(MemberPicker(action))

class TaskModal(discord.ui.Modal):
    def __init__(self, user_id, mention):
        super().__init__(title="احتساب مهمة")
        self.user_id = user_id
        self.mention = mention
        self.reason = discord.ui.TextInput(
            label="اسم أو سبب المهمة",
            placeholder="مثال: ترتيب المخزون",
            required=True,
            max_length=200
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction):
        now = datetime.now(timezone.utc)
        await add_task(
            interaction.guild.id,
            self.user_id,
            now.isoformat(),
            interaction.user.id,
            self.reason.value
        )
        new_total = await get_points(interaction.guild.id, self.user_id)
        await interaction.response.send_message(
            f"تم احتساب مهمة لـ {self.mention}.\\nتمت إضافة **7 نقاط**.\\nنقاطه الآن: **{format_points(new_total)}**",
            ephemeral=True
        )
        await send_admin_log(
            interaction,
            "📋 احتساب مهمة",
            f"الموظف: {self.mention}\\nالمهمة: {self.reason.value}\\nالنقاط: +7\\nالرصيد الجديد: {format_points(new_total)}"
        )

class PointsModal(discord.ui.Modal):
    def __init__(self, user_id, mention, action):
        super().__init__(title="زيادة نقاط" if action == "add" else "خصم نقاط")
        self.user_id = user_id; self.mention = mention; self.action = action
        self.amount = discord.ui.TextInput(label="عدد النقاط", placeholder="مثال: 10", required=True, max_length=10)
        self.reason = discord.ui.TextInput(label="السبب", placeholder="اكتب سبب العملية", required=True, max_length=200)
        self.add_item(self.amount); self.add_item(self.reason)
    async def on_submit(self, interaction):
        try:
            amount = abs(float(str(self.amount.value).replace(",", ".")))
            if amount == 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("اكتب عدد نقاط صحيح أكبر من صفر.", ephemeral=True)
        signed = amount if self.action == "add" else -amount
        await add_points(interaction.guild.id, self.user_id, signed, self.reason.value, datetime.now(timezone.utc).isoformat(), interaction.user.id)
        new_total = await get_points(interaction.guild.id, self.user_id)
        verb = "إضافة" if self.action == "add" else "خصم"
        await interaction.response.send_message(f"تم {verb} **{format_points(amount)}** نقطة لـ {self.mention}.\nنقاطه الآن: **{format_points(new_total)}**", ephemeral=True)
        await send_admin_log(interaction, f"⭐ {verb} نقاط", f"الموظف: {self.mention}\nالقيمة: {format_points(signed)}\nالسبب: {self.reason.value}\nالرصيد الجديد: {format_points(new_total)}")

class AdminButton(discord.ui.Button):
    def __init__(self, label, custom_id, action, style=discord.ButtonStyle.secondary):
        self.action = action
        super().__init__(label=label, custom_id=custom_id, style=style)
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        if self.action in ("force","add","remove","task","stats","reset","fire"):
            labels = {"force":"اختر الموظف لتسجيل خروجه إجباريًا:", "add":"اختر الموظف لزيادة نقاطه:", "remove":"اختر الموظف لخصم نقاطه:", "task":"اختر الموظف لاحتساب مهمة له:", "stats":"اختر الموظف لعرض إحصائياته:", "reset":"اختر الموظف لتصفير نقاطه:", "fire":"اختر الموظف الذي تريد فصله:"}
            return await interaction.response.send_message(labels[self.action], view=MemberPickerView(self.action), ephemeral=True)
        if self.action == "active":
            rows = await get_all_active_attendance(interaction.guild.id)
            if not rows: return await interaction.response.send_message("لا يوجد موظفون مسجلون دخول الآن.", ephemeral=True)
            now = datetime.now(timezone.utc)
            lines = []
            for uid, started_at in rows:
                member = interaction.guild.get_member(uid)
                name = member.mention if member else f"<@{uid}>"
                seconds = int((now-datetime.fromisoformat(started_at)).total_seconds())
                lines.append(f"• {name} — {format_duration(seconds)}")
            return await interaction.response.send_message("**🟢 المسجلون دخول الآن**\n" + "\n".join(lines[:40]), ephemeral=True)
        if self.action == "all":
            rows = await get_all_employee_stats(interaction.guild.id)
            if not rows: return await interaction.response.send_message("لا توجد إحصائيات موظفين حتى الآن.", ephemeral=True)
            lines = []
            for i, (uid, points, seconds, invoices, tasks) in enumerate(rows[:30], 1):
                member = interaction.guild.get_member(uid)
                name = member.mention if member else f"<@{uid}>"
                lines.append(f"**#{i}** {name} — **{format_points(points)} نقطة** | {format_duration(seconds)} | {invoices} فاتورة | {tasks} مهمة")
            return await interaction.response.send_message("**📊 ترتيب الموظفين حسب النقاط**\n" + "\n".join(lines), ephemeral=True)
        if self.action == "reset_all":
            return await interaction.response.send_message("⚠️ هل أنت متأكد من تصفير نقاط **جميع الموظفين**؟", view=ConfirmResetAllView(), ephemeral=True)

class ConfirmResetAllView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    @discord.ui.button(label="تأكيد التصفير", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if not await admin_allowed(interaction): return
        count = await reset_all_points(interaction.guild.id, datetime.now(timezone.utc).isoformat(), interaction.user.id)
        await interaction.response.edit_message(content=f"✅ تم تصفير نقاط جميع الموظفين. عدد السجلات: **{count}**", view=None)
        await send_admin_log(interaction, "♻️ تصفير جميع النقاط", f"تم تصفير نقاط جميع الموظفين.\nعدد السجلات: {count}")
    @discord.ui.button(label="إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content="تم إلغاء العملية.", view=None)

class AdminPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminButton("تسجيل خروج إجباري","admin:force_checkout","force",discord.ButtonStyle.danger))
        self.add_item(AdminButton("زيادة نقاط","admin:add_points","add",discord.ButtonStyle.success))
        self.add_item(AdminButton("خصم نقاط","admin:remove_points","remove",discord.ButtonStyle.danger))
        self.add_item(AdminButton("احتساب مهمة","admin:add_task","task",discord.ButtonStyle.success))
        self.add_item(AdminButton("المسجلون دخول الآن","admin:active","active"))
        self.add_item(AdminButton("إحصائيات الجميع","admin:stats_all","all"))
        self.add_item(AdminButton("إحصائيات موظف","admin:stats_one","stats"))
        self.add_item(AdminButton("تصفير الجميع","admin:reset_all","reset_all",discord.ButtonStyle.danger))
        self.add_item(AdminButton("تصفير موظف","admin:reset_one","reset",discord.ButtonStyle.danger))
        self.add_item(AdminButton("فصل موظف","admin:fire_employee","fire",discord.ButtonStyle.danger))

class ApplicationModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="استبيان التقديم")

        self.name_input = discord.ui.TextInput(
            label="اسمك",
            placeholder="اكتب اسمك",
            required=True,
            max_length=50
        )
        self.age_input = discord.ui.TextInput(
            label="عمرك",
            placeholder="اكتب عمرك",
            required=True,
            max_length=3
        )
        self.reason_input = discord.ui.TextInput(
            label="سبب التقديم",
            placeholder="اكتب سبب تقديمك",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=500
        )
        self.hours_input = discord.ui.TextInput(
            label="كم تقدر تشتغل ساعة باليوم؟",
            placeholder="مثال: 3 ساعات",
            required=True,
            max_length=50
        )
        self.rules_input = discord.ui.TextInput(
            label="هل قرأت القوانين وطريقة العمل؟",
            placeholder="نعم / لا",
            required=True,
            max_length=20
        )

        self.add_item(self.name_input)
        self.add_item(self.age_input)
        self.add_item(self.reason_input)
        self.add_item(self.hours_input)
        self.add_item(self.rules_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "التقديم يعمل داخل السيرفر فقط.",
                ephemeral=True
            )

        review_id = await get_setting(interaction.guild.id, "application_review")
        if not review_id:
            return await interaction.response.send_message(
                "روم مراجعة التقديم غير محدد. خلي الإدارة تضبطه من `/settings`.",
                ephemeral=True
            )

        review_channel = interaction.guild.get_channel(int(review_id))
        if not isinstance(review_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "روم مراجعة التقديم المحدد غير صالح.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📝 طلب تقديم جديد",
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="المتقدم", value=interaction.user.mention, inline=False)
        embed.add_field(name="اسمك", value=self.name_input.value, inline=False)
        embed.add_field(name="عمرك", value=self.age_input.value, inline=False)
        embed.add_field(name="سبب التقديم", value=self.reason_input.value, inline=False)
        embed.add_field(name="كم تقدر تشتغل ساعة باليوم؟", value=self.hours_input.value, inline=False)
        embed.add_field(name="هل قرأت كامل قوانين العمل وطريقة العمل؟", value=self.rules_input.value, inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await review_channel.send(
            embed=embed,
            view=ApplicationReviewView(interaction.user.id)
        )

        await interaction.response.send_message(
            "✅ تم إرسال تقديمك للإدارة بنجاح.",
            ephemeral=True
        )


class ApplicationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="تقديم",
            emoji="📝",
            style=discord.ButtonStyle.primary,
            custom_id="panel:application"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ApplicationModal())


class ApplicationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ApplicationButton())
        self.add_item(JoinApplicationButton())


class ConfirmCloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="تأكيد الإغلاق", emoji="🔒", style=discord.ButtonStyle.danger)
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction):
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "هذا الزر يعمل داخل تذكرة فقط.",
                ephemeral=True
            )

        await interaction.response.edit_message(
            content="🔒 سيتم إغلاق التذكرة خلال **5 ثوانٍ**...",
            view=None
        )

        await send_admin_log(
            interaction,
            "🔒 إغلاق تذكرة تقديم",
            f"التذكرة: `{channel.name}`\nالروم: {channel.mention}"
        )

        await asyncio.sleep(5)

        try:
            await channel.delete(reason=f"إغلاق تذكرة بواسطة {interaction.user}")
        except discord.Forbidden:
            try:
                await interaction.user.send(
                    "تعذر حذف التذكرة لأن البوت لا يملك صلاحية **Manage Channels**."
                )
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            pass

    @discord.ui.button(label="إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction):
            return
        await interaction.response.edit_message(
            content="تم إلغاء إغلاق التذكرة.",
            view=None
        )


class CloseTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="إغلاق التذكرة",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id="application:close_ticket"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        await interaction.response.send_message(
            "⚠️ هل أنت متأكد من إغلاق هذه التذكرة؟",
            view=ConfirmCloseTicketView(),
            ephemeral=True
        )


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton())


class ApplicationReviewView(discord.ui.View):
    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id

        accept = discord.ui.Button(
            label="قبول",
            emoji="✅",
            style=discord.ButtonStyle.success
        )
        reject = discord.ui.Button(
            label="رفض",
            emoji="❌",
            style=discord.ButtonStyle.danger
        )

        accept.callback = self.accept_application
        reject.callback = self.reject_application

        self.add_item(accept)
        self.add_item(reject)

    async def accept_application(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        guild = interaction.guild
        applicant = guild.get_member(self.applicant_id)

        if applicant is None:
            try:
                applicant = await guild.fetch_member(self.applicant_id)
            except discord.HTTPException:
                applicant = None

        if applicant is None:
            return await interaction.response.send_message(
                "ما قدرت ألقى المتقدم داخل السيرفر.",
                ephemeral=True
            )

        category_id = await get_setting(guild.id, "application_ticket_category")
        if not category_id:
            return await interaction.response.send_message(
                "كاتقوري تذاكر المقبولين غير محدد. اضبطه من `/settings`.",
                ephemeral=True
            )

        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "كاتقوري تذاكر المقبولين المحدد غير صالح.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            applicant: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True
            ),
        }

        admin_role_id = await get_setting(guild.id, "admin_role")
        if admin_role_id:
            admin_role = guild.get_role(int(admin_role_id))
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        safe_name = "".join(
            c for c in applicant.display_name.lower().replace(" ", "-")
            if c.isalnum() or c == "-"
        )[:40]
        if not safe_name:
            safe_name = str(applicant.id)

        try:
            ticket = await guild.create_text_channel(
                name=f"تقديم-{safe_name}",
                category=category,
                overwrites=overwrites,
                reason=f"قبول تقديم {applicant}"
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "البوت ما عنده صلاحية إنشاء روم أو تعديل صلاحياته.",
                ephemeral=True
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                "صار خطأ أثناء إنشاء تذكرة المتقدم.",
                ephemeral=True
            )

        ticket_embed = discord.Embed(
            title="✅ تم قبول التقديم",
            description=(
                f"أهلًا {applicant.mention}\n"
                "تم قبول تقديمك مبدئيًا، وكمل إجراءاتك مع الإدارة هنا."
            ),
            timestamp=datetime.now(timezone.utc)
        )
        await ticket.send(
            content=applicant.mention,
            embed=ticket_embed,
            view=TicketControlView()
        )

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب تقديم")
            embed.add_field(
                name="الحالة",
                value=f"✅ مقبول بواسطة {interaction.user.mention}\nالتذكرة: {ticket.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send(
            f"✅ تم قبول المتقدم وفتح التذكرة {ticket.mention}",
            ephemeral=True
        )

        await send_admin_log(
            interaction,
            "✅ قبول تقديم",
            f"المتقدم: {applicant.mention}\nالتذكرة: {ticket.mention}"
        )

    async def reject_application(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        applicant = interaction.guild.get_member(self.applicant_id)

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب تقديم")
            embed.add_field(
                name="الحالة",
                value=f"❌ مرفوض بواسطة {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            "تم رفض طلب التقديم.",
            ephemeral=True
        )

        applicant_text = applicant.mention if applicant else f"<@{self.applicant_id}>"
        await send_admin_log(
            interaction,
            "❌ رفض تقديم",
            f"المتقدم: {applicant_text}"
        )


class VacationModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="طلب إجازة")

        self.reason_input = discord.ui.TextInput(
            label="سبب الإجازة",
            placeholder="اكتب سبب الإجازة",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=500
        )
        self.duration_input = discord.ui.TextInput(
            label="مدة الإجازة",
            placeholder="مثال: 3 أيام",
            required=True,
            max_length=100
        )

        self.add_item(self.reason_input)
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "طلب الإجازة يعمل داخل السيرفر فقط.",
                ephemeral=True
            )

        # Vacation requests are for employees.
        if not await employee_allowed(interaction):
            return

        review_id = await get_setting(interaction.guild.id, "vacation_review")
        if not review_id:
            return await interaction.response.send_message(
                "روم مراجعة الإجازات غير محدد. خلي الإدارة تضبطه من `/settings`.",
                ephemeral=True
            )

        review_channel = interaction.guild.get_channel(int(review_id))
        if not isinstance(review_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "روم مراجعة الإجازات المحدد غير صالح.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🏖️ طلب إجازة جديد",
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="سبب الإجازة", value=self.reason_input.value, inline=False)
        embed.add_field(name="مدة الإجازة", value=self.duration_input.value, inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await review_channel.send(
            embed=embed,
            view=VacationReviewView(interaction.user.id)
        )

        await interaction.response.send_message(
            "✅ تم إرسال طلب إجازتك للإدارة بنجاح.",
            ephemeral=True
        )


class VacationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="طلب إجازة",
            emoji="🏖️",
            style=discord.ButtonStyle.primary,
            custom_id="panel:vacation"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await employee_allowed(interaction):
            return
        await interaction.response.send_modal(VacationModal())


class VacationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VacationButton())


class VacationReviewView(discord.ui.View):
    def __init__(self, employee_id: int):
        super().__init__(timeout=None)
        self.employee_id = employee_id

        accept = discord.ui.Button(
            label="قبول",
            emoji="✅",
            style=discord.ButtonStyle.success
        )
        reject = discord.ui.Button(
            label="رفض",
            emoji="❌",
            style=discord.ButtonStyle.danger
        )

        accept.callback = self.accept_vacation
        reject.callback = self.reject_vacation
        self.add_item(accept)
        self.add_item(reject)

    async def accept_vacation(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        guild = interaction.guild
        member = guild.get_member(self.employee_id)
        if member is None:
            try:
                member = await guild.fetch_member(self.employee_id)
            except discord.HTTPException:
                member = None

        if member is None:
            return await interaction.response.send_message(
                "ما قدرت ألقى الموظف داخل السيرفر.",
                ephemeral=True
            )

        role_id = await get_setting(guild.id, "vacation_role")
        if not role_id:
            return await interaction.response.send_message(
                "رتبة الإجازة غير محددة. اضبطها من `/settings`.",
                ephemeral=True
            )

        role = guild.get_role(int(role_id))
        if role is None:
            return await interaction.response.send_message(
                "رتبة الإجازة المحددة غير موجودة.",
                ephemeral=True
            )

        try:
            await member.add_roles(
                role,
                reason=f"قبول إجازة بواسطة {interaction.user}"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "البوت ما يقدر يعطي رتبة الإجازة. تأكد أن رتبة البوت أعلى من رتبة الإجازة وعنده Manage Roles.",
                ephemeral=True
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "صار خطأ أثناء إعطاء رتبة الإجازة.",
                ephemeral=True
            )

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب إجازة")
            embed.add_field(
                name="الحالة",
                value=f"✅ مقبولة بواسطة {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            f"✅ تم قبول إجازة {member.mention} وإعطاؤه {role.mention}.",
            ephemeral=True
        )

        await send_admin_log(
            interaction,
            "🏖️ قبول إجازة",
            f"الموظف: {member.mention}\nرتبة الإجازة: {role.mention}"
        )

    async def reject_vacation(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        member = interaction.guild.get_member(self.employee_id)

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب إجازة")
            embed.add_field(
                name="الحالة",
                value=f"❌ مرفوضة بواسطة {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            "تم رفض طلب الإجازة.",
            ephemeral=True
        )

        member_text = member.mention if member else f"<@{self.employee_id}>"
        await send_admin_log(
            interaction,
            "❌ رفض إجازة",
            f"الموظف: {member_text}"
        )


class HRModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="استبيان الموارد البشرية")

        self.game_name = discord.ui.TextInput(
            label="اسمك داخل اللعبة",
            placeholder="اكتب اسمك داخل اللعبة",
            required=True,
            max_length=100
        )
        self.phone_number = discord.ui.TextInput(
            label="رقم جوالك داخل اللعبة",
            placeholder="اكتب رقم الجوال داخل اللعبة",
            required=True,
            max_length=50
        )
        self.citizen_id = discord.ui.TextInput(
            label="Citizen ID",
            placeholder="Enter your Citizen ID",
            required=True,
            max_length=100
        )

        self.add_item(self.game_name)
        self.add_item(self.phone_number)
        self.add_item(self.citizen_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "هذا الاستبيان يعمل داخل السيرفر فقط.",
                ephemeral=True
            )

        review_id = await get_setting(interaction.guild.id, "hr_review")
        if not review_id:
            return await interaction.response.send_message(
                "روم الموارد البشرية غير محدد. خلي الإدارة تضبطه من `/settings`.",
                ephemeral=True
            )

        review_channel = interaction.guild.get_channel(int(review_id))
        if not isinstance(review_channel, discord.TextChannel):
            return await interaction.response.send_message(
                "روم الموارد البشرية المحدد غير صالح.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="👥 استبيان موارد بشرية جديد",
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="العضو", value=interaction.user.mention, inline=False)
        embed.add_field(name="اسمك داخل اللعبة", value=self.game_name.value, inline=False)
        embed.add_field(name="رقم جوالك داخل اللعبة", value=self.phone_number.value, inline=False)
        embed.add_field(name="Citizen ID", value=self.citizen_id.value, inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await review_channel.send(
            embed=embed,
            view=HRReviewView(interaction.user.id, self.game_name.value, self.phone_number.value, self.citizen_id.value)
        )

        await interaction.response.send_message(
            "✅ تم إرسال استبيانك للموارد البشرية بنجاح.",
            ephemeral=True
        )


class HRButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="تعبئة الاستبيان",
            emoji="👥",
            style=discord.ButtonStyle.primary,
            custom_id="panel:hr"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(HRModal())


class HRPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HRButton())


class HRReviewView(discord.ui.View):
    def __init__(self, member_id: int, game_name: str, phone_number: str, citizen_id: str):
        super().__init__(timeout=None)
        self.member_id = member_id
        self.game_name = game_name
        self.phone_number = phone_number
        self.citizen_id = citizen_id

        accept = discord.ui.Button(
            label="قبول",
            emoji="✅",
            style=discord.ButtonStyle.success
        )
        reject = discord.ui.Button(
            label="رفض",
            emoji="❌",
            style=discord.ButtonStyle.danger
        )

        accept.callback = self.accept_hr
        reject.callback = self.reject_hr
        self.add_item(accept)
        self.add_item(reject)

    async def accept_hr(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        guild = interaction.guild
        member = guild.get_member(self.member_id)
        if member is None:
            try:
                member = await guild.fetch_member(self.member_id)
            except discord.HTTPException:
                member = None

        if member is None:
            return await interaction.response.send_message(
                "ما قدرت ألقى العضو داخل السيرفر.",
                ephemeral=True
            )

        role_id = await get_setting(guild.id, "employee_role")
        if not role_id:
            return await interaction.response.send_message(
                "رتبة الموظف غير محددة. اضبطها من `/settings`.",
                ephemeral=True
            )

        role = guild.get_role(int(role_id))
        if role is None:
            return await interaction.response.send_message(
                "رتبة الموظف المحددة غير موجودة.",
                ephemeral=True
            )

        try:
            await member.add_roles(
                role,
                reason=f"قبول الموارد البشرية بواسطة {interaction.user}"
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "البوت ما يقدر يعطي رتبة الموظف. تأكد أن رتبة البوت أعلى من رتبة الموظف وعنده Manage Roles.",
                ephemeral=True
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "صار خطأ أثناء إعطاء رتبة الموظف.",
                ephemeral=True
            )

        await save_employee_profile(
            guild.id, member.id, self.game_name, self.phone_number, self.citizen_id, datetime.now(timezone.utc).isoformat()
        )

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="استبيان موارد بشرية")
            embed.add_field(
                name="الحالة",
                value=f"✅ مقبول بواسطة {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            f"✅ تم قبول {member.mention} وإعطاؤه {role.mention}.",
            ephemeral=True
        )

        await send_admin_log(
            interaction,
            "👥 قبول الموارد البشرية",
            f"العضو: {member.mention}\nالرتبة: {role.mention}"
        )

    async def reject_hr(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        member = interaction.guild.get_member(self.member_id)

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="استبيان موارد بشرية")
            embed.add_field(
                name="الحالة",
                value=f"❌ مرفوض بواسطة {interaction.user.mention}",
                inline=False
            )
            await interaction.message.edit(embed=embed, view=None)

        await interaction.response.send_message(
            "تم رفض الاستبيان.",
            ephemeral=True
        )

        member_text = member.mention if member else f"<@{self.member_id}>"
        await send_admin_log(
            interaction,
            "❌ رفض الموارد البشرية",
            f"العضو: {member_text}"
        )



async def end_employee_membership(interaction, member: discord.Member, departure_type: str):
    guild = interaction.guild
    active = await get_active_attendance(guild.id, member.id)
    worked_text = None
    if active:
        session_id, check_in_at, _ = active
        now = datetime.now(timezone.utc)
        worked = max(0, int((now - datetime.fromisoformat(check_in_at)).total_seconds()))
        earned = round((worked / 3600) * 5, 2)
        await force_finish_attendance(session_id, guild.id, member.id, now.isoformat(), worked, earned, interaction.user.id)
        worked_text = f"{format_duration(worked)} / {format_points(earned)} نقطة"

    roles_to_remove = []
    for key in ("employee_role", "vacation_role"):
        rid = await get_setting(guild.id, key)
        if rid:
            role = guild.get_role(int(rid))
            if role and role in member.roles:
                roles_to_remove.append(role)
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason=departure_type)
        except discord.Forbidden:
            pass

    await remove_employee_profile(guild.id, member.id, departure_type, datetime.now(timezone.utc).isoformat(), interaction.user.id)
    return worked_text


class FireEmployeeModal(discord.ui.Modal):
    def __init__(self, member_id: int, mention: str):
        super().__init__(title="فصل موظف")
        self.member_id = member_id
        self.mention = mention
        self.message_text = discord.ui.TextInput(label="رسالة الإدارة", placeholder="اكتب رسالة الفصل", style=discord.TextStyle.paragraph, required=True, max_length=1000)
        self.add_item(self.message_text)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction): return
        member = interaction.guild.get_member(self.member_id)
        if not member:
            try: member = await interaction.guild.fetch_member(self.member_id)
            except discord.HTTPException: member = None
        if not member:
            return await interaction.response.send_message("ما قدرت ألقى الموظف داخل السيرفر.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        dm_ok = True
        try:
            await member.send(f"تم إنهاء عملك في **Bean Machine**.\n\n**رسالة الإدارة:**\n{self.message_text.value}")
        except discord.HTTPException:
            dm_ok = False
        worked = await end_employee_membership(interaction, member, "فصل")
        desc = f"الموظف: {member.mention}\nرسالة الإدارة: {self.message_text.value}"
        if worked: desc += f"\nتم إنهاء الدوام: {worked}"
        await send_admin_log(interaction, "فصل موظف", desc)
        await interaction.followup.send(f"تم فصل {member.mention} وحذف بياناته الوظيفية." + ("" if dm_ok else "\nتعذر إرسال الخاص للعضو."), ephemeral=True)


class ResignationModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="طلب استقالة")
        self.reason = discord.ui.TextInput(label="سبب الاستقالة", style=discord.TextStyle.paragraph, required=True, max_length=700)
        self.final = discord.ui.TextInput(label="هل الاستقالة نهائية؟", placeholder="نعم / لا", required=True, max_length=20)
        self.notes = discord.ui.TextInput(label="ملاحظات إضافية", required=False, style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.reason); self.add_item(self.final); self.add_item(self.notes)

    async def on_submit(self, interaction: discord.Interaction):
        if not await employee_allowed(interaction): return
        cid = await get_setting(interaction.guild.id, "resignation_review")
        channel = interaction.guild.get_channel(int(cid)) if cid else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("روم مراجعة الاستقالات غير محدد. اضبطه من `/settings`.", ephemeral=True)
        embed = discord.Embed(title="طلب استقالة جديد", timestamp=datetime.now(timezone.utc))
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="سبب الاستقالة", value=self.reason.value, inline=False)
        embed.add_field(name="هل الاستقالة نهائية؟", value=self.final.value, inline=False)
        embed.add_field(name="ملاحظات إضافية", value=self.notes.value or "لا يوجد", inline=False)
        await channel.send(embed=embed, view=ResignationReviewView(interaction.user.id))
        await interaction.response.send_message("تم إرسال طلب استقالتك للإدارة.", ephemeral=True)


class ResignationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="تقديم استقالة", style=discord.ButtonStyle.danger, custom_id="panel:resignation")
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        await interaction.response.send_modal(ResignationModal())

class ResignationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None); self.add_item(ResignationButton())

class ResignationReviewView(discord.ui.View):
    def __init__(self, member_id):
        super().__init__(timeout=None); self.member_id=member_id
        a=discord.ui.Button(label="قبول",style=discord.ButtonStyle.success); r=discord.ui.Button(label="رفض",style=discord.ButtonStyle.danger)
        a.callback=self.accept; r.callback=self.reject; self.add_item(a); self.add_item(r)
    async def accept(self, interaction):
        if not await admin_allowed(interaction): return
        member=interaction.guild.get_member(self.member_id)
        if not member:
            try: member=await interaction.guild.fetch_member(self.member_id)
            except discord.HTTPException: member=None
        if not member: return await interaction.response.send_message("ما قدرت ألقى الموظف.",ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        worked=await end_employee_membership(interaction,member,"استقالة")
        if interaction.message:
            e=interaction.message.embeds[0]; e.add_field(name="الحالة",value=f"مقبولة بواسطة {interaction.user.mention}",inline=False); await interaction.message.edit(embed=e,view=None)
        try: await member.send("تم قبول استقالتك من **Bean Machine**.")
        except discord.HTTPException: pass
        await send_admin_log(interaction,"قبول استقالة",f"الموظف: {member.mention}" + (f"\nتم إنهاء الدوام: {worked}" if worked else ""))
        await interaction.followup.send("تم قبول الاستقالة وإزالة الرتب وحذف البيانات الوظيفية.",ephemeral=True)
    async def reject(self, interaction):
        if not await admin_allowed(interaction): return
        if interaction.message:
            e=interaction.message.embeds[0]; e.add_field(name="الحالة",value=f"مرفوضة بواسطة {interaction.user.mention}",inline=False); await interaction.message.edit(embed=e,view=None)
        await interaction.response.send_message("تم رفض الاستقالة.",ephemeral=True)


class EmployeeSearchModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="بحث عن موظف")
        self.query=discord.ui.TextInput(label="البحث",placeholder="اسم اللعبة / رقم الجوال / Citizen ID / Discord ID",required=True,max_length=100)
        self.add_item(self.query)
    async def on_submit(self, interaction):
        if not await admin_allowed(interaction): return
        rows=await search_employee_profiles(interaction.guild.id,self.query.value)
        if not rows: return await interaction.response.send_message("لم يتم العثور على موظف.",ephemeral=True)
        embeds=[]
        for uid,name,phone,citizen,hired,status in rows[:10]:
            stats=await get_employee_stats(interaction.guild.id,uid)
            points,seconds,invoices,tasks=stats
            e=discord.Embed(title=f"بيانات الموظف - {name}")
            e.add_field(name="Discord",value=f"<@{uid}> (`{uid}`)",inline=False)
            e.add_field(name="الحالة",value="موظف",inline=True); e.add_field(name="اسم اللعبة",value=name,inline=True)
            e.add_field(name="رقم الجوال",value=phone,inline=True); e.add_field(name="Citizen ID",value=citizen,inline=True)
            e.add_field(name="تاريخ التوظيف",value=f"<t:{int(datetime.fromisoformat(hired).timestamp())}:D>",inline=True)
            e.add_field(name="النقاط",value=format_points(points),inline=True); e.add_field(name="ساعات العمل",value=format_duration(seconds),inline=True)
            e.add_field(name="الفواتير",value=str(invoices),inline=True); e.add_field(name="المهام",value=str(tasks),inline=True)
            embeds.append(e)
        await interaction.response.send_message(embeds=embeds,ephemeral=True)

class EmployeeDatabaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="بحث عن موظف",style=discord.ButtonStyle.primary,custom_id="db:search")
    async def search(self,interaction,button):
        if not await admin_allowed(interaction): return
        await interaction.response.send_modal(EmployeeSearchModal())
    @discord.ui.button(label="عرض جميع الموظفين",style=discord.ButtonStyle.secondary,custom_id="db:list")
    async def list_all(self,interaction,button):
        if not await admin_allowed(interaction): return
        rows=await list_employee_profiles(interaction.guild.id)
        if not rows: return await interaction.response.send_message("لا يوجد موظفون حاليًا.",ephemeral=True)
        chunks=[]
        for start in range(0,len(rows),10):
            lines=[]
            for i,(uid,name,phone,citizen,hired,status) in enumerate(rows[start:start+10],start+1):
                lines.append(f"**{i}. {name}** — <@{uid}>\n`{phone}` | `{citizen}`")
            chunks.append(discord.Embed(title=f"الموظفون الحاليون ({len(rows)})",description="\n\n".join(lines)))
        await interaction.response.send_message(embeds=chunks[:10],ephemeral=True)
    @discord.ui.button(label="تحديث",style=discord.ButtonStyle.success,custom_id="db:refresh")
    async def refresh(self,interaction,button):
        if not await admin_allowed(interaction): return
        rows=await list_employee_profiles(interaction.guild.id)
        embed=discord.Embed(title="قاعدة بيانات الموظفين",description=f"إجمالي الموظفين الحاليين: **{len(rows)}**\n\nاستخدم الأزرار بالأسفل للبحث أو عرض الموظفين.",timestamp=datetime.now(timezone.utc))
        await interaction.response.edit_message(embed=embed,view=self)

class OtherPanelButton(discord.ui.Button):
    def __init__(self, label, custom_id):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=custom_id)
    async def callback(self, interaction):
        await interaction.response.send_message("هذا النظام بنركبه بعد نظام التقديم.", ephemeral=True)

class PanelSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="لوحة التقديم",value="application",emoji="📝"), discord.SelectOption(label="لوحة الإجازات",value="vacation",emoji="🏖️"), discord.SelectOption(label="لوحة الموارد البشرية",value="hr",emoji="👥"), discord.SelectOption(label="لوحة الاستقالات",value="resignation"), discord.SelectOption(label="قاعدة الموظفين",value="employee_db")]
        super().__init__(placeholder="اختر اللوحة", options=options)
    async def callback(self, interaction):
        selected = self.values[0]

        if selected == "application":
            await interaction.channel.send(
                embed=discord.Embed(
                    title="📝 | التقديم على المطعم",
                    description="""أهلًا وسهلًا بك في نظام التقديم الخاص بالمطعم.

إذا كنت ترغب بالانضمام إلى فريق العمل، يرجى قراءة **قوانين العمل وطريقة العمل بالكامل** قبل البدء بالتقديم، والتأكد من قدرتك على الالتزام بالدوام والمهام المطلوبة منك.

عند الضغط على زر **📝 تقديم** سيظهر لك استبيان يحتوي على مجموعة من الأسئلة، يرجى الإجابة عليها **بشكل واضح وصحيح** لأن إجاباتك سيتم مراجعتها من قِبل الإدارة.

**الاستبيان يحتوي على:**
الاسم، العمر، سبب التقديم، عدد الساعات التي تستطيع العمل بها يوميًا، والتأكيد على قراءة قوانين وطريقة العمل.

بعد إرسال الطلب سيتم تحويله إلى **الإدارة للمراجعة**، وفي حال قبول طلبك سيتم فتح **تذكرة خاصة** بينك وبين الإدارة لاستكمال إجراءات التوظيف.

إذا قدمت عبر موقع Bean Machine وتم قبولك، استخدم زر **طلب انضمام** وأدخل رقم القبول الذي ظهر لك في الموقع.

**تنبيهات مهمة**
يرجى عدم إرسال أكثر من طلب، وعدم الاستعجال أو سؤال الإدارة عن حالة تقديمك. تأكد من صحة جميع المعلومات قبل إرسال الطلب.

**نتمنى لك التوفيق 🤍**"""
                ),
                view=ApplicationPanelView()
            )
            return await interaction.response.send_message(
                "تم إرسال لوحة التقديم.",
                ephemeral=True
            )

        if selected == "vacation":
            await interaction.channel.send(
                embed=discord.Embed(
                    title="نظام الإجازات",
                    description="""من خلال هذه اللوحة يمكنك تقديم **طلب إجازة** في حال كنت بحاجة للتوقف عن العمل لفترة محددة.

عند الضغط على زر **طلب إجازة** سيظهر لك استبيان يطلب منك:

**سبب الإجازة** و **مدة الإجازة**.

يرجى كتابة سبب واضح وتحديد مدة الإجازة بشكل دقيق قبل إرسال الطلب.

بعد إرسال الطلب سيتم تحويله إلى **الإدارة للمراجعة**، وسيتم اتخاذ قرار **القبول أو الرفض**.

في حال قبول الطلب سيتم منحك **رتبة الإجازة**.

**تنبيهات مهمة:**
لا تقدم طلب إجازة إلا عند الحاجة، وتأكد من كتابة المدة بشكل صحيح. كما يرجى عدم تكرار الطلب أو استعجال الإدارة أثناء مراجعته.

**نتمنى لكم دوامًا موفقًا.**"""
                ),
                view=VacationPanelView()
            )
            return await interaction.response.send_message(
                "تم إرسال لوحة الإجازات.",
                ephemeral=True
            )

        if selected == "resignation":
            await interaction.channel.send(embed=discord.Embed(title="نظام الاستقالات", description="من خلال هذه اللوحة يمكن للموظف تقديم طلب استقالة ليتم مراجعته من الإدارة."), view=ResignationPanelView())
            return await interaction.response.send_message("تم إرسال لوحة الاستقالات.", ephemeral=True)

        if selected == "employee_db":
            if not await admin_allowed(interaction): return
            channel_id = await get_setting(interaction.guild.id, "employee_database_channel")
            target = interaction.guild.get_channel(int(channel_id)) if channel_id else None
            if not isinstance(target, discord.TextChannel):
                return await interaction.response.send_message("روم قاعدة بيانات الموظفين غير محدد. اضبطه من `/settings`.", ephemeral=True)
            rows = await list_employee_profiles(interaction.guild.id)
            embed = discord.Embed(title="قاعدة بيانات الموظفين", description=f"إجمالي الموظفين الحاليين: **{len(rows)}**\n\nاستخدم الأزرار بالأسفل للبحث أو عرض الموظفين.", timestamp=datetime.now(timezone.utc))
            await target.send(embed=embed, view=EmployeeDatabaseView())
            return await interaction.response.send_message(f"تم إرسال قاعدة الموظفين في {target.mention}.", ephemeral=True)

        await interaction.channel.send(
            embed=discord.Embed(
                title="الموارد البشرية",
                description="""هذه اللوحة مخصصة لاستكمال **بيانات الموظف** بعد إنهاء إجراءات القبول.

عند الضغط على زر **تعبئة الاستبيان** سيطلب منك إدخال البيانات التالية:

**اسمك داخل اللعبة**
**رقم جوالك داخل اللعبة**
**Citizen ID**

يرجى التأكد من كتابة جميع البيانات **بشكل صحيح ودقيق** قبل إرسال الاستبيان، حيث سيتم اعتماد هذه المعلومات من قِبل الإدارة.

بعد إرسال الاستبيان سيتم تحويله إلى **الموارد البشرية للمراجعة**.

في حال قبول البيانات سيتم منحك **رتبة الموظف** تلقائيًا.

**تنبيه مهم:**
تأكد من صحة اسمك ورقم جوالك وCitizen ID قبل الإرسال، ولا تقم بإرسال الاستبيان أكثر من مرة."""
            ),
            view=HRPanelView()
        )
        await interaction.response.send_message(
            "تم إرسال لوحة الموارد البشرية.",
            ephemeral=True
        )

class Panels(commands.Cog):
    def __init__(self, bot):
        self.bot=bot
        bot.add_view(EmployeePanel()); bot.add_view(AdminPanel()); bot.add_view(ApplicationPanelView()); bot.add_view(TicketControlView()); bot.add_view(VacationPanelView()); bot.add_view(HRPanelView()); bot.add_view(ResignationPanelView()); bot.add_view(EmployeeDatabaseView())
    @app_commands.command(name="لوحة-الادارة",description="إرسال لوحة تحكم الإدارة")
    async def admin_panel(self,interaction):
        if not await admin_allowed(interaction): return
        await interaction.channel.send(embed=discord.Embed(
            title="⚙️ | لوحة تحكم الإدارة",
            description="""من خلال هذه اللوحة يمكنك إدارة دوام الموظفين ونقاطهم ومتابعة إحصائياتهم.

🔴 **تسجيل خروج إجباري**
تسجيل خروج موظف مسجل حاليًا، مع احتساب مدة عمله ونقاط الساعات حتى لحظة إخراجه.

➕ **زيادة نقاط**
إضافة عدد نقاط تحدده لموظف مع كتابة سبب الإضافة.

➖ **خصم نقاط**
خصم عدد نقاط تحدده من الموظف مع كتابة السبب، ويمكن أن يصل رصيده إلى **السالب**.

📋 **احتساب مهمة**
تسجيل مهمة مكتملة للموظف وإضافة **7 نقاط** تلقائيًا.

🟢 **المسجلون دخول الآن**
عرض جميع الموظفين الموجودين في الدوام حاليًا ومدة عمل كل موظف.

📊 **إحصائيات الجميع**
عرض وترتيب جميع الموظفين حسب النقاط، مع الساعات والفواتير والمهام.

👤 **إحصائيات موظف**
اختيار موظف وعرض نقاطه وساعات عمله وفواتيره ومهامه وحالة دوامه.

♻️ **تصفير الجميع**
تصفير نقاط جميع الموظفين دفعة واحدة.

🗑️ **تصفير موظف**
تصفير نقاط موظف محدد فقط.

🛑 **فصل موظف**
اختيار موظف وكتابة رسالة الإدارة، ثم إزالة رتب الموظف والإجازة وحذف بياناته الوظيفية.

**تنبيه:** عمليات زيادة وخصم وتصفير النقاط والخروج الإجباري والفصل يتم تسجيلها في لوق الإدارة."""
        ),view=AdminPanel())
        await interaction.response.send_message("تم إرسال لوحة الإدارة.",ephemeral=True)
    @app_commands.command(name="لوحة-الموظفين",description="إرسال لوحة تحكم الموظفين")
    async def employee_panel(self,interaction):
        if not await admin_allowed(interaction): return
        await interaction.channel.send(embed=discord.Embed(
            title="🍽️ | لوحة الموظفين",
            description="""من خلال هذه اللوحة يمكنك إدارة دوامك وفواتيرك ومتابعة نقاطك.

🟢 **تسجيل دخول**
لبدء دوامك، اضغط الزر ثم أرسل **صورة المخزون**.

🔴 **تسجيل خروج**
لإنهاء دوامك، اضغط الزر ثم أرسل **صورة المخزون**، وسيتم احتساب ساعات عملك ونقاطك.

🧾 **إنشاء فاتورة**
اضغط الزر ثم أرسل **صورة الفاتورة** ليتم تسجيلها واحتساب **+1 نقطة**.

⭐ **نقاطي**
يعرض لك إجمالي نقاطك الحالية.

**نظام النقاط**
كل ساعة عمل = **5 نقاط**
كل فاتورة = **1 نقطة**
كل مهمة = **7 نقاط**"""
        ),view=EmployeePanel())
        await interaction.response.send_message("تم إرسال لوحة الموظفين.",ephemeral=True)
    @app_commands.command(name="اللوحات",description="إرسال باقي لوحات البوت")
    async def panels(self,interaction):
        if not await admin_allowed(interaction): return
        view=discord.ui.View(timeout=120); view.add_item(PanelSelect())
        await interaction.response.send_message("اختر اللوحة التي تريد إرسالها:",view=view,ephemeral=True)

async def setup(bot):
    await bot.add_cog(Panels(bot))