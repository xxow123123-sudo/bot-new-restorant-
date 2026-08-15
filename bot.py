import asyncio
import discord
from discord.ext import commands
from config import TOKEN, GUILD_ID
from database.db import init_db

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True

class RestaurantBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        await init_db()
<<<<<<< HEAD
        for ext in ("cogs.settings", "cogs.general", "cogs.panels", "cogs.bot_profile"):
=======
        for ext in ("cogs.settings", "cogs.general", "cogs.panels"):
>>>>>>> 849f5d4aa636db73db2342fffa2452e76458c205
            await self.load_extension(ext)
            print(f"✅ Loaded: {ext}")

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"✅ Synced {len(synced)} guild commands")
        else:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} global commands")

bot = RestaurantBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

async def main():
    if not TOKEN:
        raise RuntimeError("حط توكن البوت داخل ملف .env أولاً")
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
<<<<<<< HEAD
    asyncio.run(main())
=======
    asyncio.run(main())
>>>>>>> 849f5d4aa636db73db2342fffa2452e76458c205
