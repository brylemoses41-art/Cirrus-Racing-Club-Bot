import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json


class Championship(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="championship", description="Show the current championship standings.")
    async def championship(self, interaction: discord.Interaction):
        data = load_json("championship.json", {"standings": {}})
        standings = data.get("standings", {})

        if not standings:
            await interaction.response.send_message(
                "🏆 No championship results have been recorded yet.", ephemeral=True
            )
            return

        ordered = sorted(
            standings.items(),
            key=lambda item: item[1].get("points", 0),
            reverse=True,
        )

        lines = []
        for position, (driver, entry) in enumerate(ordered, start=1):
            lines.append(f"**{position}.** {driver} — **{entry.get('points', 0)} pts**")

        embed = discord.Embed(
            title="🏆 Cirrus Racing Club Championship",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Championship(bot))
