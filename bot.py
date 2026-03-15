"""
╔══════════════════════════════════════════════════════════════╗
║             DELTA SOLUTIONS — TICKET BOT                     ║
║                   Powered by discord.py                      ║
╠══════════════════════════════════════════════════════════════╣
║  Variables d'environnement à configurer dans Railway :       ║
║    DISCORD_TOKEN  — Token du bot Discord                     ║
║    BANNER_URL     — URL de la bannière affichée en ticket    ║
╚══════════════════════════════════════════════════════════════╝
"""

import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import json
import io
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TOKEN      = os.getenv("DISCORD_TOKEN")
BANNER_URL = os.getenv("BANNER_URL", "")

# Couleur unique des embeds (barre latérale Discord)
EMBED_COLOR = 0xFF0000

# Salon de logs (transcriptions)
LOG_CHANNEL_ID = 1482544765114253365

# Catégories de tickets et rôles associés
TICKET_CONFIG = {
    "support": {
        "label":         "Support",
        "emoji":         "🛡️",
        "description":   "Something not working? We got you",
        "color":         EMBED_COLOR,
        "role_id":       1479606906308919387,
        "open_msg":      "Having a general issue? Our support team is here to help you.",
        "category_name": "Support",
    },
    "purchase": {
        "label":         "Purchase",
        "emoji":         "🛒",
        "description":   "Question about an order or payment?",
        "color":         EMBED_COLOR,
        "role_id":       1479606902638776499,
        "open_msg":      "Got a question about an order or a payment? We're on it.",
        "category_name": "Purchase",
    },
    "media": {
        "label":         "Media",
        "emoji":         "📸",
        "description":   "Collab or media partnership request?",
        "color":         EMBED_COLOR,
        "role_id":       1479606906308919387,
        "open_msg":      "Looking for a collab or media partnership? Tell us more.",
        "category_name": "Media",
    },
    "hwid_reset": {
        "label":         "HWID Reset",
        "emoji":         "🔄",
        "description":   "Need your HWID reset?",
        "color":         EMBED_COLOR,
        "role_id":       1479606902638776499,
        "open_msg":      "Need a HWID reset? A staff member will assist you shortly.",
        "category_name": "HWID Reset",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  PERSISTANCE DES TICKETS (fichier JSON)
# ─────────────────────────────────────────────────────────────────────────────

TICKETS_FILE = "tickets.json"


def _load_tickets() -> dict:
    if not os.path.exists(TICKETS_FILE):
        return {}
    try:
        with open(TICKETS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        result = {}
        for k, v in raw.items():
            result[int(k)] = {
                "user_id":    v["user_id"],
                "type":       v["type"],
                "opened_at":  datetime.fromisoformat(v["opened_at"]),
                "number":     v.get("number", 0),
                "claimed_by": v.get("claimed_by"),
            }
        return result
    except Exception:
        return {}


def _save_tickets(tickets: dict) -> None:
    serializable = {
        str(ch_id): {
            "user_id":    d["user_id"],
            "type":       d["type"],
            "opened_at":  d["opened_at"].isoformat(),
            "number":     d.get("number", 0),
            "claimed_by": d.get("claimed_by"),
        }
        for ch_id, d in tickets.items()
    }
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


COUNTER_FILE = "ticket_counter.json"


def _next_ticket_number() -> int:
    count = 1
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r", encoding="utf-8") as f:
                count = json.load(f).get("count", 0) + 1
        except Exception:
            count = 1
    with open(COUNTER_FILE, "w", encoding="utf-8") as f:
        json.dump({"count": count}, f)
    return count


open_tickets: dict = _load_tickets()

# Verrou anti-doublon : user IDs en cours de création de ticket
_pending_users: set[int] = set()

# ─────────────────────────────────────────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────────────────────────────────────
#  GÉNÉRATION DE TRANSCRIPTION HTML
# ─────────────────────────────────────────────────────────────────────────────

def _format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m {s}s"
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


async def generate_transcript(
    channel: discord.TextChannel,
    ticket: dict | None = None,
) -> tuple[discord.File, int]:
    """Returns (discord.File TXT transcript, message_count)."""

    messages = []
    async for msg in channel.history(limit=2000, oldest_first=True):
        messages.append(msg)

    now_str   = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    opened_at = ticket["opened_at"].strftime("%d/%m/%Y %H:%M:%S UTC") if ticket else "N/A"
    category  = TICKET_CONFIG.get(ticket["type"], {}) if ticket else {}
    cat_label = f"{category.get('label', 'N/A')}" if category else "N/A"

    sep  = "═" * 60
    sep2 = "─" * 60

    lines = [
        sep,
        "       DELTA SOLUTIONS — Ticket Transcript",
        sep,
        f"  Channel  : #{channel.name}",
        f"  Category : {cat_label}",
        f"  User     : {ticket['user_id'] if ticket else 'N/A'}",
        f"  Opened   : {opened_at}",
        f"  Exported : {now_str}",
        sep,
        "",
    ]

    for msg in messages:
        # Skip empty bot system messages
        if msg.author.bot and not msg.content and not msg.embeds and not msg.attachments:
            continue

        ts     = msg.created_at.strftime("%d/%m/%Y %H:%M:%S")
        author = f"{msg.author.display_name}{'  [BOT]' if msg.author.bot else ''}"
        lines.append(f"[{ts}]  {author}")

        if msg.content:
            for text_line in msg.content.splitlines():
                lines.append(f"    {text_line}")

        for emb in msg.embeds:
            if emb.title:
                lines.append(f"    [Embed] {emb.title}")
            if emb.description:
                short = emb.description[:300].replace("\n", " ")
                lines.append(f"    {short}")

        for att in msg.attachments:
            lines.append(f"    [Attachment] {att.url}")

        lines.append(sep2)

    lines.append("")
    lines.append("Delta Solutions Ticket System — auto-generated transcript")

    raw = "\n".join(lines).encode("utf-8")
    file = discord.File(
        io.BytesIO(raw),
        filename=f"transcript-{channel.name}.txt",
    )
    return file, len(messages)


# ─────────────────────────────────────────────────────────────────────────────
#  MODAL : RAISON DE FERMETURE
# ─────────────────────────────────────────────────────────────────────────────

class CloseReasonModal(discord.ui.Modal, title="Close Ticket"):
    reason = discord.ui.TextInput(
        label="Reason for closing (optional)",
        placeholder="e.g. Issue resolved, request handled…",
        required=False,
        max_length=300,
        style=discord.TextStyle.short,
    )

    def __init__(self, channel: discord.TextChannel, invoker: discord.Member):
        super().__init__()
        self._channel = channel
        self._invoker = invoker

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip() or "No reason provided"
        await interaction.response.send_message(
            f"🔒 Closing ticket… (**{reason_text}**)", ephemeral=True
        )
        await _do_close(self._channel, self._invoker, reason_text)

# ─────────────────────────────────────────────────────────────────────────────
#  LOGIQUE DE FERMETURE (partagée entre bouton et modal)
# ─────────────────────────────────────────────────────────────────────────────

async def _do_close(channel: discord.TextChannel, closer: discord.Member, reason: str):
    ticket   = open_tickets.get(channel.id)
    now      = datetime.now(timezone.utc)

    # Generate transcript twice (discord.File is single-use)
    transcript_log, msg_count = await generate_transcript(channel, ticket)
    transcript_dm,  _         = await generate_transcript(channel, ticket)

    log_channel = channel.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        if ticket:
            config   = TICKET_CONFIG.get(ticket["type"], {})
            duration = _format_duration(now - ticket["opened_at"]) if ticket.get("opened_at") else "N/A"
            claimed  = f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "Unclaimed"

            log_embed = discord.Embed(
                title="🔒 Ticket Closed",
                color=config.get("color", EMBED_COLOR),
                timestamp=now,
            )
            log_embed.set_author(
                name=f"Ticket #{ticket.get('number', '?')} — {config.get('label', 'N/A')}",
                icon_url=channel.guild.icon.url if channel.guild.icon else discord.Embed.Empty,
            )
            # Fetch user avatar for thumbnail
            user = channel.guild.get_member(ticket["user_id"])
            if user:
                log_embed.set_thumbnail(url=user.display_avatar.url)

            log_embed.add_field(name="👤 User",       value=f"<@{ticket['user_id']}>", inline=True)
            log_embed.add_field(name="📂 Category",    value=f"{config.get('emoji','')} {config.get('label','N/A')}", inline=True)
            log_embed.add_field(name="🙋 Claimed by",  value=claimed, inline=True)
            log_embed.add_field(name="🔒 Closed by",   value=closer.mention, inline=True)
            log_embed.add_field(name="⏱️ Duration",    value=duration, inline=True)
            log_embed.add_field(name="💬 Messages",    value=str(msg_count), inline=True)
            log_embed.add_field(name="📅 Opened",      value=f"<t:{int(ticket['opened_at'].timestamp())}:f>", inline=True)
            log_embed.add_field(name="📅 Closed",      value=f"<t:{int(now.timestamp())}:f>", inline=True)
            log_embed.add_field(name="📝 Reason",      value=reason, inline=False)
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")
        else:
            log_embed = discord.Embed(
                title="🔒 Ticket Closed",
                description=f"Channel: `{channel.name}`\nClosed by {closer.mention}\nReason: {reason}",
                color=EMBED_COLOR,
                timestamp=now,
            )
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")

        await log_channel.send(embed=log_embed, file=transcript_log)

    # Send transcript DM to the ticket creator
    if ticket:
        ticket_user = channel.guild.get_member(ticket["user_id"])
        if ticket_user:
            config = TICKET_CONFIG.get(ticket["type"], {})
            dm_embed = discord.Embed(
                title="🔒 Your ticket has been closed",
                description=(
                    f"Your **{config.get('label', '')}** ticket (`#{ticket.get('number', '?'):04d}`) "
                    f"has been closed.\n\n"
                    f"📝 **Reason:** {reason}\n\n"
                    f"The transcript of your conversation is attached below."
                ),
                color=config.get("color", EMBED_COLOR),
                timestamp=now,
            )
            dm_embed.set_footer(text="Delta Solutions — Support System")
            if BANNER_URL:
                dm_embed.set_image(url=BANNER_URL)
            try:
                await ticket_user.send(embed=dm_embed, file=transcript_dm)
            except discord.Forbidden:
                pass  # User has DMs disabled — silently skip

    open_tickets.pop(channel.id, None)
    _save_tickets(open_tickets)

    await channel.send("🔒 This ticket will be deleted in **5 seconds**…")
    await asyncio.sleep(5)
    await channel.delete(reason=f"Ticket closed by {closer} — {reason}")


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW : BOUTONS DU TICKET (persistants)
# ─────────────────────────────────────────────────────────────────────────────

class TicketControlView(discord.ui.View):
    """Boutons Notify et Close Ticket — persistants après redémarrage."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── 🔔 Notify ──────────────────────────────────────────────────────────
    @discord.ui.button(
        label="Notify",
        emoji="🔔",
        style=discord.ButtonStyle.secondary,
        custom_id="ds_ticket_notify",
    )
    async def notify(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = open_tickets.get(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(
                "❌ Ticket data not found.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(ticket["user_id"])
        if not member:
            await interaction.response.send_message(
                "❌ Could not find the ticket creator.", ephemeral=True
            )
            return

        config = TICKET_CONFIG[ticket["type"]]
        embed  = discord.Embed(
            title="📬 New Reply — Delta Solutions",
            description=(
                f"Hey {member.mention}, a staff member has replied to your ticket!\n\n"
                f"🎟️ Go back to your ticket: {interaction.channel.mention}"
            ),
            color=config["color"],
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Delta Solutions — Support")
        if BANNER_URL:
            embed.set_image(url=BANNER_URL)

        try:
            await member.send(embed=embed)
            await interaction.response.send_message(
                f"✅ {member.mention} has been notified by DM.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Could not send a DM (user has DMs disabled).",
                ephemeral=True,
            )

    # ── ✖️ Fermer le ticket ────────────────────────────────────────────────
    @discord.ui.button(
        label="Close Ticket",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        custom_id="ds_ticket_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CloseReasonModal(channel=interaction.channel, invoker=interaction.user)
        await interaction.response.send_modal(modal)

# ─────────────────────────────────────────────────────────────────────────────
#  VIEW : PANEL PRINCIPAL (dropdown + persistant)
# ─────────────────────────────────────────────────────────────────────────────

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=cfg["label"],
                value=key,
                emoji=cfg["emoji"],
                description=cfg["description"],
            )
            for key, cfg in TICKET_CONFIG.items()
        ]
        super().__init__(
            placeholder="Select an option…",
            options=options,
            custom_id="ds_ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        key    = self.values[0]
        config = TICKET_CONFIG[key]
        guild  = interaction.guild
        user   = interaction.user

        # Verrou anti-doublon : évite la race condition sur double-clic
        if user.id in _pending_users:
            await interaction.response.send_message(
                "⏳ Your ticket is already being created, please wait a moment…", ephemeral=True
            )
            return
        _pending_users.add(user.id)

        try:
            await self._create_ticket(interaction, key, config, guild, user)
        finally:
            _pending_users.discard(user.id)

    async def _create_ticket(self, interaction, key, config, guild, user):
        # Vérification : ticket déjà ouvert ?
        for ch_id, data in list(open_tickets.items()):
            if data["user_id"] == user.id:
                ch = guild.get_channel(ch_id)
                if ch:
                    await interaction.response.send_message(
                        f"❌ You already have an open ticket: {ch.mention}", ephemeral=True
                    )
                    return
                else:
                    # Channel deleted manually, clean up
                    open_tickets.pop(ch_id, None)
                    _save_tickets(open_tickets)

        # Catégorie propre à chaque type de ticket (création auto si absente)
        cat_name = config["category_name"]
        category = discord.utils.get(guild.categories, name=cat_name)
        role     = guild.get_role(config["role_id"])
        if category is None:
            cat_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
            }
            if role:
                cat_overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                )
            category = await guild.create_category(cat_name, overwrites=cat_overwrites)

        # Permissions du salon
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )

        ticket_number = _next_ticket_number()
        channel_name = (
            f"ticket-{ticket_number:04d}-{config['label'].lower().replace(' ', '-')}"
        )
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket {config['label']} ouvert par {user}",
        )

        opened_at = datetime.now(timezone.utc)
        open_tickets[channel.id] = {
            "user_id":    user.id,
            "type":       key,
            "opened_at":  opened_at,
            "number":     ticket_number,
            "claimed_by": None,
        }
        _save_tickets(open_tickets)

        # Embed d'ouverture
        embed = discord.Embed(
            title=f"{config['emoji']} {config['label']} Ticket",
            description=(
                f"Hey {user.mention}, thanks for reaching out!\n\n"
                f"{config['open_msg']}"
            ),
            color=config["color"],
            timestamp=opened_at,
        )
        embed.add_field(
            name="📋 Instructions",
            value=(
                "• Describe your issue **clearly and in detail**\n"
                "• Attach **screenshots** if relevant\n"
                "• Be patient, a staff member will assist you shortly"
            ),
            inline=False,
        )
        embed.add_field(name="👤 User",         value=user.mention,                                   inline=True)
        embed.add_field(name="📂 Category",     value=f"{config['emoji']} {config['label']}",         inline=True)
        embed.add_field(name="🔢 Ticket #",     value=f"`#{ticket_number:04d}`",                      inline=True)
        embed.add_field(name="📅 Opened",       value=f"<t:{int(opened_at.timestamp())}:R>",          inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Delta Solutions — Support System")
        if BANNER_URL:
            embed.set_image(url=BANNER_URL)

        # Ping the relevant role + ticket creator
        ping = role.mention if role else user.mention
        await channel.send(
            content=f"{ping} | {user.mention}",
            embed=embed,
            view=TicketControlView(),
        )

        await interaction.response.send_message(
            f"✅ Your ticket has been created: {channel.mention}", ephemeral=True
        )


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# Rôle autorisé à utiliser les commandes staff
STAFF_ROLE_ID = 1479606906308919387


def _has_staff_role(interaction: discord.Interaction) -> bool:
    return any(r.id == STAFF_ROLE_ID for r in interaction.user.roles)


# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /setup
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="setup",
    description="Deploy the Delta Solutions ticket panel in this channel",
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Hey, need help? 👋",
        description=(
            "You're in the right place.\n\n"
            "Whether you've got a question, an issue, or just need someone to talk to — "
            "our team is around and ready to help. Just pick the option that fits your "
            "situation in the menu below and we'll be with you shortly.\n\n"
            "**What can we help you with?**\n"
            "🛡️ **Support** — Something's not working? We got you\n"
            "🔄 **HWID Reset** — Need your HWID reset?\n"
            "🛒 **Purchase** — Question about an order or payment?\n"
            "📸 **Media** — Collab or media related request?\n\n"
            "**Before you open a ticket**\n"
            "Take a moment to make sure your question isn't already answered somewhere "
            "on the server. If not — go ahead, we don't bite 😄"
        ),
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Delta Solutions — Support System")
    if BANNER_URL:
        embed.set_image(url=BANNER_URL)

    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("✅ Ticket panel deployed!", ephemeral=True)


@setup.error
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need to be an **administrator** to use this command.",
            ephemeral=True,
        )

# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /adduser
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="adduser",
    description="Add a user to the current ticket",
)
@app_commands.describe(member="The member to add to the ticket")
async def adduser(interaction: discord.Interaction, member: discord.Member):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True
        )
        return

    if interaction.channel.id not in open_tickets:
        await interaction.response.send_message(
            "❌ This command must be used inside a ticket channel.", ephemeral=True
        )
        return

    await interaction.channel.set_permissions(
        member,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True,
    )

    embed = discord.Embed(
        description=f"✅ {member.mention} has been added to the ticket by {interaction.user.mention}.",
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /removeuser
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="removeuser",
    description="Remove a user from the current ticket",
)
@app_commands.describe(member="The member to remove from the ticket")
async def removeuser(interaction: discord.Interaction, member: discord.Member):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True
        )
        return

    ticket = open_tickets.get(interaction.channel.id)
    if not ticket:
        await interaction.response.send_message(
            "❌ This command must be used inside a ticket channel.", ephemeral=True
        )
        return

    if member.id == ticket["user_id"]:
        await interaction.response.send_message(
            "❌ Cannot remove the ticket creator.", ephemeral=True
        )
        return

    await interaction.channel.set_permissions(member, overwrite=None)

    embed = discord.Embed(
        description=f"🚫 {member.mention} has been removed from the ticket by {interaction.user.mention}.",
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /closeall
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmCloseAllView(discord.ui.View):
    def __init__(self, invoker_id: int):
        super().__init__(timeout=30)
        self.invoker_id = invoker_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "❌ Only the command author can confirm this.", ephemeral=True
            )
            return

        self.stop()
        await interaction.response.edit_message(
            content="⏳ Closing all tickets…", view=None
        )

        guild           = interaction.guild
        ticket_ids      = list(open_tickets.keys())
        closed, failed  = 0, 0

        for ch_id in ticket_ids:
            channel = guild.get_channel(ch_id)
            if channel:
                try:
                    open_tickets.pop(ch_id, None)
                    await channel.delete(reason=f"Closeall par {interaction.user}")
                    closed += 1
                except Exception:
                    failed += 1
            else:
                open_tickets.pop(ch_id, None)

        _save_tickets(open_tickets)

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title="🗑️ Mass Ticket Closure",
                description=(
                    f"**{closed}** ticket(s) deleted\n"
                    f"**{failed}** failure(s)\n\n"
                    f"Executed by {interaction.user.mention}"
                ),
                color=EMBED_COLOR,
                timestamp=datetime.now(timezone.utc),
            )
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")
            await log_channel.send(embed=log_embed)

        await interaction.followup.send(
            f"✅ **{closed}** ticket(s) closed{f', {failed} error(s)' if failed else ''}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)


@bot.tree.command(
    name="closeall",
    description="Close and delete ALL open tickets",
)
async def closeall(interaction: discord.Interaction):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True
        )
        return

    count = len(open_tickets)
    if count == 0:
        await interaction.response.send_message(
            "ℹ️ No open tickets at the moment.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⚠️ You are about to close **{count}** ticket(s). This action is **irreversible**.",
        view=ConfirmCloseAllView(invoker_id=interaction.user.id),
        ephemeral=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
#  ÉVÉNEMENTS DU BOT
# ─────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    # Enregistrement des vues persistantes (survient après redémarrage)
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())

    try:
        synced = await bot.tree.sync()
        print(f"✅  {len(synced)} commande(s) slash synchronisée(s)")
    except Exception as e:
        print(f"⚠️   Erreur synchronisation commandes : {e}")

    print(f"🚀  Delta Solutions Ticket Bot connecté — {bot.user} (ID: {bot.user.id})")
    print(f"📋  {len(TICKET_CONFIG)} catégories de tickets chargées")
    print(f"🎟️   {len(open_tickets)} ticket(s) actif(s) restauré(s) depuis la sauvegarde")

# ─────────────────────────────────────────────────────────────────────────────
#  DÉMARRAGE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "❌  DISCORD_TOKEN manquant ! "
            "Ajoutez la variable d'environnement DISCORD_TOKEN dans Railway."
        )
    bot.run(TOKEN)
