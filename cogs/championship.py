import discord
from discord import app_commands
from discord.ext import commands

from constants import points_for_position
from storage import load_json
from utils import bot_embed, set_crc_footer


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

    def build_embed(self):
        ordered = self.calculate()
        if not ordered:
            return None

        lines = []
        for i, (driver, points) in enumerate(ordered, 1):
            marker = "▸" if i == 1 else "·"
            lines.append(f"{marker} **P{i:02d}**  {driver}  —  **{points} pts**")

        embed = bot_embed(
            "Championship Standings",
            "The current order of the championship, as entered in the official race records.",
        )
        embed.add_field(name="CURRENT ORDER", value="\n".join(lines), inline=False)
        set_crc_footer(embed, "Official Championship")
        return embed

    @app_commands.command(name="standings", description="Show the current championship standings.")
    async def standings(self, interaction: discord.Interaction):
        embed = self.build_embed()
        if embed is None:
            await interaction.response.send_message("The championship table is presently empty.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="championship", description="Alias for the championship standings.")
    async def championship(self, interaction: discord.Interaction):
        embed = self.build_embed()
        if embed is None:
            await interaction.response.send_message("The championship table is presently empty.", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Championship(bot))
