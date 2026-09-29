# Cirrus Racing Club Bot

A security-first Discord server management bot.

## Features
- Owner-only administrative slash commands
- Server/channel/category/role management
- Security audit for risky permissions and verification settings
- Emergency lockdown and unlock
- Announcement helper
- OAuth2 invite-link generator for other Discord bots/apps
- Configuration through environment variables

## Setup
1. Create a Discord application and bot in the Discord Developer Portal.
2. Put the bot token in a Codespaces secret named DISCORD_TOKEN.
3. Set GUILD_ID and OWNER_IDS in the environment.
4. Install dependencies with `pip install -r requirements.txt`.
5. Run `python bot.py`.

Never commit a bot token.
