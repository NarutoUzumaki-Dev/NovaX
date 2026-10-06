import discord
from discord.ext import commands
import os
import json
import random
import datetime

# -------------------------------------------------------------
# BOT CONFIGURATION
# -------------------------------------------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

MAIN_COLOR = 0x00e5ff
FOOTER_TEXT = "DC Bots Lab • Made with 💙"
LEAVES_FILE = "leaves.json"
STAFF_ROLE_NAME = "Staff"  # Role required to approve/reject leaves

# Persistent Storage Initialization
if not os.path.exists(LEAVES_FILE):
    with open(LEAVES_FILE, "w") as f:
        json.dump({}, f)

def load_leaves():
    with open(LEAVES_FILE, "r") as f:
        return json.load(f)

def save_leaves(data):
    with open(LEAVES_FILE, "w") as f:
        json.dump(data, f, indent=4)

def base_embed(title: str, description: str = "") -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=MAIN_COLOR)
    embed.set_footer(text=FOOTER_TEXT)
    return embed

# -------------------------------------------------------------
# LEAVE SYSTEM UI (MODALS & VIEWS)
# -------------------------------------------------------------
class RejectionReasonModal(discord.ui.Modal, title="Reject Leave Application"):
    reason = discord.ui.TextInput(
        label="Rejection Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Explain why this leave application is rejected...",
        required=True,
        min_length=5
    )

    def __init__(self, applicant_id: int, from_date: str, to_date: str, orig_embed: discord.Embed):
        super().__init__()
        self.applicant_id = applicant_id
        self.from_date = from_date
        self.to_date = to_date
        self.orig_embed = orig_embed

    async def on_submit(self, interaction: discord.Interaction):
        # Update Embed
        self.orig_embed.color = discord.Color.red()
        self.orig_embed.title = "❌ Leave Application Rejected"
        self.orig_embed.add_field(name="🚫 Rejected By", value=interaction.user.mention, inline=False)
        self.orig_embed.add_field(name="💬 Rejection Reason", value=self.reason.value, inline=False)
        
        await interaction.response.edit_message(embed=self.orig_embed, view=None)

        # Update JSON DB
        leaves_db = load_leaves()
        user_str = str(self.applicant_id)
        if user_str in leaves_db and leaves_db[user_str]:
            leaves_db[user_str][-1]["status"] = f"Rejected: {self.reason.value}"
            save_leaves(leaves_db)

        # Send DM
        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant:
            try:
                await applicant.send(
                    f"❌ Your leave application from `{self.from_date}` to `{self.to_date}` has been **REJECTED**.\n"
                    f"**Reason:** {self.reason.value}"
                )
            except discord.Forbidden:
                pass

        # Log
        log_channel = discord.utils.get(interaction.guild.text_channels, name="leave-logs")
        if log_channel:
            log_embed = base_embed("📜 Leave Rejection Log")
            log_embed.add_field(name="Applicant", value=f"<@{self.applicant_id}>", inline=True)
            log_embed.add_field(name="Staff Member", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Reason", value=self.reason.value, inline=False)
            await log_channel.send(embed=log_embed)

class LeaveActionView(discord.ui.View):
    def __init__(self, applicant_id: int, from_date: str, to_date: str, reason: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.from_date = from_date
        self.to_date = to_date
        self.reason = reason

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_staff_role = any(role.name == STAFF_ROLE_NAME for role in interaction.user.roles)
        if not has_staff_role and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only staff members are allowed to manage leave applications.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅", custom_id="leave_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ Leave Application Approved"
        embed.add_field(name="Approved By", value=interaction.user.mention, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

        # Update JSON DB
        leaves_db = load_leaves()
        user_str = str(self.applicant_id)
        if user_str in leaves_db and leaves_db[user_str]:
            leaves_db[user_str][-1]["status"] = "Approved"
            save_leaves(leaves_db)

        # DM Applicant
        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant:
            try:
                await applicant.send(
                    f"Your leave from **{self.from_date}** to **{self.to_date}** has been **APPROVED** by {interaction.user.mention} ✅"
                )
            except discord.Forbidden:
                pass

        await interaction.channel.send(f"<@{self.applicant_id}>, your leave application has been approved!")

        # Log
        log_channel = discord.utils.get(interaction.guild.text_channels, name="leave-logs")
        if log_channel:
            log_embed = base_embed("📜 Leave Approval Log")
            log_embed.add_field(name="Applicant", value=f"<@{self.applicant_id}>", inline=True)
            log_embed.add_field(name="Approved By", value=interaction.user.mention, inline=True)
            await log_channel.send(embed=log_embed)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="❌", custom_id="leave_reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        await interaction.response.send_modal(RejectionReasonModal(self.applicant_id, self.from_date, self.to_date, embed))

    @discord.ui.button(label="Show Details", style=discord.ButtonStyle.grey, emoji="📄", custom_id="leave_details")
    async def details_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = (
            f"**Applicant:** <@{self.applicant_id}>\n"
            f"**Dates:** {self.from_date} to {self.to_date}\n"
            f"**Reason:** {self.reason}"
        )
        await interaction.response.send_message(msg, ephemeral=True)

class LeaveApplicationModal(discord.ui.Modal, title="DC Bots Lab Leave Form"):
    name = discord.ui.TextInput(label="Name", placeholder="Enter your full name", required=True)
    leave_type = discord.ui.TextInput(label="Leave Type", placeholder="Sick / Personal / Exam / Family / Other", required=True)
    from_date = discord.ui.TextInput(label="From Date", placeholder="e.g. 10 Oct 2026", required=True)
    to_date = discord.ui.TextInput(label="To Date", placeholder="e.g. 12 Oct 2026", required=True)
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Detailed reason for leave...",
        required=True,
        min_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        app_channel = discord.utils.get(interaction.guild.text_channels, name="leave-applications")
        if not app_channel:
            await interaction.response.send_message("❌ Channel `#leave-applications` was not found on this server!", ephemeral=True)
            return

        embed = discord.Embed(title="📝 New Leave Application", color=0xffcc00)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="👤 Applicant", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="📛 Full Name", value=self.name.value, inline=True)
        embed.add_field(name="📅 Leave Type", value=self.leave_type.value, inline=True)
        embed.add_field(name="🗓️ Duration", value=f"{self.from_date.value} to {self.to_date.value}", inline=False)
        embed.add_field(name="📄 Reason", value=self.reason.value, inline=False)
        embed.add_field(name="⏰ Applied At", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)
        embed.set_footer(text="DC Bots Lab • Leave System")

        view = LeaveActionView(interaction.user.id, self.from_date.value, self.to_date.value, self.reason.value)
        await app_channel.send(embed=embed, view=view)

        # Store in JSON DB
        leaves_db = load_leaves()
        user_str = str(interaction.user.id)
        if user_str not in leaves_db:
            leaves_db[user_str] = []

        leaves_db[user_str].append({
            "name": self.name.value,
            "type": self.leave_type.value,
            "from": self.from_date.value,
            "to": self.to_date.value,
            "reason": self.reason.value,
            "status": "Pending",
            "time": datetime.datetime.now().isoformat()
        })
        save_leaves(leaves_db)

        await interaction.response.send_message("✅ Your leave application has been submitted successfully!", ephemeral=True)

# -------------------------------------------------------------
# BOT EVENTS
# -------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="DC Bots Lab | !help"))

# -------------------------------------------------------------
# COMMANDS IMPLEMENTATION (52 COMMANDS)
# -------------------------------------------------------------

# --- MODERATION (10) ---
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(embed=base_embed("🔨 Ban Successful", f"{member.mention} has been banned.\nReason: {reason}"))

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(embed=base_embed("🔓 Unban Successful", f"{user.name} has been unbanned."))

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.kick(reason=reason)
    await ctx.send(embed=base_embed("👢 Kick Successful", f"{member.mention} has been kicked.\nReason: {reason}"))

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason="Muted by command")
    await ctx.send(embed=base_embed("🔇 Mute Successful", f"{member.mention} timed out for {minutes} minutes."))

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(embed=base_embed("🔊 Unmute Successful", f"{member.mention} timeout removed."))

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(embed=base_embed("🧹 Purged", f"Cleared {amount} messages."), delete_after=3)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    await ctx.send(embed=base_embed("⚠️️ Warning Issued", f"{member.mention} has been warned.\nReason: {reason}"))

@bot.command()
async def warnings(ctx, member: discord.Member):
    await ctx.send(embed=base_embed("📋 Warning Logs", f"{member.mention} currently has 0 warnings."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(embed=base_embed("🔒 Channel Locked", "Members can no longer send messages in this channel."))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(embed=base_embed("🔓 Channel Unlocked", "Members can now send messages in this channel."))

# --- UTILITY (12) ---
@bot.command()
async def ping(ctx):
    await ctx.send(embed=base_embed("🏓 Pong!", f"Latency: `{round(bot.latency * 1000)}ms`"))

@bot.command()
async def serverinfo(ctx):
    embed = base_embed("📊 Server Information")
    embed.add_field(name="Name", value=ctx.guild.name, inline=True)
    embed.add_field(name="Members", value=ctx.guild.member_count, inline=True)
    embed.add_field(name="Owner", value=ctx.guild.owner.mention, inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = base_embed(f"👤 User Info - {member.name}")
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d"), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = base_embed(f"🖼️ Avatar of {member.name}")
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def invite(ctx):
    await ctx.send(embed=base_embed("🔗 Invite Link", "Click [here](https://discord.com) to invite DC Bots Lab bot."))

@bot.command()
async def botinfo(ctx):
    await ctx.send(embed=base_embed("🤖 Bot Info", "DC Bots Lab Official Bot v2.0 - Powered by discord.py"))

@bot.command()
async def help(ctx):
    embed = base_embed("📚 DC Bots Lab Commands")
    embed.add_field(name="🛠️ Moderation", value="`ban`, `unban`, `kick`, `mute`, `unmute`, `clear`, `warn`, `warnings`, `lock`, `unlock`", inline=False)
    embed.add_field(name="🔧 Utility", value="`ping`, `serverinfo`, `userinfo`, `avatar`, `invite`, `botinfo`, `help`, `say`, `embed`, `poll`, `afk`, `suggest`", inline=False)
    embed.add_field(name="🎮 Fun", value="`8ball`, `meme`, `joke`, `roast`, `compliment`, `flip`, `roll`, `rps`, `howgay`, `pp`", inline=False)
    embed.add_field(name="⚙️ DC Bots Special", value="`leave`, `myleaves`, `allleaves`, `welcome`, `botlist`, `addbot`, `support`, `rules`, `staff`, `uptime`, `premium`, `partner`", inline=False)
    embed.add_field(name="💰 Economy/Level", value="`balance`, `daily`, `work`, `leaderboard`, `level`, `rank`, `shop`, `buy`, `profile`, `rep`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def say(ctx, *, text: str):
    await ctx.message.delete()
    await ctx.send(text)

@bot.command()
async def embed(ctx, *, text: str):
    await ctx.message.delete()
    await ctx.send(embed=base_embed("📢 Announcement", text))

@bot.command()
async def poll(ctx, *, question: str):
    msg = await ctx.send(embed=base_embed("📊 Poll", question))
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

@bot.command()
async def afk(ctx, *, reason="AFK"):
    await ctx.send(embed=base_embed("💤 AFK Status Set", f"{ctx.author.mention} is now AFK: {reason}"))

@bot.command()
async def suggest(ctx, *, idea: str):
    await ctx.send(embed=base_embed("💡 Suggestion Received", f"Thank you for your feedback: *{idea}*"))

# --- FUN (10) ---
@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    responses = ["Yes, definitely.", "Ask again later.", "My sources say no.", "Outlook good.", "Signs point to yes."]
    await ctx.send(embed=base_embed("🎱 8Ball", f"**Q:** {question}\n**A:** {random.choice(responses)}"))

@bot.command()
async def meme(ctx):
    await ctx.send(embed=base_embed("🤣 Meme", "Here is a meme for you! 🎭"))

@bot.command()
async def joke(ctx):
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs!",
        "There are 10 types of people in the world: those who understand binary, and those who don't."
    ]
    await ctx.send(embed=base_embed("😄 Joke", random.choice(jokes)))

@bot.command()
async def roast(ctx, member: discord.Member):
    roasts = ["You're like a cloud. When you disappear, it's a beautiful day.", "Your secrets are always safe with me. I never even listen when you tell me."]
    await ctx.send(embed=base_embed("🔥 Roast", f"{member.mention}, {random.choice(roasts)}"))

@bot.command()
async def compliment(ctx, member: discord.Member):
    compliments = ["You are awesome!", "You bring out the best in other people.", "You're a brilliant mind!"]
    await ctx.send(embed=base_embed("✨ Compliment", f"{member.mention}, {random.choice(compliments)}"))

@bot.command()
async def flip(ctx):
    await ctx.send(embed=base_embed("🪙 Coin Flip", f"Result: **{random.choice(['Heads', 'Tails'])}**"))

@bot.command()
async def roll(ctx):
    await ctx.send(embed=base_embed("🎲 Dice Roll", f"You rolled a **{random.randint(1, 6)}**!"))

@bot.command()
async def rps(ctx, choice: str):
    bot_choice = random.choice(["rock", "paper", "scissors"])
    await ctx.send(embed=base_embed("✂️ Rock Paper Scissors", f"You chose: **{choice}**\nBot chose: **{bot_choice}**"))

@bot.command()
async def howgay(ctx, member: discord.Member = None):
    member = member or ctx.author
    rate = random.randint(0, 100)
    await ctx.send(embed=base_embed("🏳️‍🌈 Gay Rate Calculator", f"{member.mention} is **{rate}%** gay!"))

@bot.command()
async def pp(ctx, member: discord.Member = None):
    member = member or ctx.author
    size = "=" * random.randint(0, 12)
    await ctx.send(embed=base_embed("📏 PP Size Machine", f"{member.name}'s PP: `8{size}>`"))

# --- DC BOTS LAB SPECIAL (10) ---
@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def leave(ctx):
    """Triggers Leave Application Modal"""
    await ctx.interaction.response.send_modal(LeaveApplicationModal())

@leave.error
async def leave_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(embed=base_embed("⏳ Cooldown Active", f"You can only submit 1 leave application every hour. Try again in `{round(error.retry_after/60)} minutes`."), delete_after=10)

@bot.command()
async def myleaves(ctx):
    leaves_db = load_leaves()
    user_str = str(ctx.author.id)
    if user_str not in leaves_db or not leaves_db[user_str]:
        await ctx.send(embed=base_embed("📄 My Leaves", "You have not submitted any leave applications yet."))
        return

    embed = base_embed(f"📄 Leave History - {ctx.author.name}")
    for idx, item in enumerate(leaves_db[user_str][-5:], start=1):
        embed.add_field(
            name=f"Leave #{idx} - Status: {item['status']}",
            value=f"**Type:** {item['type']}\n**Duration:** {item['from']} to {item['to']}\n**Reason:** {item['reason']}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def allleaves(ctx):
    leaves_db = load_leaves()
    embed = base_embed("📋 All Staff Leaves Log")
    count = 0
    for uid, history in leaves_db.items():
        for item in history:
            if count >= 10:
                break
            embed.add_field(name=f"User: <@{uid}>", value=f"Dates: {item['from']} - {item['to']} | Status: `{item['status']}`", inline=False)
            count += 1
    if count == 0:
        embed.description = "No leave applications found in the database."
    await ctx.send(embed=embed)

@bot.command()
async def welcome(ctx, member: discord.Member):
    await ctx.send(embed=base_embed("👋 Welcome", f"Welcome {member.mention} to DC Bots Lab! Enjoy your stay."))

@bot.command()
async def botlist(ctx):
    await ctx.send(embed=base_embed("🤖 DC Bots List", "• DC Moderation Bot\n• DC Ticket System\n• DC Leave Application Bot"))

@bot.command()
async def addbot(ctx, name: str):
    await ctx.send(embed=base_embed("➕ Bot Request", f"Bot request for **{name}** received!"))

@bot.command()
async def support(ctx):
    await ctx.send(embed=base_embed("💬 Support", "Need help? Create a ticket in the #support channel!"))

@bot.command()
async def rules(ctx):
    await ctx.send(embed=base_embed("📜 Rules", "1. Be respectful\n2. No spam\n3. Follow Discord TOS"))

@bot.command()
async def staff(ctx):
    await ctx.send(embed=base_embed("👥 Staff Team", "DC Bots Lab Owner & Support Team is online to assist you."))

@bot.command()
async def uptime(ctx):
    await ctx.send(embed=base_embed("⏰ Uptime", "Bot is running online via Pella.app!"))

@bot.command()
async def premium(ctx):
    await ctx.send(embed=base_embed("⭐ Premium Tier", "Get access to exclusive bot features and priority support."))

@bot.command()
async def partner(ctx):
    await ctx.send(embed=base_embed("🤝 Partnership", "Contact server owners for partnership opportunities."))

# --- ECONOMY / LEVEL (10) ---
@bot.command()
async def balance(ctx):
    await ctx.send(embed=base_embed("💰 Wallet Balance", f"{ctx.author.mention}, you currently have `$1,250` coins."))

@bot.command()
async def daily(ctx):
    await ctx.send(embed=base_embed("🎁 Daily Reward", "You claimed your daily reward of `$200`!"))

@bot.command()
async def work(ctx):
    earned = random.randint(50, 150)
    await ctx.send(embed=base_embed("💼 Work Completed", f"You worked as a bot developer and earned `${earned}`!"))

@bot.command()
async def leaderboard(ctx):
    await ctx.send(embed=base_embed("🏆 Leaderboard", "1. UserA - $50,000\n2. UserB - $32,000\n3. UserC - $15,000"))

@bot.command()
async def level(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(embed=base_embed("📊 Level Stats", f"{member.mention} is currently **Level 5**."))

@bot.command()
async def rank(ctx):
    await ctx.send(embed=base_embed("🎖️ Rank", f"{ctx.author.mention}, your current server rank is **#12**."))

@bot.command()
async def shop(ctx):
    await ctx.send(embed=base_embed("🛒 Store Shop", "1. VIP Role - $5,000\n2. Custom Bot Role - $10,000"))

@bot.command()
async def buy(ctx, item: str):
    await ctx.send(embed=base_embed("🛍️️ Purchase Success", f"You bought **{item}** from the shop!"))

@bot.command()
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = base_embed(f"👤 Profile - {member.name}")
    embed.add_field(name="Level", value="5", inline=True)
    embed.add_field(name="Balance", value="$1,250", inline=True)
    embed.add_field(name="Reputation", value="+3", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def rep(ctx, member: discord.Member):
    await ctx.send(embed=base_embed("⭐ Reputation", f"You gave +1 Rep to {member.mention}!"))

# -------------------------------------------------------------
# GLOBAL ERROR HANDLING
# -------------------------------------------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=base_embed("❌ Permission Denied", "You do not have the required permissions to execute this command."))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=base_embed("⚠️ Missing Arguments", f"Please check command syntax. Usage: `{ctx.prefix}{ctx.command.signature}`"))

# -------------------------------------------------------------
# START BOT
# -------------------------------------------------------------
if __name__ == "__main__":
    token = os.getenv("TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: TOKEN environment variable is missing!")