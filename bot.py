from __future__ import annotations

import os
import logging
from pathlib import Path

import discord
from discord.ext import commands

from utils.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

TOKEN    = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID")
DB_PATH  = os.environ.get("DB_PATH", "eclipse.db")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


class EclipseBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DB_PATH)

    async def setup_hook(self) -> None:
        await self.db.connect()
        log.info("Database connected: %s", DB_PATH)

        # ── Load all cogs ──────────────────────────────────────────────────────
        cogs_dir = Path(__file__).parent / "cogs"
        if cogs_dir.is_dir():
            for f in sorted(cogs_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                ext = f"cogs.{f.stem}"
                try:
                    await self.load_extension(ext)
                    log.info("Loaded %s", ext)
                except Exception:
                    log.exception("Failed to load %s", ext)

        # ── Sync commands ──────────────────────────────────────────────────────
        #
        # With GUILD_ID set (recommended for instant updates):
        #   1. copy_global_to  — copies all cog commands into the guild scope
        #   2. sync(guild)     — pushes them to Discord instantly ✓
        #   3. clear + sync()  — wipes the GLOBAL copy so commands only appear
        #                        once (no duplicates). Done AFTER guild sync.
        #
        # Without GUILD_ID: standard global sync (up to 1 hour to propagate).
        # ──────────────────────────────────────────────────────────────────────
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))

                # 1 + 2 — get commands into the guild first
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d commands to guild %s", len(synced), GUILD_ID)

                # 3 — now remove the global copy so nothing is doubled
                self.tree.clear_commands(guild=None)
                await self.tree.sync(guild=None)
                log.info("Cleared global commands (anti-duplicate)")
            else:
                synced = await self.tree.sync()
                log.info("Synced %d global commands", len(synced))
        except Exception:
            log.exception("Failed to sync commands")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    async def close(self) -> None:
        try:
            await self.db.close()
        except Exception:
            log.exception("Error closing database")
        await super().close()


bot = EclipseBot()


@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! `{latency_ms}ms`")


@bot.tree.command(name="sync", description="Owner-only: re-sync slash commands")
async def sync_cmd(interaction: discord.Interaction):
    app_info = await bot.application_info()
    if interaction.user.id != app_info.owner.id:
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync(guild=None)
        await interaction.followup.send(
            f"Synced {len(synced)} commands to guild `{GUILD_ID}`. Global duplicates cleared.",
            ephemeral=True,
        )
    else:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"Synced {len(synced)} global commands.", ephemeral=True)


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
