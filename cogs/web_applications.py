from datetime import datetime,timezone
import discord
from discord.ext import commands
from database.db import get_setting,get_web_application,get_latest_web_application_for_user,update_web_application_status
async def adm(i):
 if i.user.guild_permissions.administrator:return True
 r=await get_setting(i.guild.id,"admin_role")
 if r and any(x.id==int(r) for x in i.user.roles):return True
 await i.response.send_message("هذا الخيار مخصص للإدارة فقط.",ephemeral=True);return False
class WebApplicationReviewView(discord.ui.View):
 def __init__(self,app_id):
  super().__init__(timeout=None);self.app_id=app_id
  a=discord.ui.Button(label="قبول مبدئي",emoji="✅",style=discord.ButtonStyle.success,custom_id=f"web:accept:{app_id}");r=discord.ui.Button(label="رفض",emoji="❌",style=discord.ButtonStyle.danger,custom_id=f"web:reject:{app_id}");a.callback=self.accept;r.callback=self.reject;self.add_item(a);self.add_item(r)
 async def accept(self,i):
  if not await adm(i):return
  row=await get_web_application(self.app_id)
  if not row or row[10]!="pending":return await i.response.send_message("تمت مراجعة الطلب مسبقًا.",ephemeral=True)
  await update_web_application_status(self.app_id,"accepted",datetime.now(timezone.utc).isoformat(),i.user.id);e=i.message.embeds[0];e.add_field(name="الحالة",value=f"🟢 قبول مبدئي بواسطة {i.user.mention}",inline=False);await i.message.edit(embed=e,view=None);await i.response.send_message("تم القبول المبدئي.",ephemeral=True)
 async def reject(self,i):
  if not await adm(i):return
  row=await get_web_application(self.app_id)
  if not row or row[10]!="pending":return await i.response.send_message("تمت مراجعة الطلب مسبقًا.",ephemeral=True)
  await update_web_application_status(self.app_id,"rejected",datetime.now(timezone.utc).isoformat(),i.user.id);e=i.message.embeds[0];e.add_field(name="الحالة",value=f"🔴 مرفوض بواسطة {i.user.mention}",inline=False);await i.message.edit(embed=e,view=None);await i.response.send_message("تم الرفض ويمكنه إعادة التقديم من الموقع.",ephemeral=True)
class TrackButton(discord.ui.Button):
 def __init__(self):super().__init__(label="متابعة طلبي",emoji="📋",style=discord.ButtonStyle.primary,custom_id="web:track")
 async def callback(self,i):
  row=await get_latest_web_application_for_user(i.guild.id,i.user.id)
  if not row:return await i.response.send_message("ما حصلت طلب مرتبط بحسابك. تأكد من Discord ID في الموقع.",ephemeral=True)
  if row[10]=="pending":return await i.response.send_message("🟡 **طلبك قيد المراجعة**",ephemeral=True)
  if row[10]=="rejected":return await i.response.send_message("🔴 **تم رفض طلبك** — يمكنك إعادة التقديم من الموقع.",ephemeral=True)
  from cogs.panels import HRPanelView
  return await i.response.send_message(embed=discord.Embed(title="✅ تم قبولك مبدئيًا",description="اضغط الزر بالأسفل لاستكمال بيانات الموارد البشرية."),view=HRPanelView(),ephemeral=True)
class ApplicationFollowupView(discord.ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(TrackButton())
class WebApplications(commands.Cog):
 def __init__(self,bot):self.bot=bot;bot.add_view(ApplicationFollowupView())
async def setup(bot):await bot.add_cog(WebApplications(bot))
