import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json, save_json


class Races(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="race", description="Create a basic race record.")
    @app_commands.describe(name="Race name", track="Track name")
    async def race(self, interaction: discord.Interaction, name: str, track: str):
        data = load_json("races.json", {"races": []})
        races = data.setdefault("races", [])

        races.append({
            "name": name,
            "track": track,
            "created_by": interaction.user.id,
        })
        save_json("races.json", data)

        await interaction.response.send_message(
            f"🏁 Race **{name}** created for **{track}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Races(bot))
