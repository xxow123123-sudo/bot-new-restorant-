from datetime import datetime, timezone, timedelta
import asyncio
from io import BytesIO
import discord
import openpyxl
from discord import app_commands
from discord.ext import commands, tasks as discord_tasks

from database.db import (
    get_setting, get_points, get_active_attendance, get_all_active_attendance,
    start_attendance, finish_attendance, force_finish_attendance, add_invoice,
    add_points, set_points, reset_all_points, add_task, get_all_employee_stats, get_employee_stats,
    create_task, set_task_message, get_task, get_active_tasks, get_task_participant_count,
    get_task_participants, accept_task, submit_task_evidence, get_task_participant_evidence, get_pending_task_submissions, complete_task_for_user, approve_task_submission, reject_task_submission, close_task,
    save_employee_profile, get_employee_profile, search_employee_profiles, list_employee_profiles, list_current_employee_profiles, remove_employee_profile,
    add_disciplinary_action, get_manual_strike_level, get_attendance_strike_level,
    can_user_apply, set_reapply_allowed, create_vacation_request, get_vacation, get_active_vacation,
    accept_vacation, reject_vacation, end_vacation, get_expired_vacations, get_pending_vacations,
    get_all_weekly_activity, get_weekly_activity, reset_weekly_activity, set_setting, set_employee_status, get_total_strikes,
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

FIXED_CHANNELS = {
    "attendance_log": 1538166452975046667,
    "invoice_log": 1539032592580354174,
    "discipline_log": 1538208912329670787,
    "decisions_log": 1538208912329670787,
    "application_log": 1539032752253313174,
    "hr_log": 1538166804160184423,
    "vacation_log": 1538166714632511640,
    "resignation_log": 1539029748485718016,
    "termination_log": 1539034314103324752,
    "employee_database_log": 1539034291034521630,
    "bot_log": 1539034314103324752,
}

async def get_log_channel(interaction: discord.Interaction, setting_key: str):
    if not interaction.guild:
        return None
    channel_id = await get_setting(interaction.guild.id, setting_key)
    if not channel_id:
        channel_id = FIXED_CHANNELS.get(setting_key)
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

def _employee_board_embeds(rows):
    now = datetime.now(timezone.utc)
    if not rows:
        embed = discord.Embed(
            title="👥 لوحة الموظفين",
            description="لا يوجد موظفون مسجلون حاليًا.",
            timestamp=now,
        )
        embed.set_footer(text="هذه اللوحة تتحدث تلقائيًا من قاعدة بيانات البوت")
        return [embed]

    lines = []
    for index, (uid, name, phone, citizen, hired, status) in enumerate(rows, 1):
        status_text = "🏖️ إجازة" if status == "vacation" else "🟢 موظف"
        lines.append(
            f"**{index}. {name}** — <@{uid}>\n"
            f"{status_text} • Citizen ID: `{citizen}` • الجوال: `{phone}`"
        )

    descriptions = []
    current = []
    current_len = 0
    for line in lines:
        add_len = len(line) + (2 if current else 0)
        if current and current_len + add_len > 3800:
            descriptions.append("\n\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += add_len
    if current:
        descriptions.append("\n\n".join(current))

    overflow = max(0, len(descriptions) - 10)
    descriptions = descriptions[:10]
    embeds = []
    for page, description in enumerate(descriptions, 1):
        title = f"👥 لوحة الموظفين — الإجمالي: {len(rows)}" if page == 1 else f"👥 الموظفون — صفحة {page}"
        embed = discord.Embed(title=title, description=description, timestamp=now if page == 1 else None)
        if page == 1:
            embed.set_footer(text="تتحدث تلقائيًا عند التوظيف أو الإجازة أو الفصل أو تغيير رتبة الموظف")
        embeds.append(embed)
    if overflow and embeds:
        embeds[-1].add_field(name="تنبيه", value="عدد الموظفين أكبر من سعة رسالة Discord الواحدة. استخدم زر البحث لعرض بقية السجلات.", inline=False)
    return embeds


async def sync_employee_board(guild: discord.Guild, view=None):
    """إنشاء/تحديث رسالة ثابتة للموظفين بدل تصدير ملف Excel."""
    channel_id = await get_setting(guild.id, "employee_database_channel")
    if not channel_id:
        channel_id = FIXED_CHANNELS.get("employee_database_log")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return None

    rows = await list_current_employee_profiles(guild.id)
    embeds = _employee_board_embeds(rows)
    message_id = await get_setting(guild.id, "employee_database_message")
    message = None
    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            message = None

    try:
        if message:
            if view is None:
                await message.edit(embeds=embeds)
            else:
                await message.edit(embeds=embeds, view=view)
        else:
            message = await channel.send(embeds=embeds, view=view)
            await set_setting(guild.id, "employee_database_message", str(message.id))
    except (discord.Forbidden, discord.HTTPException):
        return None
    return message

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
            forced_count, strike_level = await force_finish_attendance(session_id, interaction.guild.id, member.id, now.isoformat(), worked, earned, interaction.user.id)

            # أول خروج إجباري لا يعطي Strike. من الخروج الإجباري الثاني يبدأ Strike 1.
            STRIKE_ROLES = {
                1: 1539288778210943069,
                2: 1539289156059140309,
                3: 1539289310321180853,
            }
            strike_role = None
            if strike_level:
                # إزالة أي Strike سابق ثم إعطاء المستوى الحالي.
                for rid in STRIKE_ROLES.values():
                    role = interaction.guild.get_role(rid)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason="تحديث مستوى الاسترايك بعد خروج إجباري")
                        except discord.HTTPException:
                            pass
                strike_role = interaction.guild.get_role(STRIKE_ROLES[strike_level])
                if strike_role:
                    try:
                        await member.add_roles(strike_role, reason=f"Strike {strike_level} بسبب الخروج الإجباري رقم {forced_count}")
                    except discord.HTTPException:
                        strike_role = None

            response = f"تم تسجيل خروج {member.mention} إجباريًا.\nالمدة: **{format_duration(worked)}**\nالنقاط: **{format_points(earned)}**"
            if strike_level == 0:
                response += "\nهذه أول مرة، لا يوجد Strike."
            else:
                response += f"\nتم تسجيل **Strike {strike_level}**."
            await interaction.response.send_message(response, ephemeral=True)

            strike_channel = interaction.guild.get_channel(1538208912329670787)
            if strike_level and strike_channel:
                embed = discord.Embed(title=f"Strike {strike_level}", timestamp=now)
                embed.add_field(name="الموظف", value=member.mention, inline=False)
                embed.add_field(name="الخروج الإجباري رقم", value=str(forced_count), inline=True)
                embed.add_field(name="الإداري", value=interaction.user.mention, inline=True)
                embed.add_field(name="الرتبة", value=strike_role.mention if strike_role else f"Strike {strike_level}", inline=False)
                await strike_channel.send(embed=embed)

            await send_admin_log(interaction, "🔴 خروج إجباري", f"الموظف: {member.mention}\nالمدة: {format_duration(worked)}\nالنقاط: {format_points(earned)}\nالخروج الإجباري رقم: {forced_count}\nStrike: {strike_level if strike_level else 'لا يوجد'}")
        elif self.action == "discipline":
            await interaction.response.send_message("اختر مستوى الاسترايك:", view=DisciplineLevelView(member.id, member.mention), ephemeral=True)
        elif self.action in ("add", "remove"):
            await interaction.response.send_modal(PointsModal(member.id, member.mention, self.action))
        elif self.action == "task":
            await interaction.response.send_modal(TaskModal(member.id, member.mention))
        elif self.action == "fire":
            await interaction.response.send_modal(FireEmployeeModal(member.id, member.mention))
        elif self.action == "reapply":
            await set_reapply_allowed(interaction.guild.id, member.id, True, datetime.now(timezone.utc).isoformat())
            await interaction.response.send_message(f"✅ تم السماح لـ {member.mention} بإعادة التقديم.", ephemeral=True)
            await send_admin_log(interaction, "🔓 سماح إعادة تقديم", f"العضو: {member.mention}")
        elif self.action == "stats":
            stats = await get_employee_stats(interaction.guild.id, member.id)
            points, seconds, invoices, tasks = stats
            weekly = await get_weekly_activity(interaction.guild.id, member.id)
            w_invoices, w_seconds, w_tasks, w_points = weekly
            target = await _weekly_target(interaction.guild.id)
            strikes = await get_total_strikes(interaction.guild.id, member.id)
            active = await get_active_attendance(interaction.guild.id, member.id)
            status = "🟢 مسجل دخول" if active else "🔴 غير مسجل"
            embed = discord.Embed(title=f"إحصائيات {member.display_name}")
            embed.add_field(name="إجمالي النقاط", value=format_points(points))
            embed.add_field(name="إجمالي ساعات العمل", value=format_duration(seconds))
            embed.add_field(name="إجمالي الفواتير", value=str(invoices))
            embed.add_field(name="إجمالي المهام", value=str(tasks))
            embed.add_field(name="إجمالي السترايكات", value=str(strikes))
            embed.add_field(name="الحالة", value=status)
            embed.add_field(name="فواتير الأسبوع", value=f"{w_invoices}/{target}")
            embed.add_field(name="ساعات الأسبوع", value=format_duration(w_seconds))
            embed.add_field(name="مهام الأسبوع", value=str(w_tasks))
            embed.add_field(name="نقاط الأسبوع", value=format_points(w_points))
            embed.add_field(name="حالة التفاعل", value="✅ متفاعل" if w_invoices >= target else "❌ غير متفاعل", inline=False)
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

class TaskPublishModal(discord.ui.Modal):
    def __init__(self, channel):
        super().__init__(title="نشر مهمة جديدة")
        self.channel = channel
        self.title_input = discord.ui.TextInput(label="اسم المهمة", placeholder="مثال: تجهيز المخزون", required=True, max_length=100)
        self.description_input = discord.ui.TextInput(label="شرح المهمة", placeholder="اكتب تفاصيل وتعليمات المهمة", required=True, style=discord.TextStyle.paragraph, max_length=1800)
        self.max_input = discord.ui.TextInput(label="الحد الأقصى للموظفين", placeholder="مثال: 2", required=True, max_length=3)
        self.add_item(self.title_input); self.add_item(self.description_input); self.add_item(self.max_input)

    async def on_submit(self, interaction):
        try:
            maximum = int(str(self.max_input.value).strip())
            if maximum < 1 or maximum > 99:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("اكتب عددًا صحيحًا من 1 إلى 99.", ephemeral=True)

        task_channel_id = await get_setting(interaction.guild.id, "task_channel")
        task_channel = interaction.guild.get_channel(int(task_channel_id)) if task_channel_id else None
        if not isinstance(task_channel, discord.TextChannel):
            return await interaction.response.send_message("روم نشر المهام غير محدد. خلي الإدارة تضبطه من `/settings`.", ephemeral=True)

        await interaction.response.send_message(f"أرسل **صورة المهمة** الآن في {task_channel.mention} أو في نفس روم لوحة الإدارة خلال دقيقتين.", ephemeral=True)
        def check(message):
            if message.author.id != interaction.user.id or message.channel.id not in (interaction.channel_id, task_channel.id) or not message.attachments:
                return False
            a = message.attachments[0]
            ctype = a.content_type or ""
            return ctype.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
        try:
            source = await interaction.client.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            return await interaction.followup.send("انتهى الوقت. اضغط نشر مهمة وحاول مرة ثانية.", ephemeral=True)

        attachment = source.attachments[0]
        task_id = await create_task(
            interaction.guild.id, task_channel.id, self.title_input.value.strip(),
            self.description_input.value.strip(), attachment.url, maximum,
            interaction.user.id, datetime.now(timezone.utc).isoformat()
        )
        embed = await build_task_embed(task_id)
        embed.title = f"📋 | مهمة جديدة — {self.title_input.value.strip()}"
        image_bytes = await attachment.read()
        filename = attachment.filename or "task.png"
        embed.set_image(url=f"attachment://{filename}")
        task_file = discord.File(BytesIO(image_bytes), filename=filename)
        msg = await task_channel.send(embed=embed, file=task_file, view=TaskView(task_id, maximum, 0, "open"))
        stored_image_url = msg.attachments[0].url if msg.attachments else attachment.url
        await set_task_message(task_id, msg.id, stored_image_url)
        try: await source.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass
        await interaction.followup.send(f"تم نشر المهمة بنجاح. رقم المهمة: **{task_id}**", ephemeral=True)
        await send_admin_log(interaction, "📋 نشر مهمة", f"المهمة: **{self.title_input.value.strip()}**\nالحد الأقصى: {maximum}\nرقم المهمة: {task_id}")

class TaskAcceptButton(discord.ui.Button):
    def __init__(self, task_id, disabled=False):
        super().__init__(label="قبول المهمة", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"task:accept:{task_id}", disabled=disabled)
        self.task_id = task_id
    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        task = await get_task(self.task_id)
        if not task or task[1] != interaction.guild.id:
            return await interaction.response.send_message("هذه المهمة غير موجودة.", ephemeral=True)
        status, count, maximum = await accept_task(self.task_id, interaction.guild.id, interaction.user.id, datetime.now(timezone.utc).isoformat())
        if status == "accepted":
            await interaction.response.send_message("تم قبول المهمة وتسجيل اسمك ضمن المشاركين.", ephemeral=True)
        elif status == "already":
            await interaction.response.send_message("أنت مقبول في هذه المهمة مسبقًا.", ephemeral=True)
        elif status == "full":
            await interaction.response.send_message("اكتمل العدد المحدد لهذه المهمة.", ephemeral=True)
        else:
            await interaction.response.send_message("هذه المهمة مغلقة حاليًا.", ephemeral=True)
        try:
            await interaction.message.edit(embed=await build_task_embed(self.task_id), view=await build_task_view(self.task_id))
        except discord.HTTPException:
            pass

class TaskEvidenceButton(discord.ui.Button):
    def __init__(self, task_id):
        super().__init__(label="إكمال المهمة", emoji="🏁", style=discord.ButtonStyle.primary, custom_id=f"task:evidence:{task_id}")
        self.task_id = task_id

    async def callback(self, interaction):
        if not await employee_allowed(interaction): return
        task = await get_task(self.task_id)
        if not task or task[1] != interaction.guild.id:
            return await interaction.response.send_message("هذه المهمة غير موجودة.", ephemeral=True)
        participant = await get_task_participant_evidence(self.task_id, interaction.guild.id, interaction.user.id)
        if not participant:
            return await interaction.response.send_message("لازم تقبل المهمة أولًا.", ephemeral=True)
        if participant[2] == "completed":
            return await interaction.response.send_message("تم احتساب هذه المهمة لك مسبقًا.", ephemeral=True)
        if participant[2] == "pending_review":
            return await interaction.response.send_message("دليلك السابق بانتظار مراجعة الإدارة.", ephemeral=True)

        await interaction.response.send_message("📸 أرسل صورة الأشياء التي صنعتها في المهمة في نفس الشات خلال دقيقتين.", ephemeral=True)
        def check(message):
            if message.author.id != interaction.user.id or message.channel.id != interaction.channel_id or not message.attachments:
                return False
            a = message.attachments[0]
            ctype = a.content_type or ""
            return ctype.startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
        try:
            source = await interaction.client.wait_for("message", timeout=120, check=check)
        except asyncio.TimeoutError:
            return await interaction.followup.send("انتهى الوقت. اضغط **إكمال المهمة** وحاول مرة ثانية.", ephemeral=True)

        attachment = source.attachments[0]
        try:
            image_bytes = await attachment.read()
            filename = attachment.filename or "task_evidence.png"
            log_channel = await get_log_channel(interaction, "task_log")
            if not log_channel:
                return await interaction.followup.send("لوق المهام غير محدد. خلي الإدارة تضبطه من `/settings`.", ephemeral=True)
            evidence_url = attachment.url
            review_embed = discord.Embed(
                title="📋 | مراجعة إنجاز مهمة",
                description=f"**المهمة:** {task[4]}\n**رقم المهمة:** {self.task_id}\n**الموظف:** {interaction.user.mention}\n\n**الحالة:** ⏳ بانتظار مراجعة الإدارة",
                timestamp=datetime.now(timezone.utc)
            )
            review_embed.add_field(name="المطلوب", value="راجع الصورة ثم اختر قبول أو رفض.", inline=False)
            review_file = discord.File(BytesIO(image_bytes), filename=filename)
            review_embed.set_image(url=f"attachment://{filename}")
            review_msg = await log_channel.send(embed=review_embed, file=review_file, view=TaskReviewView(self.task_id, interaction.user.id))
            if review_msg.attachments:
                evidence_url = review_msg.attachments[0].url
            result = await submit_task_evidence(self.task_id, interaction.guild.id, interaction.user.id, evidence_url, datetime.now(timezone.utc).isoformat())
            if result == "submitted":
                try: await source.delete()
                except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass
                await interaction.followup.send("✅ تم إرسال الإنجاز، وبانتظار اعتماد الإدارة من لوق المهام.", ephemeral=True)
            elif result == "completed":
                await interaction.followup.send("تم احتساب المهمة مسبقًا.", ephemeral=True)
            else:
                await interaction.followup.send("لازم تقبل المهمة أولًا.", ephemeral=True)
        except Exception:
            await interaction.followup.send("حدث خطأ أثناء رفع الدليل، حاول مرة ثانية.", ephemeral=True)

class TaskCompleteButton(discord.ui.Button):
    def __init__(self, task_id):
        super().__init__(label="إكمال موظف", emoji="🏁", style=discord.ButtonStyle.primary, custom_id=f"task:complete:{task_id}")
        self.task_id = task_id
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        participants = await get_task_participants(self.task_id)
        if not participants:
            return await interaction.response.send_message("لا يوجد موظفون قبلوا هذه المهمة حتى الآن.", ephemeral=True)
        await interaction.response.send_message("اختر الموظف الذي أكمل المهمة:", view=TaskParticipantView(self.task_id), ephemeral=True)

class TaskCloseButton(discord.ui.Button):
    def __init__(self, task_id):
        super().__init__(label="إغلاق المهمة", emoji="🔒", style=discord.ButtonStyle.danger, custom_id=f"task:close:{task_id}")
        self.task_id = task_id
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        await close_task(self.task_id, interaction.guild.id)
        try:
            await interaction.message.edit(embed=await build_task_embed(self.task_id), view=await build_task_view(self.task_id))
        except discord.HTTPException: pass
        await interaction.response.send_message("تم إغلاق المهمة ولن يستطيع أحد قبولها.", ephemeral=True)

class TaskReviewView(discord.ui.View):
    def __init__(self, task_id, user_id, disabled=False):
        super().__init__(timeout=None)
        self.add_item(TaskApproveButton(task_id, user_id, disabled))
        self.add_item(TaskRejectButton(task_id, user_id, disabled))

class TaskApproveButton(discord.ui.Button):
    def __init__(self, task_id, user_id, disabled=False):
        super().__init__(label="قبول واحتساب +7", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"task:approve:{task_id}:{user_id}", disabled=disabled)
        self.task_id, self.user_id = task_id, user_id
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        result = await approve_task_submission(self.task_id, interaction.guild.id, self.user_id, interaction.user.id, datetime.now(timezone.utc).isoformat())
        if result == "approved":
            points = await get_points(interaction.guild.id, self.user_id)
            member = interaction.guild.get_member(self.user_id)
            name = member.mention if member else f"<@{self.user_id}>"
            await interaction.response.edit_message(content=f"✅ تم اعتماد المهمة لـ {name} وإضافة **7 نقاط**.\nالرصيد الآن: **{format_points(points)} نقطة**", view=TaskReviewView(self.task_id, self.user_id, True))
            await send_admin_log(interaction, "✅ اعتماد مهمة", f"الموظف: <@{self.user_id}>\nرقم المهمة: {self.task_id}\nالنقاط: +7")
        elif result == "already_completed":
            await interaction.response.send_message("هذه المهمة محتسبة مسبقًا.", ephemeral=True)
        else:
            await interaction.response.send_message("لا يوجد إنجاز بانتظار المراجعة لهذا الموظف.", ephemeral=True)

class TaskRejectButton(discord.ui.Button):
    def __init__(self, task_id, user_id, disabled=False):
        super().__init__(label="رفض", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"task:reject:{task_id}:{user_id}", disabled=disabled)
        self.task_id, self.user_id = task_id, user_id
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        result = await reject_task_submission(self.task_id, interaction.guild.id, self.user_id, datetime.now(timezone.utc).isoformat())
        if result == "rejected":
            member = interaction.guild.get_member(self.user_id)
            name = member.mention if member else f"<@{self.user_id}>"
            await interaction.response.edit_message(content=f"❌ تم رفض إنجاز المهمة لـ {name}. يمكن للموظف إعادة إرسال الدليل.", view=TaskReviewView(self.task_id, self.user_id, True))
            await send_admin_log(interaction, "❌ رفض إنجاز مهمة", f"الموظف: <@{self.user_id}>\nرقم المهمة: {self.task_id}")
        else:
            await interaction.response.send_message("لا يوجد إنجاز بانتظار المراجعة.", ephemeral=True)

class TaskView(discord.ui.View):
    def __init__(self, task_id, maximum=1, count=0, status="open"):
        super().__init__(timeout=None)
        self.add_item(TaskAcceptButton(task_id, disabled=(status != "open" or count >= maximum)))
        self.add_item(TaskEvidenceButton(task_id))

class TaskParticipantSelect(discord.ui.UserSelect):
    def __init__(self, task_id):
        self.task_id = task_id
        super().__init__(placeholder="اختر الموظف", min_values=1, max_values=1)
    async def callback(self, interaction):
        user = self.values[0]
        result = await complete_task_for_user(self.task_id, interaction.guild.id, user.id, interaction.user.id, datetime.now(timezone.utc).isoformat())
        if result == "completed":
            points = await get_points(interaction.guild.id, user.id)
            await interaction.response.send_message(f"تم احتساب المهمة لـ {user.mention} وإضافة **7 نقاط**. رصيده الآن **{format_points(points)} نقطة**.", ephemeral=True)
            await send_admin_log(interaction, "🏁 إكمال مهمة", f"الموظف: {user.mention}\nرقم المهمة: {self.task_id}\nالنقاط: +7\nالرصيد الجديد: {format_points(points)}")
        elif result == "already_completed":
            await interaction.response.send_message("هذه المهمة محتسبة لهذا الموظف مسبقًا.", ephemeral=True)
        elif result == "no_evidence":
            await interaction.response.send_message("هذا الموظف لم يرسل دليل المهمة حتى الآن.", ephemeral=True)
        else:
            await interaction.response.send_message("هذا الموظف غير مسجل ضمن المشاركين في المهمة.", ephemeral=True)

class TaskParticipantView(discord.ui.View):
    def __init__(self, task_id):
        super().__init__(timeout=120)
        self.add_item(TaskParticipantSelect(task_id))

async def build_task_embed(task_id):
    task = await get_task(task_id)
    if not task:
        return discord.Embed(title="مهمة غير موجودة")

    participants = await get_task_participants(task_id)
    maximum = int(task[7])
    count = len(participants)
    status = task[8]
    status_text = "🟢 مفتوحة" if status == "open" and count < maximum else ("🟠 مكتملة العدد" if status == "full" or count >= maximum else "🔒 مغلقة")

    # كل مقعد يبقى ثابتًا: المقبول يظهر منشنه، والمقاعد المتبقية تبقى شاغرة.
    seats = []
    for index in range(maximum):
        if index < count:
            user_id = participants[index][0]
            seats.append(f"**المقعد {index + 1}:** <@{user_id}>")
        else:
            seats.append(f"**المقعد {index + 1}:** شاغر")

    embed = discord.Embed(title=f"📋 | مهمة — {task[4]}", description=task[5])
    embed.add_field(name="👥 المقاعد", value="\n".join(seats), inline=False)
    embed.add_field(name="الحالة", value=status_text, inline=True)
    embed.add_field(name="الإنجاز", value="اضغط إكمال المهمة وأرسل صورة، ثم تعتمدها الإدارة", inline=False)
    embed.set_footer(text=f"رقم المهمة: {task_id}")
    embed.set_image(url=task[6])
    return embed

async def build_task_view(task_id):
    task = await get_task(task_id)
    if not task: return TaskView(task_id, 1, 1, "closed")
    count = await get_task_participant_count(task_id)
    return TaskView(task_id, task[7], count, task[8])

class TaskPublishButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="نشر مهمة", emoji="📋", style=discord.ButtonStyle.success, custom_id="admin:publish_task")
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        await interaction.response.send_modal(TaskPublishModal(interaction.channel))

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

STRIKE_ROLES = {
    1: 1539288778210943069,
    2: 1539289156059140309,
    3: 1539289310321180853,
}

class DisciplineReasonModal(discord.ui.Modal):
    def __init__(self, user_id: int, mention: str, strike_level: int):
        super().__init__(title=f"محاسبة - Strike {strike_level}")
        self.user_id = user_id
        self.mention = mention
        self.strike_level = strike_level
        self.reason = discord.ui.TextInput(
            label="سبب المحاسبة",
            placeholder="اكتب سبب الاسترايك",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=800,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        member = interaction.guild.get_member(self.user_id)
        if not member:
            return await interaction.response.send_message("تعذر العثور على الموظف داخل السيرفر.", ephemeral=True)
        channel = await get_log_channel(interaction, "discipline_log")
        if not channel:
            return await interaction.response.send_message("روم المحاسبات غير محدد. عيّنه من `/settings` أولًا.", ephemeral=True)

        now = datetime.now(timezone.utc)
        await add_disciplinary_action(
            interaction.guild.id, member.id, self.strike_level, self.reason.value,
            interaction.user.id, now.isoformat()
        )

        attendance_level = await get_attendance_strike_level(interaction.guild.id, member.id)
        manual_level = await get_manual_strike_level(interaction.guild.id, member.id)
        effective_level = max(attendance_level, manual_level)

        for rid in STRIKE_ROLES.values():
            role = interaction.guild.get_role(rid)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="تحديث رتبة الاسترايك بعد المحاسبة")
                except discord.HTTPException:
                    pass
        strike_role = interaction.guild.get_role(STRIKE_ROLES.get(effective_level)) if effective_level else None
        if strike_role:
            try:
                await member.add_roles(strike_role, reason=f"محاسبة إدارية - Strike {self.strike_level}")
            except discord.HTTPException:
                strike_role = None

        embed = discord.Embed(
            title="بسم الله الرحمن الرحيم",
            description=(
                "**قرار إداري**\n\n"
                f"يتم تحذير العضو: {member.mention}\n\n"
                f"**نوع التحذير:** Strike {self.strike_level}\n\n"
                f"**سبب التحذير:**\n{self.reason.value}\n\n"
                "نأمل من العضو الانتباه والالتزام بالأنظمة والتعليمات، وعدم تكرار المخالفة مستقبلاً.\n\n"
                f"اعتمدت بواسطة: {interaction.user.mention}"
            ),
            timestamp=now
        )
        await channel.send(content=member.mention + "\n||@here||", embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=True))

        await interaction.response.send_message(
            f"تمت محاسبة {member.mention} بـ **Strike {self.strike_level}** وإرسالها في {channel.mention}.",
            ephemeral=True,
        )
        await send_admin_log(interaction, "⚠️ محاسبة موظف", f"الموظف: {member.mention}\
Strike: {self.strike_level}\
السبب: {self.reason.value}")

class DisciplineLevelSelect(discord.ui.Select):
    def __init__(self, user_id: int, mention: str):
        self.user_id = user_id
        self.mention = mention
        super().__init__(
            placeholder="اختر Strike 1 أو 2 أو 3",
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(label="Strike 1", value="1"),
                discord.SelectOption(label="Strike 2", value="2"),
                discord.SelectOption(label="Strike 3", value="3"),
            ],
        )
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DisciplineReasonModal(self.user_id, self.mention, int(self.values[0])))

class DisciplineLevelView(discord.ui.View):
    def __init__(self, user_id: int, mention: str):
        super().__init__(timeout=120)
        self.add_item(DisciplineLevelSelect(user_id, mention))



class OpenMemberTicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="فتح تكت مع عضو")
        self.member_id = discord.ui.TextInput(
            label="Discord ID للعضو",
            placeholder="ضع Copy ID هنا",
            required=True,
            max_length=30
        )
        self.add_item(self.member_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        try:
            member_id = int(self.member_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("الـ ID غير صحيح.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(member_id)
        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except discord.HTTPException:
                member = None

        if member is None:
            return await interaction.response.send_message("لم يتم العثور على العضو.", ephemeral=True)

        category_id = await get_setting(guild.id, "application_ticket_category")
        category = guild.get_channel(int(category_id)) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "كاتقوري التكتات غير محدد. اضبطه من `/settings`.",
                ephemeral=True
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        ticket = await guild.create_text_channel(
            name=f"اداري-{member.name}".replace(" ", "-")[:90],
            category=category,
            overwrites=overwrites,
            reason=f"فتح تكت إداري بواسطة {interaction.user}"
        )

        embed = discord.Embed(
            title="🎫 تكت إداري",
            description=f"تم فتح تكت مع {member.mention}\n\nيرجى استخدام التكت للموضوع الإداري فقط.",
            timestamp=datetime.now(timezone.utc)
        )
        await ticket.send(
            content=member.mention,
            embed=embed,
            view=TicketControlView()
        )

        await interaction.response.send_message(
            f"✅ تم فتح التكت: {ticket.mention}",
            ephemeral=True
        )


class OpenMemberTicketButton(AdminButton if False else discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="فتح تكت مع عضو",
            emoji="🎫",
            style=discord.ButtonStyle.primary,
            custom_id="admin:open_member_ticket"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        await interaction.response.send_modal(OpenMemberTicketModal())


class AdminButton(discord.ui.Button):
    def __init__(self, label, custom_id, action, style=discord.ButtonStyle.secondary):
        self.action = action
        super().__init__(label=label, custom_id=custom_id, style=style)
    async def callback(self, interaction):
        if not await admin_allowed(interaction): return
        if self.action in ("force","add","remove","task","stats","reset","fire","reapply","discipline"):
            labels = {"force":"اختر الموظف لتسجيل خروجه إجباريًا:", "add":"اختر الموظف لزيادة نقاطه:", "remove":"اختر الموظف لخصم نقاطه:", "task":"اختر الموظف لاحتساب مهمة له:", "stats":"اختر الموظف لعرض إحصائياته:", "reset":"اختر الموظف لتصفير نقاطه:", "fire":"اختر الموظف الذي تريد فصله:", "reapply":"اختر العضو الذي تريد السماح له بإعادة التقديم:", "discipline":"اختر الموظف الذي تريد محاسبته:"}
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
            embed = discord.Embed(title="📊 إحصائيات جميع الموظفين", description="ترتيب الموظفين حسب النقاط")
            lines = []
            for i, (uid, points, seconds, invoices, tasks) in enumerate(rows[:30], 1):
                member = interaction.guild.get_member(uid)
                name = member.mention if member else f"<@{uid}>"
                lines.append(f"**#{i}** {name}\nالنقاط: **{format_points(points)}** | الساعات: **{format_duration(seconds)}** | الفواتير: **{invoices}** | المهام: **{tasks}**")
            # Discord يسمح بحقل Description أطول من 2000 فقط عبر embed، مع حد 4096.
            embed.description = "\n\n".join(lines[:30])[:4096]
            return await interaction.response.send_message(embed=embed, ephemeral=True)
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

class AdminDMModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="إرسال رسالة لعضو")
        self.uid=discord.ui.TextInput(label="Discord User ID",required=True,max_length=22)
        self.msg=discord.ui.TextInput(label="الرسالة",style=discord.TextStyle.paragraph,required=True,max_length=1500)
        self.add_item(self.uid);self.add_item(self.msg)
    async def on_submit(self,interaction):
        if not await admin_allowed(interaction):return
        try: uid=int(str(self.uid.value).strip())
        except ValueError:return await interaction.response.send_message("User ID غير صحيح.",ephemeral=True)
        try: target=interaction.guild.get_member(uid) or await interaction.client.fetch_user(uid);await target.send(embed=discord.Embed(title="☕ رسالة من إدارة Bean Machine",description=self.msg.value,timestamp=datetime.now(timezone.utc)))
        except (discord.Forbidden,discord.HTTPException):return await interaction.response.send_message("تعذر إرسال الرسالة؛ قد يكون الخاص مقفلًا.",ephemeral=True)
        await interaction.response.send_message(f"تم إرسال الرسالة إلى <@{uid}>.",ephemeral=True);await send_admin_log(interaction,"✉️ رسالة خاصة لعضو",f"العضو: <@{uid}> (`{uid}`)\nالرسالة:\n{self.msg.value}")
class AdminDMButton(discord.ui.Button):
    def __init__(self):super().__init__(label="إرسال رسالة لعضو",emoji="✉️",style=discord.ButtonStyle.primary,custom_id="admin:send_dm")
    async def callback(self,interaction):
        if not await admin_allowed(interaction):return
        await interaction.response.send_modal(AdminDMModal())


class AdminEmployeeProfileModal(discord.ui.Modal):
    def __init__(self, user_id: int, current_profile=None):
        title = "تعديل بيانات موظف" if current_profile else "تسجيل بيانات موظف"
        super().__init__(title=title)
        self.user_id = user_id
        self.current_profile = current_profile

        game_default = current_profile[1] if current_profile else None
        phone_default = current_profile[2] if current_profile else None
        citizen_default = current_profile[3] if current_profile else None

        self.game_name = discord.ui.TextInput(
            label="الاسم داخل اللعبة",
            placeholder="اكتب اسم الموظف داخل اللعبة",
            required=True,
            max_length=100,
            default=game_default
        )
        self.phone_number = discord.ui.TextInput(
            label="رقم الجوال داخل اللعبة",
            placeholder="اكتب رقم الجوال",
            required=True,
            max_length=50,
            default=phone_default
        )
        self.citizen_id = discord.ui.TextInput(
            label="Citizen ID",
            placeholder="اكتب Citizen ID",
            required=True,
            max_length=100,
            default=citizen_default
        )

        self.add_item(self.game_name)
        self.add_item(self.phone_number)
        self.add_item(self.citizen_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        existing = await get_employee_profile(interaction.guild.id, self.user_id)
        hired_at = existing[4] if existing else datetime.now(timezone.utc).isoformat()

        await save_employee_profile(
            interaction.guild.id,
            self.user_id,
            self.game_name.value,
            self.phone_number.value,
            self.citizen_id.value,
            hired_at
        )

        # إذا كان تسجيل جديد، نحاول إعطاء رتبة الموظف مثل قبول الموارد البشرية.
        role_note = ""
        member = interaction.guild.get_member(self.user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(self.user_id)
            except discord.HTTPException:
                member = None

        if (not existing or existing[5] not in ("active", "vacation")) and member:
            role_id = await get_setting(interaction.guild.id, "employee_role")
            role = interaction.guild.get_role(int(role_id)) if role_id else None
            if role and role not in member.roles:
                try:
                    await member.add_roles(
                        role,
                        reason=f"تسجيل يدوي في الموارد البشرية بواسطة {interaction.user}"
                    )
                    role_note = f"\nتم إعطاؤه رتبة الموظف {role.mention}."
                except (discord.Forbidden, discord.HTTPException):
                    role_note = "\nتم حفظ البيانات، لكن تعذر إعطاء رتبة الموظف."

        action = "تعديل" if existing else "تسجيل"
        await interaction.response.send_message(
            f"✅ تم **{action} بيانات الموظف** <@{self.user_id}> بنجاح.{role_note}",
            ephemeral=True
        )

        await send_admin_log(
            interaction,
            f"👥 {action} بيانات موظف",
            (
                f"الموظف: <@{self.user_id}> (`{self.user_id}`)\n"
                f"الاسم داخل اللعبة: {self.game_name.value}\n"
                f"رقم الجوال: {self.phone_number.value}\n"
                f"Citizen ID: {self.citizen_id.value}"
            )
        )
        await sync_employee_board(interaction.guild)


class AdminEmployeeProfileActionView(discord.ui.View):
    def __init__(self, user_id: int, profile):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.profile = profile

    @discord.ui.button(label="تعديل البيانات", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction):
            return
        await interaction.response.send_modal(
            AdminEmployeeProfileModal(self.user_id, self.profile)
        )


class AdminEmployeeProfileCreateView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="تسجيل بيانات جديدة", emoji="➕", style=discord.ButtonStyle.success)
    async def create_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction):
            return
        await interaction.response.send_modal(
            AdminEmployeeProfileModal(self.user_id, None)
        )


class AdminEmployeeLookupModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="إدارة بيانات موظف")
        self.user_id = discord.ui.TextInput(
            label="Discord User ID",
            placeholder="الصق Copy User ID هنا",
            required=True,
            max_length=22
        )
        self.add_item(self.user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return

        try:
            uid = int(str(self.user_id.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                "User ID غير صحيح.",
                ephemeral=True
            )

        profile = await get_employee_profile(interaction.guild.id, uid)

        if profile:
            _, game_name, phone, citizen_id, hired_at, status = profile
            embed = discord.Embed(
                title="👥 بيانات الموظف الحالية",
                description=f"<@{uid}> (`{uid}`)"
            )
            embed.add_field(name="الاسم داخل اللعبة", value=game_name, inline=False)
            embed.add_field(name="رقم الجوال", value=phone, inline=True)
            embed.add_field(name="Citizen ID", value=citizen_id, inline=True)
            embed.add_field(name="الحالة", value=status, inline=True)
            await interaction.response.send_message(
                embed=embed,
                view=AdminEmployeeProfileActionView(uid, profile),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"لا توجد بيانات موارد بشرية مسجلة لـ <@{uid}> (`{uid}`).\n"
                "اضغط الزر بالأسفل لتسجيل بياناته كموظف جديد.",
                view=AdminEmployeeProfileCreateView(uid),
                ephemeral=True
            )


class AdminEmployeeProfileButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="إدارة بيانات موظف",
            emoji="👥",
            style=discord.ButtonStyle.secondary,
            custom_id="admin:employee_profile"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        await interaction.response.send_modal(AdminEmployeeLookupModal())



class BulkEmployeeImportButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="إضافة مجموعة موظفين", emoji="📥", style=discord.ButtonStyle.success, custom_id="admin:bulk_employee_import")

    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        role_id = await get_setting(interaction.guild.id, "employee_role")
        employee_role = interaction.guild.get_role(int(role_id)) if role_id else None
        if employee_role is None:
            return await interaction.response.send_message("رتبة الموظف غير محددة. اضبطها من `/settings` أولًا.", ephemeral=True)
        await interaction.response.send_message("📥 ارفع ملف Excel الآن (.xlsx) خلال دقيقتين. الأعمدة المطلوبة: Discord ID | اسم الموظف داخل اللعبة | رقم الموظف | Citizen ID", ephemeral=True)
        def check(m):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id and m.attachments and m.attachments[0].filename.endswith('.xlsx')
        try:
            msg = await interaction.client.wait_for('message', timeout=120, check=check)
            data = await msg.attachments[0].read()
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.xlsx') as f:
                f.write(data); f.flush()
                wb = openpyxl.load_workbook(f.name)
                ws = wb.active
                added = 0; skipped = 0
                for row in ws.iter_rows(min_row=2, values_only=True):
                    uid, game_name, number, citizen = row[:4]
                    if not uid or not game_name or not number or not citizen:
                        continue
                    try:
                        uid = int(uid)
                        member = interaction.guild.get_member(uid)
                        if member is None:
                            try:
                                member = await interaction.guild.fetch_member(uid)
                            except discord.HTTPException:
                                member = None
                        if member is None:
                            skipped += 1
                            continue
                        if employee_role not in member.roles:
                            await member.add_roles(employee_role, reason=f"استيراد موظفين بواسطة {interaction.user}")
                        await save_employee_profile(interaction.guild.id, uid, str(game_name), str(number), str(citizen), datetime.now(timezone.utc).isoformat())
                        added += 1
                    except Exception:
                        skipped += 1
            await sync_employee_board(interaction.guild)
            await interaction.followup.send(f"✅ تم استيراد الموظفين\n\nتمت الإضافة: {added}\nتم التخطي: {skipped}", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("انتهى الوقت.", ephemeral=True)



async def _weekly_target(guild_id: int) -> int:
    raw = await get_setting(guild_id, "weekly_invoice_target")
    try:
        return max(1, int(raw or 15))
    except (TypeError, ValueError):
        return 15

async def build_weekly_report_embed(guild: discord.Guild, title: str = "📊 نتائج الجرد الأسبوعي"):
    rows = await get_all_weekly_activity(guild.id)
    target = await _weekly_target(guild.id)
    embed = discord.Embed(title=title, timestamp=datetime.now(timezone.utc))
    if not rows:
        embed.description = "لا يوجد موظفون في قاعدة البيانات حتى الآن."
        return embed

    active_rows = [r for r in rows if r[5] != "vacation"]
    met = sum(1 for r in active_rows if int(r[1]) >= target)
    not_met = sum(1 for r in active_rows if int(r[1]) < target)
    vacation_count = sum(1 for r in rows if r[5] == "vacation")
    embed.add_field(name="المطلوب", value=f"**{target} فاتورة** لكل موظف", inline=True)
    embed.add_field(name="المتفاعلون", value=str(met), inline=True)
    embed.add_field(name="غير المتفاعلين", value=str(not_met), inline=True)
    if vacation_count:
        embed.add_field(name="مستثنون بإجازة", value=str(vacation_count), inline=True)

    lines = []
    for i, (uid, invoices, work_seconds, task_count, points, status) in enumerate(rows[:35], 1):
        member = guild.get_member(int(uid))
        name = member.mention if member else f"<@{uid}>"
        if status == "vacation":
            state = "🏖️ إجازة — مستثنى"
        elif int(invoices) >= target:
            state = "✅ متفاعل"
        else:
            state = "❌ غير متفاعل"
        lines.append(
            f"**#{i} {name}** — {state}\n"
            f"الفواتير: **{invoices}/{target}** | الساعات: **{format_duration(work_seconds)}** | المهام: **{task_count}** | نقاط الأسبوع: **{format_points(points)}**"
        )
    embed.description = "\n\n".join(lines)[:4096]
    return embed

class WeeklyTargetModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="تحديد المطلوب الأسبوعي")
        self.target = discord.ui.TextInput(label="عدد الفواتير المطلوبة لكل موظف", placeholder="مثال: 15", required=True, max_length=4)
        self.add_item(self.target)

    async def on_submit(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        try:
            value = int(str(self.target.value).strip())
            if value < 1 or value > 9999:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("اكتب عددًا صحيحًا من 1 إلى 9999.", ephemeral=True)
        await set_setting(interaction.guild.id, "weekly_invoice_target", str(value))
        log_channel = await get_log_channel(interaction, "weekly_audit_log")
        if log_channel:
            await log_channel.send(f"🎯 تم تغيير المطلوب الأسبوعي إلى **{value} فاتورة** لكل موظف بواسطة {interaction.user.mention}.")
        await interaction.response.send_message(f"✅ تم تغيير المطلوب الأسبوعي إلى **{value} فاتورة** لكل موظف.", ephemeral=True)
        await send_admin_log(interaction, "📊 تغيير المطلوب الأسبوعي", f"المطلوب الجديد: {value} فاتورة")

class ConfirmWeeklyResetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="تأكيد تصفير الجرد", emoji="♻️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction):
            return
        target = await _weekly_target(interaction.guild.id)
        report = await build_weekly_report_embed(interaction.guild, "📦 أرشيف الجرد قبل التصفير")
        archived_at = datetime.now(timezone.utc).isoformat()
        week_no, rows = await reset_weekly_activity(interaction.guild.id, target, archived_at, interaction.user.id)
        report.set_footer(text=f"الأسبوع رقم {week_no} — تم تصفير جميع إحصائيات الجرد بعد حفظ هذا التقرير")
        log_channel = await get_log_channel(interaction, "weekly_audit_log")
        if log_channel:
            await log_channel.send(embed=report)
            await log_channel.send(f"♻️ **بدأ أسبوع جرد جديد** بواسطة {interaction.user.mention}. جميع عدادات الجرد الأسبوعي عادت إلى صفر.")
        await interaction.response.edit_message(
            content=(f"✅ تم حفظ الأسبوع رقم **{week_no}** وتصفير **كل إحصائيات الجرد الأسبوعي** لجميع الموظفين إلى صفر."
                     + (f"\nتم إرسال الأرشيف إلى {log_channel.mention}." if log_channel else "\n⚠️ لوق الجرد الأسبوعي غير محدد من `/settings`.")),
            embed=None,
            view=None,
        )
        await send_admin_log(interaction, "♻️ تصفير الجرد الأسبوعي", f"الأسبوع المؤرشف: {week_no}\nعدد الموظفين: {len(rows)}\nالمطلوب: {target}")

    @discord.ui.button(label="إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="تم إلغاء تصفير الجرد.", embed=None, view=None)

class WeeklyAuditView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="نتائج الأسبوع", emoji="📊", style=discord.ButtonStyle.primary, custom_id="weekly:results")
    async def results(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction): return
        embed = await build_weekly_report_embed(interaction.guild)
        log_channel = await get_log_channel(interaction, "weekly_audit_log")
        if log_channel:
            await log_channel.send(embed=embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="الأكثر تفاعلًا", emoji="🏆", style=discord.ButtonStyle.success, custom_id="weekly:top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction): return
        rows = [r for r in await get_all_weekly_activity(interaction.guild.id) if r[5] != "vacation"]
        if not rows:
            return await interaction.response.send_message("لا توجد بيانات جرد لهذا الأسبوع.", ephemeral=True)
        max_invoices = max(int(r[1]) for r in rows)
        if max_invoices == 0:
            return await interaction.response.send_message("لا توجد فواتير مسجلة في الجرد الحالي حتى الآن.", ephemeral=True)
        top_rows = [r for r in rows if int(r[1]) == max_invoices]
        names = []
        for uid, invoices, work_seconds, task_count, points, status in top_rows:
            member = interaction.guild.get_member(int(uid))
            names.append(f"{member.mention if member else f'<@{uid}>'} — **{invoices} فاتورة**")
        text = "🏆 **الأكثر تفاعلًا هذا الأسبوع**\n" + "\n".join(names[:25])
        log_channel = await get_log_channel(interaction, "weekly_audit_log")
        if log_channel:
            await log_channel.send(text)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="غير المتفاعلين", emoji="⚠️", style=discord.ButtonStyle.danger, custom_id="weekly:inactive")
    async def inactive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction): return
        target = await _weekly_target(interaction.guild.id)
        rows = [r for r in await get_all_weekly_activity(interaction.guild.id) if r[5] != "vacation" and int(r[1]) < target]
        if not rows:
            return await interaction.response.send_message("✅ جميع الموظفين حققوا المطلوب الأسبوعي.", ephemeral=True)
        lines = []
        for uid, invoices, *_ in rows:
            member = interaction.guild.get_member(int(uid))
            lines.append(f"• {member.mention if member else f'<@{uid}>'} — **{invoices}/{target}**")
        text = "⚠️ **الموظفون غير المحققين للمطلوب**\n" + "\n".join(lines[:40])
        log_channel = await get_log_channel(interaction, "weekly_audit_log")
        if log_channel:
            await log_channel.send(text)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="تغيير المطلوب", emoji="🎯", style=discord.ButtonStyle.secondary, custom_id="weekly:target")
    async def target(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction): return
        await interaction.response.send_modal(WeeklyTargetModal())

    @discord.ui.button(label="تصفير الأسبوع", emoji="♻️", style=discord.ButtonStyle.danger, custom_id="weekly:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await admin_allowed(interaction): return
        await interaction.response.send_message(
            "⚠️ سيتم حفظ تقرير الأسبوع الحالي في لوق الجرد ثم **تصفير الفواتير والساعات والمهام والنقاط الأسبوعية لكل الموظفين إلى 0**.\nهل أنت متأكد؟",
            view=ConfirmWeeklyResetView(), ephemeral=True
        )

class WeeklyAuditOpenButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="الجرد الأسبوعي", emoji="📊", style=discord.ButtonStyle.primary, custom_id="admin:weekly_audit")
    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction): return
        target = await _weekly_target(interaction.guild.id)
        await interaction.response.send_message(
            f"📊 **نظام الجرد الأسبوعي المستقل**\nالمطلوب الحالي: **{target} فاتورة** لكل موظف.\nاختر العملية:",
            view=WeeklyAuditView(), ephemeral=True
        )

class EmployeeBoardButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="تحديث لوحة الموظفين", emoji="👥", style=discord.ButtonStyle.success, custom_id="admin:employee_board")
    async def callback(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction): return
        await interaction.response.defer(ephemeral=True)
        message = await sync_employee_board(interaction.guild, view=EmployeeDatabaseView())
        if message:
            await interaction.followup.send(f"✅ تم تحديث لوحة الموظفين الثابتة: {message.jump_url}", ephemeral=True)
        else:
            await interaction.followup.send("تعذر تحديث اللوحة. تأكد من ضبط روم **قاعدة بيانات الموظفين** وصلاحيات البوت.", ephemeral=True)

class AdminPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminButton("تسجيل خروج إجباري","admin:force_checkout","force",discord.ButtonStyle.danger))
        self.add_item(AdminButton("زيادة نقاط","admin:add_points","add",discord.ButtonStyle.success))
        self.add_item(AdminButton("خصم نقاط","admin:remove_points","remove",discord.ButtonStyle.danger))
        self.add_item(AdminButton("احتساب مهمة","admin:add_task","task",discord.ButtonStyle.success))
        self.add_item(TaskPublishButton())
        self.add_item(AdminButton("المسجلون دخول الآن","admin:active","active"))
        self.add_item(AdminButton("إحصائيات الجميع","admin:stats_all","all"))
        self.add_item(AdminButton("إحصائيات موظف","admin:stats_one","stats"))
        self.add_item(AdminButton("تصفير نقاط الجميع","admin:reset_all","reset_all",discord.ButtonStyle.danger))
        self.add_item(AdminButton("تصفير نقاط موظف","admin:reset_one","reset",discord.ButtonStyle.danger))
        self.add_item(AdminButton("فصل موظف","admin:fire_employee","fire",discord.ButtonStyle.danger))
        self.add_item(AdminButton("سماح إعادة تقديم","admin:allow_reapply","reapply",discord.ButtonStyle.success))
        self.add_item(AdminButton("محاسبة موظف","admin:discipline","discipline",discord.ButtonStyle.danger))
        self.add_item(OpenMemberTicketButton())
        self.add_item(AdminDMButton())
        self.add_item(AdminEmployeeProfileButton())
        self.add_item(BulkEmployeeImportButton())
        self.add_item(WeeklyAuditOpenButton())
        self.add_item(EmployeeBoardButton())

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

        allowed, reason = await can_user_apply(interaction.guild.id, interaction.user.id)
        if not allowed:
            return await interaction.response.send_message(f"❌ {reason}", ephemeral=True)

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
        if not interaction.guild:
            return await interaction.response.send_message("التقديم يعمل داخل السيرفر فقط.", ephemeral=True)
        allowed, reason = await can_user_apply(interaction.guild.id, interaction.user.id)
        if not allowed:
            return await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
        await interaction.response.send_modal(ApplicationModal())


class ApplicationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ApplicationButton())


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
            label="سبب الإجازة", placeholder="اكتب سبب الإجازة", required=True,
            style=discord.TextStyle.paragraph, max_length=500
        )
        self.duration_input = discord.ui.TextInput(
            label="عدد أيام الإجازة", placeholder="مثال: 3", required=True, max_length=3
        )
        self.add_item(self.reason_input)
        self.add_item(self.duration_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("طلب الإجازة يعمل داخل السيرفر فقط.", ephemeral=True)
        if not await employee_allowed(interaction):
            return
        try:
            days = int(str(self.duration_input.value).strip())
            if days < 1 or days > 365:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("اكتب **عدد الأيام كرقم** من 1 إلى 365. مثال: `3`", ephemeral=True)

        review_id = await get_setting(interaction.guild.id, "vacation_review")
        review_channel = interaction.guild.get_channel(int(review_id)) if review_id else None
        if not isinstance(review_channel, discord.TextChannel):
            return await interaction.response.send_message("روم مراجعة الإجازات غير محدد أو غير صالح. اضبطه من `/settings`.", ephemeral=True)

        now = datetime.now(timezone.utc)
        vacation_id = await create_vacation_request(
            interaction.guild.id, interaction.user.id, self.reason_input.value, days, now.isoformat()
        )
        if not vacation_id:
            return await interaction.response.send_message("عندك طلب إجازة قيد المراجعة أو إجازة فعالة بالفعل.", ephemeral=True)

        embed = discord.Embed(title="🏖️ طلب إجازة جديد", timestamp=now)
        embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
        embed.add_field(name="سبب الإجازة", value=self.reason_input.value, inline=False)
        embed.add_field(name="عدد الأيام", value=f"{days} يوم", inline=True)
        embed.add_field(name="رقم الطلب", value=f"#{vacation_id}", inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        await review_channel.send(embed=embed, view=VacationReviewView(vacation_id))
        await interaction.response.send_message("✅ تم إرسال طلب إجازتك للإدارة بنجاح.", ephemeral=True)


class VacationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="طلب إجازة", emoji="🏖️", style=discord.ButtonStyle.primary, custom_id="panel:vacation")
    async def callback(self, interaction: discord.Interaction):
        if not await employee_allowed(interaction):
            return
        await interaction.response.send_modal(VacationModal())


async def restore_employee_from_vacation(guild: discord.Guild, member: discord.Member, reason: str):
    vacation_role_id = await get_setting(guild.id, "vacation_role")
    employee_role_id = await get_setting(guild.id, "employee_role")
    vacation_role = guild.get_role(int(vacation_role_id)) if vacation_role_id else None
    employee_role = guild.get_role(int(employee_role_id)) if employee_role_id else None
    if vacation_role and vacation_role in member.roles:
        await member.remove_roles(vacation_role, reason=reason)
    if employee_role and employee_role not in member.roles:
        await member.add_roles(employee_role, reason=reason)


class BreakVacationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="كسر الإجازة", emoji="↩️", style=discord.ButtonStyle.danger, custom_id="panel:break_vacation")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("هذا الزر يعمل داخل السيرفر فقط.", ephemeral=True)
        vacation = await get_active_vacation(interaction.guild.id, interaction.user.id)
        if not vacation:
            return await interaction.response.send_message("ما عندك إجازة فعالة حاليًا.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await restore_employee_from_vacation(interaction.guild, interaction.user, "كسر الإجازة بواسطة الموظف")
        except discord.Forbidden:
            return await interaction.followup.send("البوت لا يقدر يعدّل الرتب. تأكد أن رتبة البوت أعلى من رتب الموظف والإجازة.", ephemeral=True)
        now = datetime.now(timezone.utc)
        await end_vacation(vacation[0], now.isoformat(), "broken_by_employee")
        await sync_employee_board(interaction.guild)
        log_channel = await get_log_channel(interaction, "vacation_log")
        if log_channel:
            embed = discord.Embed(title="↩️ كسر إجازة", timestamp=now)
            embed.add_field(name="الموظف", value=interaction.user.mention, inline=False)
            embed.add_field(name="الإجازة الأصلية", value=f"{vacation[4]} يوم", inline=True)
            embed.add_field(name="النهاية الأصلية", value=str(vacation[8] or "-")[:19].replace("T", " "), inline=True)
            await log_channel.send(embed=embed)
        await interaction.followup.send("✅ تم كسر الإجازة وإرجاع رتبة الموظف. رجعت لك صلاحيات أنظمة الموظفين.", ephemeral=True)


class VacationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VacationButton())
        self.add_item(BreakVacationButton())


class VacationReviewView(discord.ui.View):
    def __init__(self, vacation_id: int):
        super().__init__(timeout=None)
        self.vacation_id = int(vacation_id)
        accept = discord.ui.Button(label="قبول", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"vacation:accept:{vacation_id}")
        reject = discord.ui.Button(label="رفض", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"vacation:reject:{vacation_id}")
        accept.callback = self.accept_vacation
        reject.callback = self.reject_vacation
        self.add_item(accept); self.add_item(reject)

    async def accept_vacation(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        vacation = await get_vacation(self.vacation_id)
        if not vacation or vacation[5] != "pending":
            return await interaction.response.send_message("تمت مراجعة طلب الإجازة مسبقًا.", ephemeral=True)
        _, guild_id, employee_id, reason, days, *_ = vacation
        guild = interaction.guild
        member = guild.get_member(employee_id)
        if member is None:
            try:
                member = await guild.fetch_member(employee_id)
            except discord.HTTPException:
                member = None
        if member is None:
            return await interaction.response.send_message("ما قدرت ألقى الموظف داخل السيرفر.", ephemeral=True)

        vacation_role_id = await get_setting(guild.id, "vacation_role")
        employee_role_id = await get_setting(guild.id, "employee_role")
        vacation_role = guild.get_role(int(vacation_role_id)) if vacation_role_id else None
        employee_role = guild.get_role(int(employee_role_id)) if employee_role_id else None
        if vacation_role is None:
            return await interaction.response.send_message("رتبة الإجازة غير محددة. اضبطها من `/settings`.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # إذا كان الموظف داخل الدوام، ننهي الجلسة طبيعيًا عند بدء الإجازة بدون احتساب خروج إجباري/Strike.
        active_attendance = await get_active_attendance(guild.id, member.id)
        ended_shift_text = None
        if active_attendance:
            session_id, check_in_at, _ = active_attendance
            shift_end = datetime.now(timezone.utc)
            worked = max(0, int((shift_end - datetime.fromisoformat(check_in_at)).total_seconds()))
            earned = round((worked / 3600) * 5, 2)
            await finish_attendance(
                session_id, guild.id, member.id, shift_end.isoformat(),
                "vacation:auto", worked, earned, interaction.user.id
            )
            ended_shift_text = f"{format_duration(worked)} / {format_points(earned)} نقطة"

        try:
            # نعطي رتبة الإجازة أولًا حتى لا يعتبر نظام الفصل التلقائي سحب رتبة الموظف فصلًا.
            if vacation_role not in member.roles:
                await member.add_roles(vacation_role, reason=f"قبول إجازة بواسطة {interaction.user}")
            if employee_role and employee_role in member.roles:
                await member.remove_roles(employee_role, reason=f"بدء إجازة بواسطة {interaction.user}")
        except discord.Forbidden:
            return await interaction.followup.send("البوت ما يقدر يعدّل رتب الموظف/الإجازة. تأكد من ترتيب الرتب وصلاحية Manage Roles.", ephemeral=True)

        start_at = datetime.now(timezone.utc)
        end_at = start_at + timedelta(days=int(days))
        await accept_vacation(self.vacation_id, start_at.isoformat(), end_at.isoformat(), start_at.isoformat(), interaction.user.id)
        await sync_employee_board(guild)

        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب إجازة")
            embed.add_field(name="الحالة", value=f"✅ مقبولة بواسطة {interaction.user.mention}", inline=False)
            embed.add_field(name="بداية الإجازة", value=f"<t:{int(start_at.timestamp())}:F>", inline=True)
            embed.add_field(name="نهاية الإجازة", value=f"<t:{int(end_at.timestamp())}:F>", inline=True)
            await interaction.message.edit(embed=embed, view=None)

        await interaction.followup.send(
            f"✅ تم قبول إجازة {member.mention} لمدة **{days} يوم**.\nتم سحب رتبة الموظف وإعطاؤه {vacation_role.mention}.\nترجع رتبة الموظف تلقائيًا عند انتهاء الإجازة.",
            ephemeral=True
        )
        log_text = f"الموظف: {member.mention}\nالمدة: {days} يوم\nالنهاية: {end_at.isoformat()}"
        if ended_shift_text:
            log_text += f"\nتم إنهاء الدوام عند بدء الإجازة: {ended_shift_text}"
        await send_admin_log(interaction, "🏖️ قبول إجازة", log_text)

    async def reject_vacation(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        vacation = await get_vacation(self.vacation_id)
        if not vacation or vacation[5] != "pending":
            return await interaction.response.send_message("تمت مراجعة طلب الإجازة مسبقًا.", ephemeral=True)
        await reject_vacation(self.vacation_id, datetime.now(timezone.utc).isoformat(), interaction.user.id)
        member = interaction.guild.get_member(vacation[2])
        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="طلب إجازة")
            embed.add_field(name="الحالة", value=f"❌ مرفوضة بواسطة {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=embed, view=None)
        await interaction.response.send_message("تم رفض طلب الإجازة.", ephemeral=True)
        await send_admin_log(interaction, "❌ رفض إجازة", f"الموظف: {member.mention if member else f'<@{vacation[2]}>'}")


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
        await sync_employee_board(guild)

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

        # نشر قرار التوظيف بصيغة بسيطة في روم القرارات بعد نجاح القبول وإعطاء الرتبة.
        decisions_channel = await get_log_channel(interaction, "decisions_channel")
        if decisions_channel:
            decision_message = (
                "بسم الله الرحمن الرحيم\n\n"
                f"يتم تعيين العضو: {member.mention}\n\n"
                f"برتبة: {role.mention}\n\n\n"
                "يرجى من العضو **الرجوع للموقع** في حال الرغبة بمعرفة أي شيء يخص الرتبة أو النظام، "
                "والحرص على **متابعة الرومات المهمة** أولًا بأول والاطلاع على جميع التحديثات والتنبيهات.\n\n"
                f"اعتمدت بواسطة: {interaction.user.mention}"
            )
            await decisions_channel.send(
                content=decision_message,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False)
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

    # إذا كان الموظف في إجازة فعالة ننهيها أولًا حتى لا تعيده مهمة انتهاء الإجازة إلى حالة موظف لاحقًا.
    departed_at = datetime.now(timezone.utc).isoformat()
    active_vacation = await get_active_vacation(guild.id, member.id)
    if active_vacation:
        await end_vacation(active_vacation[0], departed_at, "employee_departure")

    # نحدّث حالة الموظف أولًا حتى لا يسجل مستمع إزالة الرتبة فصلًا تلقائيًا فوق الفصل/الاستقالة اليدوية.
    await remove_employee_profile(guild.id, member.id, departure_type, departed_at, interaction.user.id)

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
        await sync_employee_board(interaction.guild)
        desc = f"الموظف: {member.mention}\nرسالة الإدارة: {self.message_text.value}"
        if worked: desc += f"\nتم إنهاء الدوام: {worked}"
        await send_admin_log(interaction, "فصل موظف", desc)
        await interaction.followup.send(f"تم فصل {member.mention}. تم حفظ سجله كـ **مفصول** ومنعه من إعادة التقديم حتى تسمح له الإدارة." + ("" if dm_ok else "\nتعذر إرسال الخاص للعضو."), ephemeral=True)


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
        await sync_employee_board(interaction.guild)
        if interaction.message:
            e=interaction.message.embeds[0]; e.add_field(name="الحالة",value=f"مقبولة بواسطة {interaction.user.mention}",inline=False); await interaction.message.edit(embed=e,view=None)
        try: await member.send("تم قبول استقالتك من **Bean Machine**.")
        except discord.HTTPException: pass
        await send_admin_log(interaction,"قبول استقالة",f"الموظف: {member.mention}" + (f"\nتم إنهاء الدوام: {worked}" if worked else ""))
        await interaction.followup.send("تم قبول الاستقالة وإزالة الرتب وتحديث الحالة في سجل الموظفين.",ephemeral=True)
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
        rows=await list_current_employee_profiles(interaction.guild.id)
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
        await interaction.response.defer(ephemeral=True)
        message = await sync_employee_board(interaction.guild, view=self)
        await interaction.followup.send("✅ تم تحديث لوحة الموظفين." if message else "تعذر تحديث لوحة الموظفين.", ephemeral=True)

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
            from cogs.web_applications import ApplicationFollowupView
            await interaction.channel.send(embed=discord.Embed(title="📋 | متابعة التقديم", description="التقديم يتم بالكامل من موقع Bean Machine. بعد إرسال الطلب ادخل السيرفر واضغط **📋 متابعة طلبي**. البوت يتعرف على Discord ID تلقائيًا بدون رمز. إذا تم قبولك مبدئيًا ستظهر لك لوحة الموارد البشرية مباشرة."), view=ApplicationFollowupView())
            return await interaction.response.send_message("تم إرسال لوحة متابعة التقديم.", ephemeral=True)

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
            message = await sync_employee_board(interaction.guild, view=EmployeeDatabaseView())
            if not message:
                return await interaction.response.send_message("روم قاعدة بيانات الموظفين غير محدد أو البوت لا يملك صلاحية الإرسال. اضبطه من `/settings`.", ephemeral=True)
            return await interaction.response.send_message(f"✅ تم إنشاء/تحديث لوحة الموظفين الثابتة: {message.jump_url}", ephemeral=True)

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
        self._auto_fire_in_progress = set()
        bot.add_view(EmployeePanel()); bot.add_view(AdminPanel()); bot.add_view(ApplicationPanelView()); bot.add_view(TicketControlView()); bot.add_view(VacationPanelView()); bot.add_view(HRPanelView()); bot.add_view(ResignationPanelView()); bot.add_view(EmployeeDatabaseView()); bot.add_view(WeeklyAuditView())
        asyncio.create_task(self._restore_task_views())
        self.vacation_expiry_loop.start()
        self.employee_reconcile_loop.start()

    def cog_unload(self):
        self.vacation_expiry_loop.cancel()
        self.employee_reconcile_loop.cancel()

    async def _auto_fire_employee(self, guild: discord.Guild, user_id: int, reason: str, member: discord.Member | None = None):
        key = (guild.id, int(user_id))
        if key in self._auto_fire_in_progress:
            return False
        self._auto_fire_in_progress.add(key)
        try:
            profile = await get_employee_profile(guild.id, int(user_id))
            if not profile or profile[5] not in ("active", "vacation"):
                return False

            now = datetime.now(timezone.utc)
            active = await get_active_attendance(guild.id, int(user_id))
            if active:
                session_id, check_in_at, _ = active
                worked = max(0, int((now - datetime.fromisoformat(check_in_at)).total_seconds()))
                earned = round((worked / 3600) * 5, 2)
                await finish_attendance(
                    session_id, guild.id, int(user_id), now.isoformat(),
                    "auto:termination", worked, earned, self.bot.user.id if self.bot.user else None
                )

            active_vacation = await get_active_vacation(guild.id, int(user_id))
            if active_vacation:
                await end_vacation(active_vacation[0], now.isoformat(), "auto_termination")

            departure_type = f"فصل تلقائي - {reason}"
            await remove_employee_profile(
                guild.id, int(user_id), departure_type, now.isoformat(),
                self.bot.user.id if self.bot.user else None
            )
            await sync_employee_board(guild, view=EmployeeDatabaseView())

            channel = guild.get_channel(FIXED_CHANNELS.get("termination_log"))
            if not isinstance(channel, discord.TextChannel):
                admin_log_id = await get_setting(guild.id, "admin_log")
                channel = guild.get_channel(int(admin_log_id)) if admin_log_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    embed=discord.Embed(
                        title="🤖 فصل تلقائي",
                        description=f"الموظف: <@{user_id}>\nالسبب: **{reason}**\nتم تحديث لوحة الموظفين ومنع إعادة التقديم تلقائيًا.",
                        timestamp=now,
                    )
                )
            return True
        finally:
            self._auto_fire_in_progress.discard(key)

    async def _reconcile_guild_employees(self, guild: discord.Guild):
        employee_role_id = await get_setting(guild.id, "employee_role")
        if not employee_role_id:
            return
        employee_role = guild.get_role(int(employee_role_id))
        if employee_role is None:
            # إذا حذفت الرتبة نفسها لا نفصل الجميع بالخطأ؛ يجب ضبط رتبة موظف صحيحة أولًا.
            return

        vacation_role_id = await get_setting(guild.id, "vacation_role")
        vacation_role = guild.get_role(int(vacation_role_id)) if vacation_role_id else None
        rows = await list_current_employee_profiles(guild.id)
        for user_id, _name, _phone, _citizen, _hired, status in rows:
            member = guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(user_id))
                except discord.NotFound:
                    await self._auto_fire_employee(guild, int(user_id), "غادر السيرفر")
                    continue
                except discord.HTTPException:
                    # فشل مؤقت في Discord API؛ لا نفصل الموظف اعتمادًا على خطأ اتصال.
                    continue

            if status == "vacation":
                # الموظف في إجازة معتمدة لا يلزمه حمل رتبة الموظف حتى انتهاء الإجازة.
                continue
            if employee_role not in member.roles:
                if vacation_role and vacation_role in member.roles:
                    continue
                await self._auto_fire_employee(guild, int(user_id), "رتبة الموظف غير موجودة", member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._auto_fire_employee(member.guild, member.id, "غادر السيرفر", member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        employee_role_id = await get_setting(after.guild.id, "employee_role")
        if not employee_role_id:
            return
        employee_role_id = int(employee_role_id)
        if after.guild.get_role(employee_role_id) is None:
            # إذا حُذفت رتبة الموظف نفسها لا نفصل الجميع تلقائيًا.
            return
        had_employee_role = any(role.id == employee_role_id for role in before.roles)
        has_employee_role = any(role.id == employee_role_id for role in after.roles)
        if not had_employee_role or has_employee_role:
            return

        # سحب رتبة الموظف عند بدء الإجازة مقصود ولا يعتبر فصلًا.
        vacation_role_id = await get_setting(after.guild.id, "vacation_role")
        if vacation_role_id and any(role.id == int(vacation_role_id) for role in after.roles):
            return
        profile = await get_employee_profile(after.guild.id, after.id)
        if profile and profile[5] == "vacation":
            return
        await self._auto_fire_employee(after.guild, after.id, "تم سحب رتبة الموظف", after)

    @discord_tasks.loop(minutes=5)
    async def employee_reconcile_loop(self):
        for guild in self.bot.guilds:
            try:
                await self._reconcile_guild_employees(guild)
                await sync_employee_board(guild, view=EmployeeDatabaseView())
            except Exception as exc:
                print(f"⚠️ تعذر تدقيق الموظفين تلقائيًا للسيرفر {guild.id}: {exc}")

    @employee_reconcile_loop.before_loop
    async def before_employee_reconcile_loop(self):
        await self.bot.wait_until_ready()

    @discord_tasks.loop(minutes=1)
    async def vacation_expiry_loop(self):
        now = datetime.now(timezone.utc)
        expired = await get_expired_vacations(now.isoformat())
        for vacation in expired:
            vacation_id, guild_id, user_id = vacation[0], vacation[1], vacation[2]
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            member = guild.get_member(int(user_id))
            if member:
                try:
                    await restore_employee_from_vacation(guild, member, "انتهاء الإجازة تلقائيًا")
                except (discord.Forbidden, discord.HTTPException):
                    # لا ننهي السجل حتى تنجح إعادة الرتب؛ سيعيد البوت المحاولة في الدورة التالية.
                    continue
            await end_vacation(vacation_id, now.isoformat(), "expired")
            await sync_employee_board(guild)
            channel_id = await get_setting(guild.id, "vacation_log")
            if not channel_id:
                channel_id = FIXED_CHANNELS.get("vacation_log")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    embed=discord.Embed(
                        title="✅ انتهاء إجازة تلقائيًا",
                        description=f"الموظف: <@{user_id}>\nتمت إزالة رتبة الإجازة وإرجاع رتبة الموظف تلقائيًا.",
                        timestamp=now,
                    )
                )

    @vacation_expiry_loop.before_loop
    async def before_vacation_expiry_loop(self):
        await self.bot.wait_until_ready()
    async def _restore_task_views(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                await self._reconcile_guild_employees(guild)
                await sync_employee_board(guild, view=EmployeeDatabaseView())
            except Exception as exc:
                print(f"⚠️ تعذر تحديث لوحة الموظفين عند التشغيل للسيرفر {guild.id}: {exc}")
            try:
                for (vacation_id,) in await get_pending_vacations(guild.id):
                    self.bot.add_view(VacationReviewView(vacation_id))
            except Exception as exc:
                print(f"⚠️ تعذر استعادة أزرار الإجازات المعلقة للسيرفر {guild.id}: {exc}")
        guild_id = self.bot.guilds[0].id if self.bot.guilds else None
        if not guild_id:
            return
        tasks = await get_active_tasks(guild_id)
        # المهام المفتوحة/المكتملة العدد تحتاج إعادة تسجيل أزرارها بعد إعادة تشغيل البوت.
        for task in tasks:
            if task[3]:
                try:
                    self.bot.add_view(TaskView(task[0], task[7], await get_task_participant_count(task[0]), task[8]), message_id=task[3])
                except Exception as exc:
                    print(f"⚠️ تعذر إعادة تسجيل View للمهمة {task[0]}: {exc}")
        for task_id, user_id in await get_pending_task_submissions(guild_id):
            try:
                self.bot.add_view(TaskReviewView(task_id, user_id), message_id=None)
            except Exception as exc:
                print(f"⚠️ تعذر إعادة تسجيل مراجعة المهمة {task_id}/{user_id}: {exc}")

    @app_commands.command(name="لوحة-الجرد", description="إرسال لوحة الجرد الأسبوعي في روم الجرد المخصص")
    async def weekly_audit_panel(self, interaction: discord.Interaction):
        if not await admin_allowed(interaction):
            return
        channel_id = await get_setting(interaction.guild.id, "weekly_audit_log")
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
        if not channel:
            return await interaction.response.send_message("حدد روم **لوق الجرد الأسبوعي** من `/settings` أولًا.", ephemeral=True)
        target = await _weekly_target(interaction.guild.id)
        embed = discord.Embed(
            title="📊 | لوحة الجرد الأسبوعي",
            description=(
                f"المطلوب الحالي لكل موظف: **{target} فاتورة أسبوعيًا**.\n\n"
                "من هذه اللوحة تستطيع عرض نتائج الأسبوع، معرفة الأكثر تفاعلًا وغير المتفاعلين، تغيير المطلوب، أو تصفير جميع إحصائيات الجرد وبدء أسبوع جديد."
            )
        )
        await channel.send(embed=embed, view=WeeklyAuditView())
        await interaction.response.send_message(f"✅ تم إرسال لوحة الجرد إلى {channel.mention}.", ephemeral=True)

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

🆕 **نشر مهمة**
إنشاء مهمة جديدة بشرح وصورة وتحديد الحد الأقصى للمشاركين، مع زر قبول يمنع أي قبول إضافي بعد اكتمال العدد.

🟢 **المسجلون دخول الآن**
عرض جميع الموظفين الموجودين في الدوام حاليًا ومدة عمل كل موظف.

📊 **إحصائيات الجميع**
عرض وترتيب جميع الموظفين حسب النقاط، مع الساعات والفواتير والمهام.

👤 **إحصائيات موظف**
اختيار موظف وعرض نقاطه وساعات عمله وفواتيره ومهامه وحالة دوامه.

♻️ **تصفير نقاط الجميع**
تصفير رصيد النقاط العام لجميع الموظفين فقط. هذا منفصل عن الجرد الأسبوعي.

🗑️ **تصفير نقاط موظف**
تصفير رصيد النقاط العام لموظف محدد فقط.

📊 **الجرد الأسبوعي**
نظام مستقل لمتابعة المطلوب الأسبوعي، الأكثر تفاعلًا وغير المتفاعلين، وتصفير الفواتير والساعات والمهام ونقاط الأسبوع إلى صفر مع حفظ أرشيف الأسبوع السابق.

👥 **تحديث لوحة الموظفين**
تحديث لوحة الموظفين الثابتة في روم قاعدة بيانات الموظفين. اللوحة تتحدث تلقائيًا أيضًا عند التوظيف والإجازة والفصل.

⚠️ **محاسبة موظف**
اختيار موظف ثم تحديد Strike 1 أو 2 أو 3 وكتابة السبب، وإرسال المحاسبة مع منشن الموظف في روم المحاسبات.

🛑 **فصل موظف**
اختيار موظف وكتابة رسالة الإدارة، ثم إزالة رتب الموظف والإجازة وتسجيل حالته كمفصول مع إبقاء سجله التاريخي.

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