import discord
from discord import app_commands
from discord.ext import commands

from constants import points_for_position
from storage import load_json
from utils import bot_embed


class Championship(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def calculate(self):
        races = load_json("races.json", {"races": []}).get("races", [])
        totals = {}

        for race in races:
            for result in race.get("results", []):
                driver = result.get("driver", "").strip()
                if not driver:
                    continue
                position = int(result.get("position", 0))
                totals.setdefault(driver, 0)
                totals[driver] += points_for_position(position)

            for penalty in race.get("penalties", []):
                driver = penalty.get("driver", "").strip()
                if not driver:
                    continue
                totals.setdefault(driver, 0)
                totals[driver] -= int(penalty.get("points", 0))

        return sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))

    @app_commands.command(name="standings", description="Show the current championship standings.")
    async def standings(self, interaction: discord.Interaction):
        ordered = self.calculate()
        if not ordered:
            await interaction.response.send_message("The championship table is presently empty.", ephemeral=True)
            return

        lines = [f"**{i}.** {driver} — **{points} pts**" for i, (driver, points) in enumerate(ordered, 1)]
        embed = bot_embed("Championship Office", "The championship table has been brought up to date.")
        embed.add_field(name="Standings", value="\n".join(lines), inline=False)
        embed.set_footer(text="Cirrus Racing Club • Official Championship")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="championship", description="Alias for the championship standings.")
    async def championship(self, interaction: discord.Interaction):
        ordered = self.calculate()
        if not ordered:
            await interaction.response.send_message("The championship table is presently empty.", ephemeral=True)
            return
        lines = [f"**{i}.** {driver} — **{points} pts**" for i, (driver, points) in enumerate(ordered, 1)]
        embed = bot_embed("Championship Office", "The championship table has been brought up to date.")
        embed.add_field(name="Standings", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Championship(bot))
