import discord


CRC_FOOTER = "Cirrus Racing Club • Race Control"


def bot_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.from_rgb(43, 45, 49),
    )


def set_crc_footer(embed: discord.Embed, section: str | None = None) -> discord.Embed:
    footer = CRC_FOOTER if not section else f"Cirrus Racing Club • {section}"
    embed.set_footer(text=footer)
    return embed
