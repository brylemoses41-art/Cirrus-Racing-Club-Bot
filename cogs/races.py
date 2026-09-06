from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from constants import EVENT_CATEGORY_NAME, REMINDER_WINDOWS, points_for_position
from storage import load_json, save_json
from utils import bot_embed


class Races(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @staticmethod
    def find_race(races, race_id):
        return next((race for race in races if race.get("id") == race_id.upper()), None)

    @staticmethod
    def parse_date(value):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def qualifying_table(qualifying):
        lines = [
            "```text",
            "POS  DRIVER                         LAP",
            "────────────────────────────────────────────",
        ]
        for entry in qualifying:
            position = str(entry.get("position", "—"))
            driver = str(entry.get("driver", "—"))[:28]
            lap_time = str(entry.get("lap_time", "—"))
            lines.append(f"P{position:<3} {driver:<28} {lap_time}")
        lines.append("```")
        return "\n".join(lines)

    async def get_event_channel(self, guild, race, data):
        if race.get("channel_id"):
            channel = guild.get_channel(race["channel_id"])
            if channel:
                return channel

        category = discord.utils.get(guild.categories, name=EVENT_CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(EVENT_CATEGORY_NAME, reason="Cirrus Racing Club event setup")

        channel = await guild.create_text_channel(
            f"race-{race['id'].lower()}",
            category=category,
            reason="Cirrus Racing Club race event",
        )
        race["channel_id"] = channel.id
        save_json("races.json", data)
        return channel

    @app_commands.command(name="create_race", description="Create an official race record and event channel.")
    @app_commands.describe(name="Race name", track="Track", laps="Number of laps", date="ISO date/time, e.g. 2026-09-10 20:00")
    @app_commands.default_permissions(manage_guild=True)
    async def create_race(self, interaction: discord.Interaction, name: str, track: str, laps: int, date: str):
        await interaction.response.defer()

        if laps < 1:
            await interaction.followup.send("A race must contain at least one lap.", ephemeral=True)
            return

        data = load_json("races.json", {"races": []})
        races = data.setdefault("races", [])
        race_id = f"R{len(races) + 1:03d}"
        race = {
            "id": race_id, "name": name.strip(), "track": track.strip(), "laps": laps,
            "date": date.strip(), "status": "open", "created_by": interaction.user.id,
            "created_at": discord.utils.utcnow().isoformat(), "qualifying": [], "results": [],
            "penalties": [], "reports": [], "reminders_sent": [], "channel_id": None,
        }
        races.append(race)
        save_json("races.json", data)

        channel_text = "Channel not created."
        if interaction.guild:
            try:
                channel = await self.get_event_channel(interaction.guild, race, data)
                await channel.send(
                    f"# {race['name']}\n**Circuit:** {race['track']}\n**Distance:** {laps} lap(s)\n"
                    f"**Date:** {race['date']}\n\nRace Control has opened the event record."
                )
                channel_text = channel.mention
            except discord.Forbidden:
                channel_text = "Channel creation failed — check the bot's Manage Channels permission."

        embed = bot_embed("Race Control", "A new event has been entered into the official calendar.")
        embed.add_field(name="Race", value=f"**{race['name']}** (`{race_id}`)", inline=False)
        embed.add_field(name="Circuit", value=race["track"], inline=True)
        embed.add_field(name="Distance", value=f"{laps} lap(s)", inline=True)
        embed.add_field(name="Date", value=race["date"], inline=True)
        embed.add_field(name="Event Channel", value=channel_text, inline=False)
        embed.set_footer(text="Cirrus Racing Club • Race Control")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="qualifying", description="Record a driver's qualifying result and update the grid.")
    @app_commands.describe(race_id="Race record ID", driver="Driver name", lap_time="Qualifying lap time", position="Grid position")
    @app_commands.default_permissions(manage_guild=True)
    async def qualifying(self, interaction: discord.Interaction, race_id: str, driver: str, lap_time: str, position: int):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race or race.get("status") == "locked":
            await interaction.response.send_message("That race record is unavailable for qualifying entries.", ephemeral=True)
            return
        if position < 1:
            await interaction.response.send_message("Grid position must be 1 or greater.", ephemeral=True)
            return

        race.setdefault("qualifying", []).append({
            "driver": driver.strip(),
            "lap_time": lap_time.strip(),
            "position": position,
        })
        race["qualifying"].sort(key=lambda item: item.get("position", 999))
        save_json("races.json", data)

        embed = bot_embed(
            "Qualifying Grid",
            f"**{race['name']}** · `{race['id']}`\n{race.get('track', '—')}",
        )
        embed.add_field(
            name="Starting Grid",
            value=self.qualifying_table(race["qualifying"]),
            inline=False,
        )
        embed.set_footer(text="Cirrus Racing Club • Official Qualifying")

        if interaction.guild and race.get("channel_id"):
            channel = interaction.guild.get_channel(race["channel_id"])
            if channel:
                await channel.send(embed=embed)

        await interaction.response.send_message(
            f"Qualifying has been recorded: **P{position} — {driver} — {lap_time}**.",
            ephemeral=True,
        )

    @app_commands.command(name="results", description="Record an official race result and publish it to the event channel.")
    @app_commands.describe(race_id="Race record ID", driver="Driver name", position="Finishing position")
    @app_commands.default_permissions(manage_guild=True)
    async def results(self, interaction: discord.Interaction, race_id: str, driver: str, position: int):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        if race.get("status") == "locked":
            await interaction.response.send_message("That race record is locked.", ephemeral=True)
            return
        if position < 1:
            await interaction.response.send_message("Finishing position must be 1 or greater.", ephemeral=True)
            return

        points = points_for_position(position)
        race.setdefault("results", []).append({"driver": driver.strip(), "position": position, "points": points})
        race["results"].sort(key=lambda item: item.get("position", 999))
        save_json("races.json", data)

        if interaction.guild and race.get("channel_id"):
            channel = interaction.guild.get_channel(race["channel_id"])
            if channel:
                await channel.send(f"**Official Result**\nP{position} — **{driver.strip()}** — {points} pts")

        await interaction.response.send_message(
            f"The result has been entered into the official record: **P{position} — {driver}** ({points} pts).",
            ephemeral=True,
        )

    @app_commands.command(name="report", description="Submit an incident report to Race Control.")
    @app_commands.describe(race_id="Race record ID", driver="Driver involved", details="What happened")
    async def report(self, interaction: discord.Interaction, race_id: str, driver: str, details: str):
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        race.setdefault("reports", []).append({
            "driver": driver.strip(), "details": details.strip(),
            "reported_by": interaction.user.id, "created_at": discord.utils.utcnow().isoformat(),
        })
        save_json("races.json", data)
        await interaction.response.send_message("The incident has been submitted to Race Control.", ephemeral=True)

    @app_commands.command(name="penalty", description="Record a Race Control championship penalty.")
    @app_commands.describe(race_id="Race record ID", driver="Driver receiving the penalty", points="Championship points to remove", reason="Ruling")
    @app_commands.default_permissions(manage_guild=True)
    async def penalty(self, interaction: discord.Interaction, race_id: str, driver: str, points: int, reason: str):
        if points < 1:
            await interaction.response.send_message("Penalty points must be at least 1.", ephemeral=True)
            return
        data = load_json("races.json", {"races": []})
        race = self.find_race(data.get("races", []), race_id)
        if not race:
            await interaction.response.send_message("That race record could not be found.", ephemeral=True)
            return
        race.setdefault("penalties", []).append({
            "driver": driver.strip(), "points": points, "reason": reason.strip(),
            "issued_by": interaction.user.id, "created_at": discord.utils.utcnow().isoformat(),
        })
        save_json("races.json", data)
        await interaction.response.send_message("Race Control has issued the ruling and updated the official record.", ephemeral=True)

    async def set_lock(self, interaction, locked):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("This command must be used inside a server text channel.", ephemeral=True)
            return
        data = load_json("races.json", {"races": []})
        race = next((item for item in data.get("races", []) if item.get("channel_id") == interaction.channel.id), None)
        if not race:
            await interaction.response.send_message("This channel is not linked to a race record.", ephemeral=True)
            return
        race["status"] = "locked" if locked else "open"
        save_json("races.json", data)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False if locked else None
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason="Cirrus Racing Club event lockdown",
        )
        await interaction.response.send_message(
            "The event channel is now **locked**." if locked else "The event channel is now **open**.",
            ephemeral=True,
        )

    @app_commands.command(name="lockdown", description="Lock the current race event channel.")
    @app_commands.default_permissions(manage_guild=True)
    async def lockdown(self, interaction: discord.Interaction):
        await self.set_lock(interaction, True)

    @app_commands.command(name="open", description="Open the current race event channel.")
    @app_commands.default_permissions(manage_guild=True)
    async def open(self, interaction: discord.Interaction):
        await self.set_lock(interaction, False)

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
        if race.get("channel_id") and interaction.guild:
            channel = interaction.guild.get_channel(race["channel_id"])
            if channel:
                embed.add_field(name="Event Channel", value=channel.mention, inline=False)
        if race.get("qualifying"):
            embed.add_field(name="Grid", value=self.qualifying_table(race["qualifying"]), inline=False)
        if race.get("results"):
            embed.add_field(name="Results", value="\n".join(f"P{r['position']} — {r['driver']} ({r['points']} pts)" for r in race["results"]), inline=False)
        await interaction.response.send_message(embed=embed)

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        data = load_json("races.json", {"races": []})
        changed = False
        now = datetime.now(timezone.utc)
        for race in data.get("races", []):
            event_time = self.parse_date(race.get("date", ""))
            channel_id = race.get("channel_id")
            if not event_time or not channel_id:
                continue
            seconds_left = (event_time - now).total_seconds()
            sent = race.setdefault("reminders_sent", [])
            for window in REMINDER_WINDOWS:
                key = str(window)
                if 0 < seconds_left <= window and key not in sent:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        label = "24 hours" if window == 86400 else "1 hour"
                        await channel.send(
                            f"**Race Reminder**\n{race['name']} begins in approximately {label}. "
                            "Race Control has the event record prepared."
                        )
                        sent.append(key)
                        changed = True
        if changed:
            save_json("races.json", data)

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Races(bot))
