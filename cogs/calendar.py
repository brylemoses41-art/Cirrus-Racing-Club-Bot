import discord
from datetime import datetime, timedelta

from discord import app_commands
from discord.ext import commands

from utils import bot_embed


SEASON_CALENDAR = [
    {"round": 1, "country": "🇯🇵 Japan", "circuit": "Tsukuba Circuit", "date": "2026-09-20", "time": "20:00", "laps": 20},
    {"round": 2, "country": "🇬🇧 United Kingdom", "circuit": "Cadwell Park", "date": "2026-10-04", "time": "20:00", "laps": 15},
    {"round": 3, "country": "🇮🇹 Italy", "circuit": "Imola", "date": "2026-10-18", "time": "20:00", "laps": 18},
    {"round": 4, "country": "🇬🇧 United Kingdom", "circuit": "Brands Hatch GP", "date": "2026-11-01", "time": "20:00", "laps": 18},
    {"round": 5, "country": "🇧🇪 Belgium", "circuit": "Spa-Francorchamps", "date": "2026-11-15", "time": "20:00", "laps": 14},
    {"round": 6, "country": "🇯🇵 Japan", "circuit": "Suzuka Circuit", "date": "2026-11-29", "time": "20:00", "laps": 15},
    {"round": 7, "country": "🇺🇸 United States", "circuit": "Laguna Seca", "date": "2026-12-13", "time": "20:00", "laps": 20},
    {"round": 8, "country": "🇮🇹 Italy", "circuit": "Monza", "date": "2026-12-27", "time": "20:00", "laps": 18},
    {"round": 9, "country": "🇩🇪 Germany", "circuit": "Nürburgring Nordschleife", "date": "2027-01-10", "time": "20:00", "laps": 15, "special": "⭐ CRC MARQUEE EVENT"},
    {"round": 10, "country": "🇦🇺 Australia", "circuit": "Bathurst", "date": "2027-01-24", "time": "20:00", "laps": 15},
    {"round": 11, "country": "🇦🇹 Austria", "circuit": "Red Bull Ring", "date": "2027-02-07", "time": "20:00", "laps": 22},
    {"round": 12, "country": "🇦🇪 Abu Dhabi", "circuit": "Yas Marina Circuit", "date": "2027-02-21", "time": "20:00", "laps": 20, "special": "🏆 SEASON FINALE"},
]


def session_schedule(event):
    race_date = datetime.strptime(event["date"], "%Y-%m-%d")
    return [
        ("Practice 1", race_date - timedelta(days=3), event["time"]),
        ("Practice 2", race_date - timedelta(days=2), event["time"]),
        ("Practice 3", race_date - timedelta(days=1), event["time"]),
    ]


class Calendar(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="calendar", description="View the official Cirrus Racing Club season calendar.")
    async def calendar(self, interaction: discord.Interaction):
        embed = bot_embed(
            "CRC 2026–27 Calendar",
            "The official season schedule. Three practice sessions precede every Grand Prix.",
        )

        for event in SEASON_CALENDAR:
            sessions = session_schedule(event)
            practice_text = "\n".join(
                f"**{name}** — {date.strftime('%Y-%m-%d')} at **{time}**"
                for name, date, time in sessions
            )
            value = (
                f"📅 **Race:** {event['date']} at **{event['time']}**\n"
                f"🏎️ **{event['laps']} laps**\n\n"
                f"**Practice Sessions**\n{practice_text}"
            )
            if event.get("special"):
                value += f"\n{event['special']}"

            embed.add_field(
                name=f"ROUND {event['round']:02d}  ·  {event['country']}\n{event['circuit']}",
                value=value,
                inline=False,
            )

        embed.set_footer(text="Cirrus Racing Club • Official Season Calendar")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
