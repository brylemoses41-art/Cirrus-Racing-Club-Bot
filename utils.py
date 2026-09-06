import discord


def bot_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.from_rgb(43, 45, 49),
    )
