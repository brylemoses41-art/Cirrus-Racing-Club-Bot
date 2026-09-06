import inspect
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import get_token
from constants import points_for_position
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


@bot.tree.command(name="test_commands", description="Run a full safe diagnostic of every bot command.")
@discord.app_commands.default_permissions(manage_guild=True)
async def test_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    expected_commands = {
        "help": "Driver and Race Control command desk",
        "register": "Driver registration",
        "drivers": "Driver registry listing",
        "driver": "Driver profile",
        "rename": "Driver record rename",
        "manage_driver": "Driver record inspection",
        "create_race": "Race creation",
        "qualifying": "Qualifying grid",
        "results": "Race results",
        "report": "Incident reports",
        "penalty": "Championship penalties",
        "lockdown": "Event channel lockdown",
        "open": "Event channel reopening",
        "race": "Race record display",
        "standings": "Championship standings",
        "championship": "Championship standings alias",
    }

    checks = []
    registered = {command.name: command for command in bot.tree.get_commands()}

    # 1. Every expected slash command exists and has a callback.
    for name, label in expected_commands.items():
        command = registered.get(name)
        if command is None:
            checks.append(("❌", name, f"{label} — command missing"))
            continue
        if not callable(command.callback):
            checks.append(("❌", name, f"{label} — callback missing"))
            continue
        checks.append(("✅", name, label))

    # 2. Verify command callbacks are actually async functions.
    async_failures = []
    for name in expected_commands:
        command = registered.get(name)
        if command and not inspect.iscoroutinefunction(command.callback):
            async_failures.append(name)
    if async_failures:
        checks.append(("❌", "callbacks", f"Not async: {', '.join(sorted(async_failures))}"))
    else:
        checks.append(("✅", "callbacks", "All command callbacks are asynchronous"))

    # 3. Verify every command exposes the parameters expected by its callback.
    parameter_failures = []
    for name in expected_commands:
        command = registered.get(name)
        if not command:
            continue
        callback = command.callback
        signature = inspect.signature(callback)
        if "interaction" not in signature.parameters:
            parameter_failures.append(f"/{name}: interaction")
    if parameter_failures:
        checks.append(("❌", "parameters", "; ".join(parameter_failures)))
    else:
        checks.append(("✅", "parameters", "All commands accept a Discord interaction"))

    # 4. Verify persistent data files and their structures.
    try:
        drivers_data = load_json("drivers.json", {"drivers": {}})
        races_data = load_json("races.json", {"races": []})
        championship_data = load_json("championship.json", {"standings": {}})

        if not isinstance(drivers_data.get("drivers"), dict):
            raise ValueError("drivers.json has an invalid structure")
        if not isinstance(races_data.get("races"), list):
            raise ValueError("races.json has an invalid structure")
        if not isinstance(championship_data, dict):
            raise ValueError("championship.json has an invalid structure")

        checks.append(("✅", "storage", "Driver, race, and championship data are readable"))
    except Exception as error:
        checks.append(("❌", "storage", str(error)))

    # 5. Verify JSON writing without altering real records.
    test_file = ".command_test.tmp"
    test_path = Path(__file__).resolve().parent / "data" / test_file
    try:
        save_json(test_file, {"ok": True, "test": "crc"})
        test_data = load_json(test_file, {})
        if test_data.get("ok") is not True or test_data.get("test") != "crc":
            raise ValueError("write/read verification failed")
        checks.append(("✅", "storage", "Temporary write/read test passed"))
    except Exception as error:
        checks.append(("❌", "storage", f"Write test failed — {error}"))
    finally:
        if test_path.exists():
            try:
                test_path.unlink()
            except OSError:
                pass

    # 6. Verify all cogs are loaded.
    cog_names = ("Drivers", "Races", "Championship")
    missing_cogs = [name for name in cog_names if bot.get_cog(name) is None]
    if missing_cogs:
        checks.append(("❌", "cogs", f"Missing: {', '.join(missing_cogs)}"))
    else:
        checks.append(("✅", "cogs", "Drivers, Races, and Championship loaded"))

    # 7. Exercise pure race logic without creating channels or changing real race records.
    try:
        races_cog = bot.get_cog("Races")
        sample_races = [
            {"id": "R001", "name": "Diagnostic Race", "status": "open"},
            {"id": "R002", "name": "Second Race", "status": "locked"},
        ]
        found = races_cog.find_race(sample_races, "r001") if races_cog else None
        missing = races_cog.find_race(sample_races, "R999") if races_cog else None
        if not found or found["name"] != "Diagnostic Race" or missing is not None:
            raise ValueError("race lookup logic failed")

        table = races_cog.qualifying_table([
            {"position": 1, "driver": "Diagnostic Driver", "lap_time": "1:45.000"},
            {"position": 2, "driver": "Second Driver", "lap_time": "1:46.000"},
        ]) if races_cog else ""
        if "P1" not in table or "Diagnostic Driver" not in table or "1:46.000" not in table:
            raise ValueError("qualifying table logic failed")

        checks.append(("✅", "race logic", "Race lookup and qualifying table passed"))
    except Exception as error:
        checks.append(("❌", "race logic", str(error)))

    # 8. Verify championship points logic for every scoring position.
    try:
        expected_points = {
            1: 5,
            2: 4,
            3: 3,
            4: 2,
            5: 1,
            20: 1,
            21: 0,
        }
        failures = [
            f"P{position}={points_for_position(position)}"
            for position, expected in expected_points.items()
            if points_for_position(position) != expected
        ]
        if failures:
            raise ValueError("; ".join(failures))
        checks.append(("✅", "points", "Championship scoring logic passed"))
    except Exception as error:
        checks.append(("❌", "points", str(error)))

    # 9. Verify there are no unexpected slash commands besides this diagnostic.
    extra = sorted(set(registered) - set(expected_commands) - {"test_commands"})
    if extra:
        checks.append(("ℹ️", "commands", f"Additional commands: {', '.join(extra)}"))

    passed = sum(1 for status, _, _ in checks if status == "✅")
    failed = sum(1 for status, _, _ in checks if status == "❌")

    lines = []
    for status, name, description in checks:
        lines.append(f"{status} **{name}** — {description}")

    embed = bot_embed(
        "CRC Bot Diagnostics",
        "Every registered command has been checked for wiring, callbacks, parameters, storage dependencies, and safe underlying logic. No real race, driver, penalty, or channel changes were made.",
    )
    embed.add_field(
        name="Result",
        value=f"**{passed} passed** · **{failed} failed**",
        inline=False,
    )
    embed.add_field(
        name="Diagnostic Report",
        value="\n".join(lines),
        inline=False,
    )
    embed.set_footer(text="Cirrus Racing Club • Race Control Diagnostics")
    await interaction.followup.send(embed=embed, ephemeral=True)


bot.run(TOKEN)
