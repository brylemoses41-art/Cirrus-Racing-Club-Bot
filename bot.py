import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import get_token
from storage import load_json, save_json
from utils import bot_embed


load_dotenv()
TOKEN = get_token()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

COGS = (
    "cogs.drivers",
    "cogs.races",
    "cogs.championship",
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
    embed.add_field(
        name="Automation",
        value="Automatic event channels, result posts, and race reminders.",
        inline=False,
    )
    embed.set_footer(text="Cirrus Racing Club • Official Command Desk")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="test_commands", description="Run a safe smoke test of the bot's commands and systems.")
@discord.app_commands.default_permissions(manage_guild=True)
async def test_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    expected_commands = {
        "help",
        "register",
        "drivers",
        "driver",
        "rename",
        "manage_driver",
        "create_race",
        "qualifying",
        "results",
        "report",
        "penalty",
        "lockdown",
        "open",
        "race",
        "standings",
        "championship",
    }

    registered = {command.name for command in bot.tree.get_commands()}
    missing = sorted(expected_commands - registered)
    extra = sorted(registered - expected_commands - {"test_commands"})

    checks = []

    if missing:
        checks.append(f"❌ Missing commands: {', '.join(missing)}")
    else:
        checks.append(f"✅ Commands loaded: {len(expected_commands)}/16")

    try:
        drivers_data = load_json("drivers.json", {"drivers": {}})
        races_data = load_json("races.json", {"races": []})
        if not isinstance(drivers_data.get("drivers"), dict):
            raise ValueError("drivers.json has an invalid structure")
        if not isinstance(races_data.get("races"), list):
            raise ValueError("races.json has an invalid structure")
        checks.append("✅ Data storage: readable")
    except Exception as error:
        checks.append(f"❌ Data storage: {error}")

    try:
        test_file = ".command_test.tmp"
        save_json(test_file, {"ok": True})
        test_data = load_json(test_file, {})
        from pathlib import Path
        test_path = Path(__file__).resolve().parent / "data" / test_file
        if test_path.exists():
            test_path.unlink()
        if test_data.get("ok") is not True:
            raise ValueError("write/read verification failed")
        checks.append("✅ Data storage: write test passed")
    except Exception as error:
        checks.append(f"❌ Data storage: write test failed — {error}")

    try:
        races_cog = bot.get_cog("Races")
        drivers_cog = bot.get_cog("Drivers")
        championship_cog = bot.get_cog("Championship")
        if not all((races_cog, drivers_cog, championship_cog)):
            raise ValueError("one or more cogs are not loaded")
        checks.append("✅ Cogs: drivers, races, championship loaded")
    except Exception as error:
        checks.append(f"❌ Cogs: {error}")

    if extra:
        checks.append(f"ℹ️ Additional commands detected: {', '.join(extra)}")

    embed = bot_embed(
        "Command Test",
        "A safe smoke test has been completed. Commands that change races, penalties, channels, or driver records are not executed automatically.",
    )
    embed.add_field(name="System Check", value="\n".join(checks), inline=False)
    embed.add_field(
        name="Registered Commands",
        value="\n".join(f"• `/{name}`" for name in sorted(registered)),
        inline=False,
    )
    embed.set_footer(text="Cirrus Racing Club • Race Control Diagnostics")
    await interaction.followup.send(embed=embed, ephemeral=True)


bot.run(TOKEN)
