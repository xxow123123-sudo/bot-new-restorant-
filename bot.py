import asyncio
import discord
from discord.ext import commands
from config import TOKEN, GUILD_ID, PORT
from database.db import init_db
from web_app import start_web_server

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


class RestaurantBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        await init_db()
        self.web_runner = await start_web_server(self, PORT)
        print(f"✅ Website running on port {PORT}")

        for ext in (
            "cogs.settings",
            "cogs.panels",
            "cogs.bot_profile",
            "cogs.web_applications",
        ):
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
    asyncio.run(main())