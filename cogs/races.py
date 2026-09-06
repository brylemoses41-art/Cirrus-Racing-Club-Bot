import discord
from discord import app_commands
from discord.ext import commands

from storage import load_json, save_json
from utils import bot_embed


class Races(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def find_race(races, race_id):
        return next((race for race in races if race.get("id") == race_id.upper()), None)

    @app_commands.command(name="create_race", description="Create an official race record.")
    @app_commands.describe(name="Race name", track="Track", laps="Number of laps", date="Date or event date")
    @app_commands.default_permissions(manage_guild=True)
    async def create_race(self, interaction: discord.Interaction, name: str, track: str, laps: int, date: str):
        if laps < 1:
            await interaction.response.send_message("A race must contain at least one lap.", ephemeral=True)
            return
        data = load_json("races.json", {"races": []})
        races = data.setdefault("races", [])
        race_id = f"R{len(races) + 1:03d}"
        race = {"id": race_id, "name": name.strip(), "track": track.strip(), "laps": laps, "date": date.strip(),
                "status": "open", "created_by": interaction.user.id, "created_at": discord.utils.utcnow().isoformat(),
                "qualifying": [], "results": [], "penalties": [], "reports": []}
        races.append(race)
        save_json("races.json", data)
        embed = bot_embed("Race Control", "A new event has been entered into the official calendar.")
        embed.add_field(name="Race", value=f"**{race['name']}** (`{race_id}`)", inline=False)
        embed.add_field(name="Circuit", value=race["track"], inline=True)
        embed.add_field(name="Distance", value=f"{laps} lap(s)", inline=True)
        embed.add_field(name="Date", value=race["date"], inline=True)
        embed.set_footer(text="Cirrus Racing Club • Race Control")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="qualifying", description="Record a driver's qualifying result.")
    @app_commands.describe(race_id="Race record ID", driver="Driver name", lap_time="Qualifying lap time", position="Grid position")
    @app_commands.default_permissions(manage_guild=True)
    async def qualifying(self, interaction: discord.Interaction, race_id: str, driver: str, lap_time: str, position: int):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        if position < 1:
            await interaction.response.send_message("Grid position must be 1 or greater.", ephemeral=True)
            return
        race.setdefault("qualifying", []).append({"driver": driver.strip(), "lap_time": lap_time.strip(), "position": position})
        race["qualifying"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        await interaction.response.send_message(f"Qualifying has been recorded: **P{position} — {driver} — {lap_time}**.", ephemeral=True)

    @app_commands.command(name="results", description="Record a driver's official race result.")
    @app_commands.describe(race_id="Race record ID", driver="Driver name", position="Finishing position")
    @app_commands.default_permissions(manage_guild=True)
    async def results(self, interaction: discord.Interaction, race_id: str, driver: str, position: int):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        if position < 1:
            await interaction.response.send_message("Finishing position must be 1 or greater.", ephemeral=True)
            return
        points = 5 if position == 1 else 4 if position == 2 else 3 if position == 3 else 2 if position == 4 else 1 if position <= 20 else 0
        race.setdefault("results", []).append({"driver": driver.strip(), "position": position, "points": points})
        race["results"].sort(key=lambda x: x.get("position", 999))
        save_json("races.json", data)
        await interaction.response.send_message(f"The result has been entered into the official record: **P{position} — {driver}** ({points} pts).", ephemeral=True)

    @app_commands.command(name="race", description="View an official race record.")
    @app_commands.describe(race_id="Race record ID")
    async def race(self, interaction: discord.Interaction, race_id: str):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        embed = bot_embed("Race Record", f"**{race['name']}** · `{race['id']}`")
        embed.add_field(name="Circuit", value=race.get("track", "—"), inline=True)
        embed.add_field(name="Laps", value=str(race.get("laps", "—")), inline=True)
        embed.add_field(name="Date", value=race.get("date", "—"), inline=True)
        embed.add_field(name="Status", value=race.get("status", "open").title(), inline=False)
        if race.get("qualifying"):
            embed.add_field(name="Grid", value="\n".join(f"P{q['position']} — {q['driver']} ({q['lap_time']})" for q in race["qualifying"]), inline=False)
        if race.get("results"):
            embed.add_field(name="Results", value="\n".join(f"P{r['position']} — {r['driver']} ({r['points']} pts)" for r in race["results"]), inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Races(bot))
