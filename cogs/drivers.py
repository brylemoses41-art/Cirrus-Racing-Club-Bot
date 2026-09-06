import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json, save_json


class Drivers(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rename", description="Rename a registered driver.")
    @app_commands.describe(driver="Driver to rename", new_name="New driver name")
    async def rename(self, interaction: discord.Interaction, driver: str, new_name: str):
        data = load_json("drivers.json", {"drivers": {}})
        drivers = data.setdefault("drivers", {})

        if driver not in drivers:
            drivers[driver] = {"name": new_name, "points": 0}
        else:
            drivers[driver]["name"] = new_name

        save_json("drivers.json", data)
        await interaction.response.send_message(
            f"✅ Driver **{driver}** is now **{new_name}**.", ephemeral=True
        )

    @app_commands.command(name="manage_driver", description="View a driver's stored information.")
    @app_commands.describe(driver="Driver to view")
    async def manage_driver(self, interaction: discord.Interaction, driver: str):
        data = load_json("drivers.json", {"drivers": {}})
        entry = data.get("drivers", {}).get(driver)

        if not entry:
            await interaction.response.send_message(
                f"❌ Driver **{driver}** was not found.", ephemeral=True
            )
            return

        embed = discord.Embed(title="🏎️ Driver", color=discord.Color.blue())
        embed.add_field(name="Name", value=entry.get("name", driver), inline=False)
        embed.add_field(name="Points", value=str(entry.get("points", 0)), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drivers(bot))
