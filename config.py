import os


BOT_NAME = "Cirrus Racing Club"
TOKEN_ENV_NAME = "DISCORD_TOKEN"


def get_token() -> str:
    token = os.getenv(TOKEN_ENV_NAME)

    if not token:
        raise RuntimeError(
            f"{TOKEN_ENV_NAME} is missing. Add it to your .env file."
        )

    return token
