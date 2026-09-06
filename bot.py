import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import get_token
from utils import bot_embed


load_dotenv()
TOKEN = get_token()

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as error:
        print(f"Failed to sync slash commands: {error}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    print(f"Slash command error: {error}")

    message = "❌ Something went wrong while running that command."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="help", description="Show Cirrus Racing Club bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = bot_embed(
        "🏁 Cirrus Racing Club",
        "Bot commands will be listed here as we build them.",
    )

    embed.add_field(
        name="🛠️ Status",
        value="Bot foundation is online.",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
