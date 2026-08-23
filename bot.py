import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuration / Constants
VALID_GAMEMODES = ["Sword", "Crystal", "NethPot", "Axe", "SMP", "UHC"]
VALID_TIERS = [
    "HT1", "LT1", "HT2", "LT2",
    "HT3", "LT3", "HT4", "LT4",
    "HT5", "LT5", "Unranked"
]

# Database Setup
def init_db():
    conn = sqlite3.connect("mctiers.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER,
            gamemode TEXT,
            tier TEXT,
            PRIMARY KEY (user_id, gamemode)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            gamemode TEXT,
            ign TEXT,
            status TEXT DEFAULT 'PENDING',
            tester_id INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# UI Elements: Modal for Testers to Record Results
class ResultModal(discord.ui.Modal, title="Submit Test Result"):
    score = discord.ui.TextInput(
        label="Final Score (Tester - Candidate)",
        placeholder="e.g. 5-3",
        required=True
    )
    assigned_tier = discord.ui.TextInput(
        label="Assigned Tier",
        placeholder="e.g. HT3, LT3, HT4, LT4...",
        required=True,
        max_length=10
    )
    notes = discord.ui.TextInput(
        label="Tester Notes / Feedback",
        style=discord.TextStyle.paragraph,
        placeholder="Optional observations on movement, spacing, etc.",
        required=False
    )

    def __init__(self, ticket_id: int, candidate_id: int, gamemode: str):
        super().__init__()
        self.ticket_id = ticket_id
        self.candidate_id = candidate_id
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        tier_val = self.assigned_tier.value.upper().strip()
        if tier_val not in VALID_TIERS:
            await interaction.response.send_message(
                f"❌ Invalid tier specified. Choose from: `{', '.join(VALID_TIERS)}`", 
                ephemeral=True
            )
            return

        conn = sqlite3.connect("mctiers.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO profiles (user_id, gamemode, tier)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, gamemode) DO UPDATE SET tier=excluded.tier
        """, (self.candidate_id, self.gamemode, tier_val))
        
        cursor.execute("""
            UPDATE test_queue
            SET status = 'COMPLETED', tester_id = ?
            WHERE id = ?
        """, (interaction.user.id, self.ticket_id))
        
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title="⚔️ MCTiers Evaluation Result",
            color=discord.Color.green()
        )
        embed.add_field(name="Candidate", value=f"<@{self.candidate_id}>", inline=True)
        embed.add_field(name="Gamemode", value=self.gamemode, inline=True)
        embed.add_field(name="Assigned Tier", value=f"**{tier_val}**", inline=True)
        embed.add_field(name="Score", value=self.score.value, inline=True)
        embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
        if self.notes.value:
            embed.add_field(name="Notes", value=self.notes.value, inline=False)

        await interaction.response.send_message(embed=embed)

# Slash Commands
@bot.tree.command(name="request_test", description="Request a tier test for a specific gamemode.")
@app_commands.describe(gamemode="Choose the kit/gamemode", ign="Your in-game Minecraft username")
@app_commands.choices(gamemode=[app_commands.Choice(name=gm, value=gm) for gm in VALID_GAMEMODES])
async def request_test(interaction: discord.Interaction, gamemode: app_commands.Choice[str], ign: str):
    user_id = interaction.user.id
    selected_gm = gamemode.value

    conn = sqlite3.connect("mctiers.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM test_queue 
        WHERE user_id = ? AND gamemode = ? AND status = 'PENDING'
    """, (user_id, selected_gm))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        await interaction.response.send_message(
            f"❌ You already have an active **{selected_gm}** test request pending!", 
            ephemeral=True
        )
        return

    cursor.execute("""
        INSERT INTO test_queue (user_id, gamemode, ign)
        VALUES (?, ?, ?)
    """, (user_id, selected_gm, ign))
    ticket_id = cursor.lastrowid
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="📥 Tier Test Requested",
        description=f"Your request has been added to the testing queue.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Ticket ID", value=f"#{ticket_id}", inline=True)
    embed.add_field(name="Gamemode", value=selected_gm, inline=True)
    embed.add_field(name="IGN", value=ign, inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="view_queue", description="Display all currently pending test requests.")
async def view_queue(interaction: discord.Interaction):
    conn = sqlite3.connect("mctiers.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, gamemode, ign FROM test_queue
        WHERE status = 'PENDING'
        ORDER BY id ASC LIMIT 10
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("The test queue is currently empty!", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Active Testing Queue", color=discord.Color.gold())
    for ticket_id, uid, gm, ign in rows:
        embed.add_field(
            name=f"Ticket #{ticket_id} | {gm}",
            value=f"**User:** <@{uid}>\n**IGN:** `{ign}`",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="tier_profile", description="View a player's official MCTiers profile.")
@app_commands.describe(user="The player whose profile you want to check")
async def profile(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user

    conn = sqlite3.connect("mctiers.db")
    cursor = conn.cursor()
    cursor.execute("SELECT gamemode, tier FROM profiles WHERE user_id = ?", (target.id,))
    rows = cursor.fetchall()
    conn.close()

    embed = discord.Embed(
        title=f"🛡️ MCTiers Profile: {target.name}",
        color=discord.Color.purple()
    )
    
    tier_map = {gm: "Unranked" for gm in VALID_GAMEMODES}
    for gm, tier in rows:
        tier_map[gm] = tier

    for gm, tier in tier_map.items():
        embed.add_field(name=gm, value=f"`{tier}`", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="grade_test", description="[Testers Only] Grade a pending ticket test.")
@app_commands.describe(ticket_id="The ID number of the ticket you are grading")
async def grade_test(interaction: discord.Interaction, ticket_id: int):
    conn = sqlite3.connect("mctiers.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, gamemode, status FROM test_queue WHERE id = ?
    """, (ticket_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await interaction.response.send_message(f"❌ Ticket `#{ticket_id}` not found.", ephemeral=True)
        return

    uid, gm, status = row
    if status != 'PENDING':
        await interaction.response.send_message(f"❌ Ticket `#{ticket_id}` has already been processed.", ephemeral=True)
        return

    modal = ResultModal(ticket_id=ticket_id, candidate_id=uid, gamemode=gm)
    await interaction.response.send_modal(modal)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("Missing DISCORD_TOKEN environment variable.")
    bot.run(TOKEN)

