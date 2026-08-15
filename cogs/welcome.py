import discord
from discord.ext import commands

WELCOME_CHANNEL_ID = 1538210251885510746
AUTO_ROLE_ID = 1538215517092052992


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # إعطاء الرتبة التلقائية
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Auto role on join")
            except discord.Forbidden:
                print("❌ البوت لا يملك صلاحية إعطاء الرتبة التلقائية.")
            except discord.HTTPException as e:
                print(f"❌ تعذر إعطاء الرتبة: {e}")

        # إرسال رسالة الترحيب
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            print("❌ روم الترحيب غير موجود أو ليس Text Channel.")
            return

        member_count = member.guild.member_count or len(member.guild.members)

        message = (
            f"╭・𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐭𝐨 𝐨𝐮𝐫 𝐜𝐨𝐦𝐦𝐮𝐧𝐢𝐭𝐲  {member.mention}  **{member_count}**\n"
            f"╰・𝐁𝐞𝐚𝐧 𝐌𝐚𝐜𝐡𝐢𝐧𝐞"
        )

        try:
            await channel.send(message)
        except discord.Forbidden:
            print("❌ البوت لا يملك صلاحية إرسال الرسائل في روم الترحيب.")
        except discord.HTTPException as e:
            print(f"❌ تعذر إرسال رسالة الترحيب: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
