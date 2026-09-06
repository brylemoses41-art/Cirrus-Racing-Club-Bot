import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json, save_json
from utils import bot_embed, set_crc_footer


class Drivers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="register", description="Register yourself as a Cirrus Racing Club driver.")
    @app_commands.describe(name="Your racing name")
    async def register(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        if not name:
            await interaction.response.send_message("A driver needs a racing name.", ephemeral=True)
            return
        data = load_json("drivers.json", {"drivers": {}})
        drivers = data.setdefault("drivers", {})
        key = str(interaction.user.id)
        if key in drivers:
            await interaction.response.send_message("Your entry is already on the Driver Registry.", ephemeral=True)
            return
        drivers[key] = {
            "name": name,
            "discord_id": interaction.user.id,
            "registered_at": discord.utils.utcnow().isoformat(),
        }
        save_json("drivers.json", data)
        embed = bot_embed("Driver Registry", "Your registration has been entered into the official record.")
        embed.add_field(name="Driver", value=f"**{name}**", inline=False)
        set_crc_footer(embed, "Official Driver Registry")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="drivers", description="View the registered Cirrus Racing Club drivers.")
    async def drivers(self, interaction: discord.Interaction):
        entries = list(load_json("drivers.json", {"drivers": {}}).get("drivers", {}).values())
        if not entries:
            await interaction.response.send_message("The Driver Registry is presently empty.", ephemeral=True)
            return
        entries.sort(key=lambda item: item.get("name", "").lower())
        embed = bot_embed("Driver Registry", "Registered drivers of Cirrus Racing Club.")
        embed.description = "\n".join(f"`{i:02d}`  **{entry.get('name', 'Unnamed')}**" for i, entry in enumerate(entries, 1))
        set_crc_footer(embed, f"{len(entries)} registered driver(s)")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="driver", description="View a driver's profile and statistics.")
    @app_commands.describe(driver="Driver name, or leave blank to view yourself")
    async def driver(self, interaction: discord.Interaction, driver: str | None = None):
        driver_data = load_json("drivers.json", {"drivers": {}}).get("drivers", {})
        entry = driver_data.get(str(interaction.user.id)) if driver is None else next(
            (v for v in driver_data.values() if v.get("name", "").lower() == driver.strip().lower()), None
        )
        if not entry:
            await interaction.response.send_message("That driver is not on the registry.", ephemeral=True)
            return

        name = entry.get("name", "Unnamed")
        races = load_json("races.json", {"races": []}).get("races", [])
        results = [r for race in races for r in race.get("results", []) if r.get("driver", "").lower() == name.lower()]
        starts = len(results)
        wins = sum(1 for r in results if r.get("position") == 1)
        podiums = sum(1 for r in results if int(r.get("position", 999)) <= 3)
        points = sum(int(r.get("points", 0)) for r in results)
        points -= sum(int(p.get("points", 0)) for race in races for p in race.get("penalties", []) if p.get("driver", "").lower() == name.lower())

        embed = bot_embed("Driver Record", f"**{name}**\nOfficial competition statistics")
        embed.add_field(name="STARTS", value=f"`{starts}`", inline=True)
        embed.add_field(name="WINS", value=f"`{wins}`", inline=True)
        embed.add_field(name="PODIUMS", value=f"`{podiums}`", inline=True)
        embed.add_field(name="CHAMPIONSHIP POINTS", value=f"**{points}**", inline=False)
        set_crc_footer(embed, "Driver Records")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rename", description="Rename a registered driver.")
    @app_commands.describe(driver="Driver name", new_name="New racing name")
    @app_commands.default_permissions(manage_guild=True)
    async def rename(self, interaction: discord.Interaction, driver: str, new_name: str):
        data = load_json("drivers.json", {"drivers": {}})
        entry = next((v for v in data.get("drivers", {}).values() if v.get("name", "").lower() == driver.lower()), None)
        if not entry:
            await interaction.response.send_message("That driver is not on the registry.", ephemeral=True)
            return
        entry["name"] = new_name.strip()
        save_json("drivers.json", data)
        await interaction.response.send_message("The Driver Registry has been amended accordingly.", ephemeral=True)

    @app_commands.command(name="manage_driver", description="Inspect a driver's stored record.")
    @app_commands.describe(driver="Driver name")
    @app_commands.default_permissions(manage_guild=True)
    async def manage_driver(self, interaction: discord.Interaction, driver: str):
        data = load_json("drivers.json", {"drivers": {}})
        entry = next((v for v in data.get("drivers", {}).values() if v.get("name", "").lower() == driver.lower()), None)
        if not entry:
            await interaction.response.send_message("That driver is not on the registry.", ephemeral=True)
            return
        embed = bot_embed("Driver Record", "Internal Race Control reference.")
        embed.add_field(name="Driver", value=f"**{entry.get('name')}**", inline=False)
        embed.add_field(name="Discord ID", value=f"`{entry.get('discord_id')}`", inline=False)
        embed.add_field(name="Registered", value=entry.get("registered_at", "—"), inline=False)
        set_crc_footer(embed, "Race Control")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drivers(bot))
