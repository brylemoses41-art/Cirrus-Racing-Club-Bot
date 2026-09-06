import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json
from utils import bot_embed


class Standings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def calculate():
        races = load_json("races.json", {"races": []}).get("races", [])
        totals = {}
        for race in races:
            for result in race.get("results", []):
                driver = result.get("driver", "").strip()
                if not driver:
                    continue
                points = int(result.get("points", 0))
                totals[driver] = totals.get(driver, 0) + points
            for penalty in race.get("penalties", []):
                driver = penalty.get("driver", "").strip()
                if driver:
                    totals[driver] = totals.get(driver, 0) - int(penalty.get("points", 0))
        return totals

    async def send_standings(self, interaction: discord.Interaction):
        totals = self.calculate()
        if not totals:
            await interaction.response.send_message("The championship table is presently empty.", ephemeral=True)
            return
        ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))
        embed = bot_embed("Championship Table", "The championship record has been brought up to date.")
        embed.description = "\n".join(f"**{position}.** {driver} — **{points} pts**" for position, (driver, points) in enumerate(ordered, 1))
        embed.set_footer(text="Cirrus Racing Club • Official Championship")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="standings", description="Show the current championship standings.")
    async def standings(self, interaction: discord.Interaction):
        await self.send_standings(interaction)

    @app_commands.command(name="championship", description="View the current championship table.")
    async def championship(self, interaction: discord.Interaction):
        await self.send_standings(interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(Standings(bot))
