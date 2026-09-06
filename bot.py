import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in the environment.")


# =========================================================
# BOT SETUP
# =========================================================
intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


# =========================================================
# STARTUP
# =========================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as error:
        print(f"Failed to sync slash commands: {error}")


# =========================================================
# BASIC HELP COMMAND
# =========================================================
@bot.tree.command(name="help", description="Show Cirrus Racing Club bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏁 Cirrus Racing Club",
        description="Bot commands will be listed here as we build them.",
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="🛠️ Status",
        value="Bot foundation is online.",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# RUN
# =========================================================
bot.run(TOKEN)
