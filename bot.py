import inspect
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import get_token
from constants import points_for_position
from dashboard_app import start_dashboard
from dashboard import set_bot
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
    "cogs.calendar",
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
    set_bot(bot)
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    print(f"Slash command error: {error}")
    message = "Something went wrong while running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="help", description="Show Cirrus Racing Club commands.")
async def help_command(interaction: discord.Interaction):
    embed = bot_embed("Cirrus Racing Club", "The official command desk for drivers and Race Control.")
    embed.add_field(name="Driver Registry", value="`/register`  `/drivers`  `/driver`", inline=False)
    embed.add_field(name="Race Administration", value="`/create_race`  `/race`  `/qualifying`  `/results`  `/calendar`", inline=False)
    embed.add_field(name="Championship", value="`/standings`  `/championship`", inline=False)
    embed.add_field(name="Race Control", value="`/report`  `/penalty`  `/lockdown`  `/open`", inline=False)
    embed.add_field(name="Automation", value="Automatic event channels, result posts, and race reminders.", inline=False)
    embed.set_footer(text="Cirrus Racing Club • Official Command Desk")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="test_commands", description="Run a full safe diagnostic of every bot command.")
@discord.app_commands.default_permissions(manage_guild=True)
async def test_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    expected_commands = {"help":"Driver and Race Control command desk","register":"Driver registration","drivers":"Driver registry listing","driver":"Driver profile","rename":"Driver record rename","manage_driver":"Driver record inspection","create_race":"Race creation","qualifying":"Qualifying grid","results":"Race results","report":"Incident reports","penalty":"Championship penalties","lockdown":"Event channel lockdown","open":"Event channel reopening","race":"Race record display","calendar":"Official season calendar","standings":"Championship standings","championship":"Championship standings alias"}
    checks=[]; registered={command.name:command for command in bot.tree.get_commands()}
    for name,label in expected_commands.items():
        command=registered.get(name)
        if command is None: checks.append(("❌",name,f"{label} — command missing")); continue
        if not callable(command.callback): checks.append(("❌",name,f"{label} — callback missing")); continue
        checks.append(("✅",name,label))
    async_failures=[name for name in expected_commands if registered.get(name) and not inspect.iscoroutinefunction(registered[name].callback)]
    checks.append(("❌" if async_failures else "✅","callbacks",f"Not async: {', '.join(sorted(async_failures))}" if async_failures else "All command callbacks are asynchronous"))
    parameter_failures=[]
    for name in expected_commands:
        command=registered.get(name)
        if command and "interaction" not in inspect.signature(command.callback).parameters: parameter_failures.append(f"/{name}: interaction")
    checks.append(("❌" if parameter_failures else "✅","parameters","; ".join(parameter_failures) if parameter_failures else "All commands accept a Discord interaction"))
    try:
        drivers_data=load_json("drivers.json",{"drivers":{}}); races_data=load_json("races.json",{"races":[]}); championship_data=load_json("championship.json",{"standings":{}})
        if not isinstance(drivers_data.get("drivers"),dict) or not isinstance(races_data.get("races"),list) or not isinstance(championship_data,dict): raise ValueError("Invalid storage structure")
        checks.append(("✅","storage","Driver, race, and championship data are readable"))
    except Exception as error: checks.append(("❌","storage",str(error)))
    test_file=".command_test.tmp"; test_path=Path(__file__).resolve().parent/"data"/test_file
    try:
        save_json(test_file,{"ok":True,"test":"crc"}); test_data=load_json(test_file,{})
        if test_data.get("ok") is not True or test_data.get("test")!="crc": raise ValueError("write/read verification failed")
        checks.append(("✅","storage","Temporary write/read test passed"))
    except Exception as error: checks.append(("❌","storage",f"Write test failed — {error}"))
    finally:
        if test_path.exists():
            try:test_path.unlink()
            except OSError:pass
    missing_cogs=[name for name in ("Drivers","Races","Championship","Calendar") if bot.get_cog(name) is None]
    checks.append(("❌" if missing_cogs else "✅","cogs",f"Missing: {', '.join(missing_cogs)}" if missing_cogs else "Drivers, Races, Championship, and Calendar loaded"))
    try:
        races_cog=bot.get_cog("Races"); sample_races=[{"id":"R001","name":"Diagnostic Race","status":"open"},{"id":"R002","name":"Second Race","status":"locked"}]
        found=races_cog.find_race(sample_races,"r001") if races_cog else None; missing=races_cog.find_race(sample_races,"R999") if races_cog else None
        table=races_cog.qualifying_table([{"position":1,"driver":"Diagnostic Driver","lap_time":"1:45.000"},{"position":2,"driver":"Second Driver","lap_time":"1:46.000"}]) if races_cog else ""
        if not found or missing is not None or "P1" not in table or "Diagnostic Driver" not in table: raise ValueError("race logic failed")
        checks.append(("✅","race logic","Race lookup and qualifying table passed"))
    except Exception as error: checks.append(("❌","race logic",str(error)))
    try:
        expected_points={1:5,2:4,3:3,4:2,5:1,20:1,21:0}; failures=[f"P{p}={points_for_position(p)}" for p,e in expected_points.items() if points_for_position(p)!=e]
        if failures: raise ValueError("; ".join(failures))
        checks.append(("✅","points","Championship scoring logic passed"))
    except Exception as error: checks.append(("❌","points",str(error)))
    passed=sum(s=="✅" for s,_,_ in checks); failed=sum(s=="❌" for s,_,_ in checks)
    embed=bot_embed("CRC Bot Diagnostics","Every registered command has been checked for wiring, callbacks, parameters, storage dependencies, and safe underlying logic. No real race, driver, penalty, or channel changes were made.")
    embed.add_field(name="Result",value=f"**{passed} passed** · **{failed} failed**",inline=False)
    embed.add_field(name="Diagnostic Report",value="\n".join(f"{s} **{n}** — {d}" for s,n,d in checks),inline=False)
    embed.set_footer(text="Cirrus Racing Club • Race Control Diagnostics")
    await interaction.followup.send(embed=embed,ephemeral=True)


start_dashboard()
bot.run(TOKEN)
