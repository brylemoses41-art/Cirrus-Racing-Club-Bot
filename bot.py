import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import get_token
from utils import bot_embed


load_dotenv()
TOKEN = get_token()

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = (
    "cogs.drivers",
    "cogs.races",
    "cogs.standings",
    "cogs.control",
)


@bot.event
async def setup_hook():
    for extension in COGS:
        try:
            await bot.load_extension(extension)
            print(f"Loaded {extension}")
        except Exception as error:
            print(f"Failed to load {extension}: {error}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as error:
        print(f"Failed to sync slash commands: {error}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    print(f"Slash command error: {error}")
    message = "Something went wrong while running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="help", description="Show Cirrus Racing Club commands.")
async def help_command(interaction: discord.Interaction):
    embed = bot_embed(
        "Cirrus Racing Club",
        "The official command desk for drivers and Race Control.",
    )
    embed.add_field(
        name="Driver Registry",
        value="`/register`  `/drivers`  `/driver`",
        inline=False,
    )
    embed.add_field(
        name="Race Administration",
        value="`/create_race`  `/race`  `/qualifying`  `/results`",
        inline=False,
    )
    embed.add_field(
        name="Championship",
        value="`/standings`  `/championship`",
        inline=False,
    )
    embed.add_field(
        name="Race Control",
        value="`/report`  `/penalty`  `/lockdown`  `/open`",
        inline=False,
    )
    embed.set_footer(text="Cirrus Racing Club • Official Command Desk")
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
