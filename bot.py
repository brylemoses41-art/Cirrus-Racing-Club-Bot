import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_TOKEN, GUILD_ID, OWNER_IDS


class ControlBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def setup_hook(self):
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")
        print(f"Connected to {len(self.guilds)} guild(s).")


bot = ControlBot()


def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id in OWNER_IDS or interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)


@bot.tree.command(name="server_info", description="Show basic information about this server.")
@owner_only()
async def server_info(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    embed = discord.Embed(title=guild.name)
    embed.add_field(name="Server ID", value=str(guild.id), inline=False)
    embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="2FA for moderation", value="Required" if guild.mfa_level else "Not required", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="create_category", description="Create a server category.")
@app_commands.describe(name="Category name")
@owner_only()
async def create_category(interaction: discord.Interaction, name: str):
    category = await interaction.guild.create_category(name=name, reason=f"Requested by {interaction.user}")
    await interaction.response.send_message(f"Created category **{category.name}**.", ephemeral=True)


@bot.tree.command(name="create_channel", description="Create a text channel.")
@app_commands.describe(name="Channel name", category="Optional category")
@owner_only()
async def create_channel(interaction: discord.Interaction, name: str, category: discord.CategoryChannel | None = None):
    channel = await interaction.guild.create_text_channel(name=name, category=category, reason=f"Requested by {interaction.user}")
    await interaction.response.send_message(f"Created {channel.mention}.", ephemeral=True)


@bot.tree.command(name="rename_channel", description="Rename a channel.")
@app_commands.describe(channel="Channel to rename", name="New name")
@owner_only()
async def rename_channel(interaction: discord.Interaction, channel: discord.TextChannel, name: str):
    await channel.edit(name=name, reason=f"Requested by {interaction.user}")
    await interaction.response.send_message(f"Renamed channel to **{name}**.", ephemeral=True)


@bot.tree.command(name="delete_channel", description="Delete a channel.")
@app_commands.describe(channel="Channel to delete")
@owner_only()
async def delete_channel(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    name = channel.name
    await channel.delete(reason=f"Requested by {interaction.user}")
    await interaction.response.send_message(f"Deleted **{name}**.", ephemeral=True)


@bot.tree.command(name="create_role", description="Create a server role.")
@app_commands.describe(name="Role name")
@owner_only()
async def create_role(interaction: discord.Interaction, name: str):
    role = await interaction.guild.create_role(name=name, reason=f"Requested by {interaction.user}")
    await interaction.response.send_message(f"Created role **{role.name}**.", ephemeral=True)


@bot.tree.command(name="security_audit", description="Audit common server security settings.")
@owner_only()
async def security_audit(interaction: discord.Interaction):
    guild = interaction.guild
    everyone = guild.default_role
    risky = []

    if everyone.permissions.administrator:
        risky.append("@everyone has Administrator.")
    if everyone.permissions.manage_guild:
        risky.append("@everyone can Manage Server.")
    if everyone.permissions.manage_roles:
        risky.append("@everyone can Manage Roles.")
    if everyone.permissions.manage_channels:
        risky.append("@everyone can Manage Channels.")

    dangerous_roles = [
        role for role in guild.roles
        if not role.is_default() and role.permissions.administrator
    ]

    lines = []
    lines.append("🔐 **Security audit**")
    lines.append(f"• Server moderation 2FA: {'ON' if guild.mfa_level else 'OFF'}")
    lines.append(f"• @everyone Administrator: {'YES' if everyone.permissions.administrator else 'NO'}")
    lines.append(f"• Administrator roles: {len(dangerous_roles)}")

    if risky:
        lines.append("\n⚠️ **@everyone risks**")
        lines.extend(f"• {item}" for item in risky)
    else:
        lines.append("\n✅ No high-risk @everyone permissions found.")

    if dangerous_roles:
        lines.append("\n⚠️ **Administrator roles**")
        lines.extend(f"• {role.name}" for role in dangerous_roles[:20])
    else:
        lines.append("\n✅ No non-default Administrator roles found.")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="lockdown", description="Temporarily prevent @everyone from sending messages in text channels.")
@owner_only()
async def lockdown(interaction: discord.Interaction):
    changed = 0
    everyone = interaction.guild.default_role

    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False
        try:
            await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Emergency lockdown by {interaction.user}")
            changed += 1
        except discord.Forbidden:
            pass

    await interaction.response.send_message(f"Lockdown applied to {changed} text channels.", ephemeral=True)


@bot.tree.command(name="unlock", description="Remove the bot's lockdown restriction from text channels.")
@owner_only()
async def unlock(interaction: discord.Interaction):
    changed = 0
    everyone = interaction.guild.default_role

    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = None
        try:
            await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Unlock by {interaction.user}")
            changed += 1
        except discord.Forbidden:
            pass

    await interaction.response.send_message(f"Lockdown restriction removed from {changed} text channels.", ephemeral=True)


@bot.tree.command(name="announce", description="Send an announcement to a selected text channel.")
@app_commands.describe(channel="Destination channel", message="Announcement text")
@owner_only()
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    await channel.send(message)
    await interaction.response.send_message(f"Announcement sent to {channel.mention}.", ephemeral=True)


@bot.tree.command(name="bot_invite", description="Generate a standard OAuth2 invite link for another Discord bot.")
@app_commands.describe(client_id="The other bot application's client ID")
@owner_only()
async def bot_invite(interaction: discord.Interaction, client_id: str):
    if not client_id.isdigit():
        await interaction.response.send_message("Client ID must be numeric.", ephemeral=True)
        return

    permissions = discord.Permissions(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )
    url = discord.utils.oauth_url(
        int(client_id),
        permissions=permissions,
        scopes=("bot", "applications.commands"),
        guild=interaction.guild,
        disable_guild_select=False,
    )
    await interaction.response.send_message(
        f"Invite link generated. Discord still requires an authorized user with permission to install the bot.\n{url}",
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        message = "You are not authorized to use this command."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "The bot does not have the Discord permissions required for that action."
    else:
        message = "The command failed. Check the bot logs for details."
        print(repr(error))

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")
if not GUILD_ID:
    print("Warning: GUILD_ID is not set; commands will sync globally.")

bot.run(DISCORD_TOKEN)
