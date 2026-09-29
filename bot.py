import asyncio
import json
import urllib.request

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import DISCORD_TOKEN, GUILD_ID, OWNER_IDS

PLAN_URL = "https://raw.githubusercontent.com/brylemoses41-art/Cirrus-Racing-Club-Bot/main/data/server_plan.json"


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
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        plan_watcher.start()

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")
        print(f"Connected to {len(self.guilds)} guild(s).")


bot = ControlBot()


def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        return interaction.user.id in OWNER_IDS or interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)


async def fetch_plan():
    def read():
        with urllib.request.urlopen(PLAN_URL, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    return await asyncio.to_thread(read)


def build_overwrite(role, settings):
    overwrite = discord.PermissionOverwrite()
    for permission, value in settings.items():
        if hasattr(overwrite, permission):
            setattr(overwrite, permission, value if value in (True, False) else None)
    return overwrite


async def apply_plan(guild: discord.Guild, plan: dict):
    changes = []
    roles_by_name = {role.name: role for role in guild.roles}

    for spec in plan.get("roles", []):
        name = spec["name"]
        role = roles_by_name.get(name)
        permissions = discord.Permissions.none()

        for permission, value in spec.get("permissions", {}).items():
            if hasattr(permissions, permission):
                setattr(permissions, permission, bool(value))

        if role is None:
            role = await guild.create_role(
                name=name,
                permissions=permissions,
                reason="Declarative server plan",
            )
            changes.append(f"created role {name}")
        elif not role.is_default() and role.permissions != permissions:
            await role.edit(
                permissions=permissions,
                reason="Declarative server plan",
            )
            changes.append(f"updated permissions for role {name}")

        roles_by_name[name] = role

    categories_by_name = {c.name: c for c in guild.categories}

    for spec in plan.get("categories", []):
        name = spec["name"]
        category = categories_by_name.get(name)

        if category is None:
            category = await guild.create_category(
                name=name,
                reason="Declarative server plan",
            )
            changes.append(f"created category {name}")

        overwrites = {}
        for role_name, settings in spec.get("permissions", {}).items():
            role = roles_by_name.get(role_name)
            if role:
                overwrites[role] = build_overwrite(role, settings)

        if overwrites:
            await category.edit(
                overwrites=overwrites,
                reason="Declarative server plan",
            )
            changes.append(f"updated permissions for category {name}")

        categories_by_name[name] = category

    channels_by_name = {channel.name: channel for channel in guild.channels}

    for spec in plan.get("channels", []):
        name = spec["name"]
        kind = spec.get("type", "text")
        category = categories_by_name.get(spec.get("category"))
        channel = channels_by_name.get(name)

        if channel is None:
            if kind == "voice":
                channel = await guild.create_voice_channel(
                    name=name,
                    category=category,
                    reason="Declarative server plan",
                )
            else:
                channel = await guild.create_text_channel(
                    name=name,
                    category=category,
                    reason="Declarative server plan",
                )
            changes.append(f"created {kind} channel {name}")
        elif category and channel.category_id != category.id:
            await channel.edit(
                category=category,
                reason="Declarative server plan",
            )
            changes.append(f"moved {name} into {category.name}")

        overwrites = {}
        for role_name, settings in spec.get("permissions", {}).items():
            role = roles_by_name.get(role_name)
            if role:
                overwrites[role] = build_overwrite(role, settings)

        if overwrites:
            await channel.edit(
                overwrites=overwrites,
                reason="Declarative server plan",
            )
            changes.append(f"updated permissions for channel {name}")

        channels_by_name[name] = channel

    return changes


@tasks.loop(seconds=10)
async def plan_watcher():
    if not bot.is_ready():
        return

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    try:
        plan = await fetch_plan()
        if not plan.get("enabled", False):
            return

        changes = await apply_plan(guild, plan)
        if changes:
            print("Applied server plan:")
            for change in changes:
                print(f" - {change}")
    except Exception as error:
        print(f"Server plan error: {error!r}")


@plan_watcher.before_loop
async def before_plan_watcher():
    await bot.wait_until_ready()


@bot.tree.command(name="server_info", description="Show basic information about this server.")
@owner_only()
async def server_info(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=guild.name)
    embed.add_field(name="Server ID", value=str(guild.id), inline=False)
    embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


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

    lines = [
        "Security audit",
        f"• Server moderation 2FA: {'ON' if guild.mfa_level else 'OFF'}",
        f"• @everyone Administrator: {'YES' if everyone.permissions.administrator else 'NO'}",
        f"• Administrator roles: {len(dangerous_roles)}",
    ]

    if risky:
        lines.append(" @everyone risks")
        lines.extend(f"• {item}" for item in risky)
    else:
        lines.append(" No high-risk @everyone permissions found.")

    if dangerous_roles:
        lines.append(" Administrator roles")
        lines.extend(f"• {role.name}" for role in dangerous_roles[:20])
    else:
        lines.append(" No non-default Administrator roles found.")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="plan_status", description="Show whether remote server automation is enabled.")
@owner_only()
async def plan_status(interaction: discord.Interaction):
    try:
        plan = await fetch_plan()
        await interaction.response.send_message(
            f"Remote server automation: {'ON' if plan.get('enabled') else 'OFF'}",
            ephemeral=True,
        )
    except Exception as error:
        await interaction.response.send_message(
            f"Could not read the server plan: {error}",
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
    raise RuntimeError("GUILD_ID is required for server automation.")

bot.run(DISCORD_TOKEN)
