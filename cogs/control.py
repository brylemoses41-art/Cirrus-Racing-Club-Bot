import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json, save_json
from utils import bot_embed


class RaceControl(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="report", description="Submit an incident report to Race Control.")
    @app_commands.describe(race_id="Race record ID", driver="Driver involved", incident="What happened")
    async def report(self, interaction: discord.Interaction, race_id: str, driver: str, incident: str):
        data = load_json("races.json", {"races": []})
        race = next((r for r in data.get("races", []) if r.get("id") == race_id.upper()), None)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        race.setdefault("reports", []).append({
            "driver": driver.strip(), "submitted_by": interaction.user.id,
            "incident": incident.strip(), "submitted_at": discord.utils.utcnow().isoformat(),
        })
        save_json("races.json", data)
        await interaction.response.send_message("Your report has been submitted to Race Control for review.", ephemeral=True)

    @app_commands.command(name="penalty", description="Record a Race Control penalty.")
    @app_commands.describe(race_id="Race record ID", driver="Driver name", reason="Reason for penalty", points="Championship points to deduct")
    @app_commands.default_permissions(manage_guild=True)
    async def penalty(self, interaction: discord.Interaction, race_id: str, driver: str, reason: str, points: int):
        if points < 0:
            await interaction.response.send_message("Penalty points must be zero or greater.", ephemeral=True)
            return
        data = load_json("races.json", {"races": []})
        race = next((r for r in data.get("races", []) if r.get("id") == race_id.upper()), None)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        race.setdefault("penalties", []).append({
            "driver": driver.strip(), "reason": reason.strip(), "points": points,
            "issued_by": interaction.user.id, "issued_at": discord.utils.utcnow().isoformat(),
        })
        save_json("races.json", data)
        embed = bot_embed("Race Control", "The following ruling has been entered into the official record.")
        embed.add_field(name="Driver", value=driver.strip(), inline=True)
        embed.add_field(name="Deduction", value=f"{points} pts", inline=True)
        embed.add_field(name="Reason", value=reason.strip(), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lockdown", description="Close the current channel to regular members.")
    @app_commands.default_permissions(manage_channels=True)
    async def lockdown(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Race Control can only lock text channels.", ephemeral=True)
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Cirrus Racing Club Race Control lockdown")
        await interaction.response.send_message("This channel has been placed under Race Control lockdown.")

    @app_commands.command(name="open", description="Reopen the current channel to regular members.")
    @app_commands.default_permissions(manage_channels=True)
    async def open_channel(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Race Control can only reopen text channels.", ephemeral=True)
            return
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Cirrus Racing Club Race Control reopening")
        await interaction.response.send_message("The channel has been reopened. Race Control is satisfied.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RaceControl(bot))
