```python
import os
import sys
import asyncio
import datetime
import random
import json
import re
import traceback
import discord
from discord.ext import commands, tasks
from discord import app_commands

# ---------------------------------------------------------
# SETUP & CONFIGURATION (Environment Variables)
# ---------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_PREFIX = os.getenv("BOT_PREFIX", "!")

# Hardcoded Owner ID provided by user
PRIMARY_OWNER_ID = 1473641658078728202

# Try importing google.generativeai for Gemini support
try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
    else:
        gemini_model = None
except ImportError:
    genai = None
    gemini_model = None

# Database / In-Memory Data Storage (Persisted to JSON files)
PREMIUM_FILE = "premium_users.json"
WARNS_FILE = "warnings.json"
CONFIG_FILE = "security_config.json"
PREFIX_FILE = "prefixes.json"

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return default
    return default

def save_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filename}: {e}")

# Load databases
premium_users = load_json(PREMIUM_FILE, []) # List of user IDs or Usernames
warnings_db = load_json(WARNS_FILE, {})     # {guild_id: {user_id: [reasons]}}
security_db = load_json(CONFIG_FILE, {})   # {guild_id: {antinuke: bool, antiraid: bool, ...}}
prefixes_db = load_json(PREFIX_FILE, {})   # {guild_id: "prefix"}

# Dynamic Prefix Handler
def get_prefix(bot, message):
    if not message.guild:
        return DEFAULT_PREFIX
    return prefixes_db.get(str(message.guild.id), DEFAULT_PREFIX)

# Set up Bot Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.moderation = True

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    owner_id=PRIMARY_OWNER_ID
)

# In-Memory Cache for Anti-Spam / Anti-Raid tracking
message_tracker = {}
join_tracker = {}

# ---------------------------------------------------------
# HELPER FUNCTIONS & CHECKS
# ---------------------------------------------------------
def is_bot_owner():
    """Custom check to verify if the user is the primary hardcoded owner or team owner."""
    async def predicate(ctx):
        if ctx.author.id == PRIMARY_OWNER_ID or await ctx.bot.is_owner(ctx.author):
            return True
        embed = discord.Embed(
            title="⛔ Bot Owner Only",
            description="Only the official bot owner can use this command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return False
    return commands.check(predicate)

def is_premium():
    """Custom check to verify if a user or server has Premium access."""
    async def predicate(ctx):
        if ctx.author.id == PRIMARY_OWNER_ID or await ctx.bot.is_owner(ctx.author):
            return True
        user_str = f"{ctx.author.name}#{ctx.author.discriminator}" if ctx.author.discriminator != "0" else ctx.author.name
        guild_id_str = str(ctx.guild.id) if ctx.guild else ""
        
        if (ctx.author.id in premium_users or 
            str(ctx.author.id) in premium_users or 
            user_str in premium_users or 
            ctx.author.name in premium_users or
            guild_id_str in premium_users):
            return True
            
        embed = discord.Embed(
            title="🔒 Premium Restricted Feature",
            description="This feature/command requires **Premium Access**. Ask the Bot Owner to enable it using `addpremium`!",
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
        return False
    return commands.check(predicate)

# ---------------------------------------------------------
# BOT EVENTS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"==========================================")
    print(f" Bot Logged In As: {bot.user.name}#{bot.user.discriminator}")
    print(f" Bot ID: {bot.user.id}")
    print(f" Primary Owner ID: {PRIMARY_OWNER_ID}")
    print(f" Connected Guilds: {len(bot.guilds)}")
    print(f" Syncing Slash Commands...")
    try:
        synced = await bot.tree.sync()
        print(f" Synced {len(synced)} Slash Commands.")
    except Exception as e:
        print(f" Failed to sync slash commands: {e}")
    print(f" Gemini AI Status: {'Enabled' if gemini_model else 'Disabled / Missing Key'}")
    print(f"==========================================")
    
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name=f"slash & prefix commands | Help: /help"
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.event
async def on_command_error(ctx, error):
    """Global Error Handler"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore invalid commands
    
    elif isinstance(error, commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        embed = discord.Embed(
            title="🚫 Permission Denied",
            description=f"You need the following permission(s) to run this command: `{perms}`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    elif isinstance(error, commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        embed = discord.Embed(
            title="🤖 Bot Missing Permissions",
            description=f"I need the following permission(s) to perform this action: `{perms}`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    elif isinstance(error, commands.MissingRequiredArgument):
        current_prefix = get_prefix(bot, ctx.message) if ctx.message else DEFAULT_PREFIX
        embed = discord.Embed(
            title="⚠️ Missing Arguments",
            description=f"Missing parameter: `{error.param.name}`\nUsage: `{current_prefix}{ctx.command.qualified_name} {ctx.command.signature}`",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)

    elif isinstance(error, commands.CheckFailure):
        pass

    else:
        print(f"Unhandled Error: {error}")
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

# ---------------------------------------------------------
# CATEGORY 1: MODERATION COMMANDS (Prefix & Slash)
# ---------------------------------------------------------
class Moderation(commands.Cog):
    """Server moderation and management commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="kick", description="Kick a member from the server.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("❌ You cannot kick someone with an equal or higher role.")
        await member.kick(reason=reason)
        await ctx.send(embed=discord.Embed(
            title="Member Kicked",
            description=f"✅ {member.mention} has been kicked.\n**Reason:** {reason}",
            color=discord.Color.orange()
        ))

    @commands.hybrid_command(name="ban", description="Ban a member from the server.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason provided."):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("❌ You cannot ban someone with an equal or higher role.")
        await member.ban(reason=reason)
        await ctx.send(embed=discord.Embed(
            title="Member Banned",
            description=f"⛔ {member.mention} has been banned.\n**Reason:** {reason}",
            color=discord.Color.red()
        ))

    @commands.hybrid_command(name="unban", description="Unban a user by User ID or Name.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, *, user_input: str):
        banned_users = [entry async for entry in ctx.guild.bans()]
        for ban_entry in banned_users:
            user = ban_entry.user
            if user.name == user_input or str(user.id) == user_input or f"{user.name}#{user.discriminator}" == user_input:
                await ctx.guild.unban(user)
                return await ctx.send(f"✅ Unbanned **{user.name}**")
        await ctx.send("❌ User not found in the ban list.")

    @commands.hybrid_command(name="mute", description="Timeout/Mute a member for specified minutes.")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, minutes: int, *, reason: str = "No reason provided."):
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.send(f"🔇 Muted {member.mention} for {minutes} minute(s). Reason: {reason}")

    @commands.hybrid_command(name="unmute", description="Remove timeout/mute from a member.")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        await member.timeout(None)
        await ctx.send(f"🔊 Unmuted {member.mention}.")

    @commands.hybrid_command(name="purge", description="Clear a specified number of messages.")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        if amount > 100:
            return await ctx.send("❌ You can only purge up to 100 messages at once.")
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"🧹 Cleared {len(deleted) - 1} messages.")
        await asyncio.sleep(3)
        await msg.delete()

    @commands.hybrid_command(name="warn", description="Issue a warning to a member.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided."):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        if guild_id not in warnings_db:
            warnings_db[guild_id] = {}
        if user_id not in warnings_db[guild_id]:
            warnings_db[guild_id][user_id] = []
        
        warnings_db[guild_id][user_id].append({"reason": reason, "author": ctx.author.name, "date": str(datetime.date.today())})
        save_json(WARNS_FILE, warnings_db)
        await ctx.send(f"⚠️ Warned {member.mention}. Total warnings: **{len(warnings_db[guild_id][user_id])}**")

    @commands.hybrid_command(name="warnings", description="View warnings for a member.")
    async def warnings(self, ctx, member: discord.Member):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        user_warns = warnings_db.get(guild_id, {}).get(user_id, [])
        if not user_warns:
            return await ctx.send(f"✅ {member.mention} has no warnings.")
        
        embed = discord.Embed(title=f"Warnings for {member.name}", color=discord.Color.yellow())
        for idx, warn in enumerate(user_warns, 1):
            embed.add_field(name=f"Warning #{idx}", value=f"**Reason:** {warn['reason']}\n**By:** {warn['author']}\n**Date:** {warn['date']}", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="clearwarns", description="Clear all warnings for a member.")
    @commands.has_permissions(manage_messages=True)
    async def clearwarns(self, ctx, member: discord.Member):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        if guild_id in warnings_db and user_id in warnings_db[guild_id]:
            warnings_db[guild_id][user_id] = []
            save_json(WARNS_FILE, warnings_db)
            await ctx.send(f"🧹 Cleared all warnings for {member.mention}.")
        else:
            await ctx.send("No warnings found for this member.")

    @commands.hybrid_command(name="lock", description="Lock the current channel.")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked.")

    @commands.hybrid_command(name="unlock", description="Unlock the current channel.")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
        await ctx.send("🔓 Channel unlocked.")

    @commands.hybrid_command(name="slowmode", description="Set channel slowmode delay in seconds.")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        await ctx.channel.edit(slowmode_delay=seconds)
        await ctx.send(f"⏱️ Slowmode set to {seconds} seconds.")

    @commands.hybrid_command(name="nick", description="Change nickname of a member.")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str = None):
        await member.edit(nick=nickname)
        await ctx.send(f"✏️ Updated nickname for {member.mention}.")

    @commands.hybrid_command(name="role", description="Add or remove a role from a member.")
    @commands.has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member, role: discord.Role):
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"❌ Removed **{role.name}** from {member.mention}.")
        else:
            await member.add_roles(role)
            await ctx.send(f"✅ Added **{role.name}** to {member.mention}.")

    @commands.hybrid_command(name="tempban", description="Temporarily ban a member for specified minutes.")
    @commands.has_permissions(ban_members=True)
    async def tempban(self, ctx, member: discord.Member, minutes: int, *, reason: str = "Tempban"):
        await member.ban(reason=f"{reason} (Tempban {minutes}m)")
        await ctx.send(f"⛔ Temp-banned {member.name} for {minutes} minutes.")
        await asyncio.sleep(minutes * 60)
        await ctx.guild.unban(member)

# ---------------------------------------------------------
# CATEGORY 2: UTILITY COMMANDS (Prefix & Slash)
# ---------------------------------------------------------
class Utility(commands.Cog):
    """Useful tools, AI integrations, configuration, and info commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="custom_prefix", description="Set a custom prefix for this server.")
    @commands.has_permissions(administrator=True)
    async def custom_prefix(self, ctx, new_prefix: str):
        prefixes_db[str(ctx.guild.id)] = new_prefix
        save_json(PREFIX_FILE, prefixes_db)
        await ctx.send(f"⚙️ Server prefix updated to: `{new_prefix}`")

    @commands.hybrid_command(name="ping", description="Check latency of the bot.")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latency is `{latency}ms`.")

    @commands.hybrid_command(name="userinfo", description="Get detailed user info.")
    async def userinfo(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"User Info - {member.name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="Roles Count", value=len(member.roles) - 1, inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="serverinfo", description="Get detailed server info.")
    async def serverinfo(self, ctx):
        guild = ctx.guild
        embed = discord.Embed(title=f"Server Info - {guild.name}", color=discord.Color.blue())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Owner", value=guild.owner, inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Created At", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="avatar", description="Show user avatar.")
    async def avatar(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"{member.name}'s Avatar", color=discord.Color.purple())
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="gemini", description="Ask Google Gemini AI anything!")
    async def gemini(self, ctx, *, prompt: str):
        if not gemini_model:
            return await ctx.send("❌ Gemini API is not configured. Set `GEMINI_API_KEY` in environment variables.")
        
        if hasattr(ctx, "defer"):
            await ctx.defer()

        try:
            response = gemini_model.generate_content(prompt)
            text = response.text
            if len(text) > 1900:
                text = text[:1900] + "... (truncated)"
            embed = discord.Embed(title="🤖 Gemini AI Response", description=text, color=discord.Color.teal())
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Gemini Error: {e}")

    @commands.hybrid_command(name="say", description="Make the bot say something.")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx, *, message: str):
        if ctx.interaction:
            await ctx.send("Message sent!", ephemeral=True)
            await ctx.channel.send(message)
        else:
            await ctx.message.delete()
            await ctx.send(message)

    @commands.hybrid_command(name="embed", description="Create an embed message.")
    async def embed(self, ctx, title: str, *, description: str):
        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="poll", description="Create a reaction poll.")
    async def poll(self, ctx, *, question: str):
        embed = discord.Embed(title="📊 Poll", description=question, color=discord.Color.gold())
        embed.set_footer(text=f"Asked by {ctx.author.name}")
        msg = await ctx.send(embed=embed)
        if isinstance(msg, discord.Interaction):
            msg = await ctx.interaction.original_response()
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @commands.hybrid_command(name="botinfo", description="Get information about this bot.")
    async def botinfo(self, ctx):
        embed = discord.Embed(title="Bot Information", color=discord.Color.green())
        embed.add_field(name="Python Version", value=sys.version.split()[0])
        embed.add_field(name="Discord.py Version", value=discord.__version__)
        embed.add_field(name="Guilds Count", value=len(self.bot.guilds))
        embed.add_f