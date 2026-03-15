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
import html
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

TOKEN      = os.getenv("DISCORD_TOKEN")
BANNER_URL = os.getenv("BANNER_URL", "")

# Salon de logs (transcriptions)
LOG_CHANNEL_ID = 1482544765114253365

# Catégories de tickets et rôles associés
TICKET_CONFIG = {
    "support": {
        "label":       "Support",
        "emoji":       "🛡️",
        "description": "Quelque chose ne fonctionne pas ? On est là",
        "color":       0x5865F2,
        "role_id":     1479606906308919387,
        "open_msg":    "Tu rencontres un problème général ? Notre équipe support est là pour t'aider.",
    },
    "purchase": {
        "label":       "Purchase",
        "emoji":       "🛒",
        "description": "Une question sur une commande ou un paiement ?",
        "color":       0x57F287,
        "role_id":     1479606902638776499,
        "open_msg":    "Tu as une question à propos d'une commande ou d'un paiement ? On arrive.",
    },
    "media": {
        "label":       "Media",
        "emoji":       "📸",
        "description": "Demande de collab ou de partenariat média ?",
        "color":       0xEB459E,
        "role_id":     1479606906308919387,
        "open_msg":    "Tu cherches à faire une collab ou un partenariat média ? Dis-nous en plus.",
    },
    "hwid_reset": {
        "label":       "HWID Reset",
        "emoji":       "🔄",
        "description": "Besoin d'un reset de ton HWID ?",
        "color":       0xFEE75C,
        "role_id":     1479606902638776499,
        "open_msg":    "Besoin d'un reset HWID ? Un membre du staff va t'aider sous peu.",
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
    """Returns (discord.File HTML transcript, message_count)."""

    messages = []
    async for msg in channel.history(limit=2000, oldest_first=True):
        messages.append(msg)

    opened_at = ticket["opened_at"].strftime("%d/%m/%Y %H:%M:%S UTC") if ticket else "N/A"
    now_str   = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    category  = TICKET_CONFIG.get(ticket["type"], {}) if ticket else {}
    cat_label = f"{category.get('emoji', '')} {category.get('label', 'N/A')}" if category else "N/A"
    user_name = f"<@{ticket['user_id']}>" if ticket else "N/A"

    # Build message rows HTML
    rows = []
    for msg in messages:
        if msg.author.bot and not msg.content and not msg.embeds:
            continue
        ts      = msg.created_at.strftime("%d/%m/%Y %H:%M")
        avatar  = str(msg.author.display_avatar.with_size(64).url)
        name    = html.escape(msg.author.display_name)
        is_bot  = msg.author.bot
        badge   = '<span class="badge">BOT</span>' if is_bot else ""
        content_parts = []
        if msg.content:
            content_parts.append(f'<p>{html.escape(msg.content)}</p>')
        for emb in msg.embeds:
            title = html.escape(emb.title or "")
            desc  = html.escape(emb.description or "")[:300]
            content_parts.append(
                f'<div class="embed" style="border-left:4px solid #{emb.color.value:06x if emb.color else "5865F2"}">'
                f'{"<strong>" + title + "</strong><br>" if title else ""}'
                f'{desc}</div>'
            )
        for att in msg.attachments:
            if att.content_type and att.content_type.startswith("image"):
                content_parts.append(f'<img class="attachment" src="{att.url}" alt="attachment">')
            else:
                content_parts.append(f'<a class="file-link" href="{att.url}">{html.escape(att.filename)}</a>')
        content_html = "\n".join(content_parts) if content_parts else '<p class="empty">[message vide]</p>'

        rows.append(f"""
        <div class="message">
          <img class="avatar" src="{avatar}" alt="">
          <div class="msg-body">
            <div class="msg-header">
              <span class="username {'bot-name' if is_bot else ''}">{name}</span>
              {badge}
              <span class="timestamp">{ts}</span>
            </div>
            <div class="msg-content">{content_html}</div>
          </div>
        </div>""")

    rows_html = "\n".join(rows)

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Transcript — {html.escape(channel.name)}</title>
  <style>
    :root {{
      --bg:        #1e1f22;
      --bg2:       #2b2d31;
      --bg3:       #313338;
      --accent:    #5865F2;
      --text:      #dcddde;
      --muted:     #949ba4;
      --border:    #3f4147;
      --bot-color: #5865F2;
      --success:   #57F287;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'gg sans', 'Noto Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    .header {{
      background: var(--bg2);
      border-bottom: 1px solid var(--border);
      padding: 20px 30px;
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .header-icon {{
      width: 48px; height: 48px;
      border-radius: 50%;
      background: var(--accent);
      display: flex; align-items: center; justify-content: center;
      font-size: 22px; flex-shrink: 0;
    }}
    .header-info h1 {{ font-size: 18px; font-weight: 700; color: #fff; }}
    .header-info p  {{ font-size: 13px; color: var(--muted); margin-top: 2px; }}
    .meta-bar {{
      background: var(--bg3);
      padding: 14px 30px;
      display: flex; flex-wrap: wrap; gap: 24px;
      border-bottom: 1px solid var(--border);
    }}
    .meta-item {{ display: flex; flex-direction: column; gap: 2px; }}
    .meta-label {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
                   letter-spacing: .5px; color: var(--muted); }}
    .meta-value {{ font-size: 14px; color: var(--text); }}
    .messages {{
      max-width: 1000px;
      margin: 0 auto;
      padding: 20px 30px;
    }}
    .message {{
      display: flex;
      gap: 14px;
      padding: 6px 0;
      border-radius: 4px;
      transition: background .1s;
    }}
    .message:hover {{ background: rgba(255,255,255,.03); }}
    .avatar {{
      width: 40px; height: 40px;
      border-radius: 50%;
      flex-shrink: 0;
      margin-top: 2px;
    }}
    .msg-body {{ flex: 1; min-width: 0; }}
    .msg-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }}
    .username {{ font-weight: 600; color: #fff; }}
    .bot-name {{ color: var(--bot-color); }}
    .badge {{
      background: var(--bot-color);
      color: #fff;
      font-size: 10px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 3px;
      letter-spacing: .3px;
    }}
    .timestamp {{ font-size: 11px; color: var(--muted); }}
    .msg-content p {{ color: var(--text); margin: 1px 0; word-break: break-word; }}
    .msg-content .empty {{ color: var(--muted); font-style: italic; }}
    .embed {{
      margin-top: 6px;
      background: var(--bg2);
      border-radius: 4px;
      padding: 10px 14px;
      max-width: 520px;
      font-size: 13px;
      color: var(--text);
    }}
    .attachment {{
      max-width: 400px;
      border-radius: 6px;
      margin-top: 6px;
    }}
    .file-link {{
      display: inline-block;
      margin-top: 6px;
      color: var(--accent);
      text-decoration: none;
    }}
    .file-link:hover {{ text-decoration: underline; }}
    .footer {{
      text-align: center;
      padding: 20px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="header-icon">🎟️</div>
    <div class="header-info">
      <h1>#{html.escape(channel.name)}</h1>
      <p>Delta Solutions — Transcription de ticket</p>
    </div>
  </div>
  <div class="meta-bar">
    <div class="meta-item">
      <span class="meta-label">Utilisateur</span>
      <span class="meta-value">{html.escape(str(ticket['user_id']) if ticket else 'N/A')}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Catégorie</span>
      <span class="meta-value">{html.escape(cat_label)}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Ouvert le</span>
      <span class="meta-value">{html.escape(opened_at)}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Généré le</span>
      <span class="meta-value">{html.escape(now_str)}</span>
    </div>
    <div class="meta-item">
      <span class="meta-label">Messages</span>
      <span class="meta-value">{len(messages)}</span>
    </div>
  </div>
  <div class="messages">
    {rows_html}
  </div>
  <div class="footer">Delta Solutions Ticket System — transcript généré automatiquement</div>
</body>
</html>"""

    file = discord.File(
        io.BytesIO(html_content.encode("utf-8")),
        filename=f"transcript-{channel.name}.html",
    )
    return file, len(messages)


# ─────────────────────────────────────────────────────────────────────────────
#  MODAL : RAISON DE FERMETURE
# ─────────────────────────────────────────────────────────────────────────────

class CloseReasonModal(discord.ui.Modal, title="Fermer le ticket"):
    reason = discord.ui.TextInput(
        label="Raison de fermeture (optionnel)",
        placeholder="Ex : Problème résolu, demande traitée…",
        required=False,
        max_length=300,
        style=discord.TextStyle.short,
    )

    def __init__(self, channel: discord.TextChannel, invoker: discord.Member):
        super().__init__()
        self._channel = channel
        self._invoker = invoker

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip() or "Aucune raison fournie"
        await interaction.response.send_message(
            f"🔒 Fermeture en cours… (**{reason_text}**)", ephemeral=True
        )
        await _do_close(self._channel, self._invoker, reason_text)

# ─────────────────────────────────────────────────────────────────────────────
#  LOGIQUE DE FERMETURE (partagée entre bouton et modal)
# ─────────────────────────────────────────────────────────────────────────────

async def _do_close(channel: discord.TextChannel, closer: discord.Member, reason: str):
    ticket   = open_tickets.get(channel.id)
    now      = datetime.now(timezone.utc)

    # Transcription HTML
    transcript, msg_count = await generate_transcript(channel, ticket)

    log_channel = channel.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        if ticket:
            config   = TICKET_CONFIG.get(ticket["type"], {})
            duration = _format_duration(now - ticket["opened_at"]) if ticket.get("opened_at") else "N/A"
            claimed  = f"<@{ticket['claimed_by']}>" if ticket.get("claimed_by") else "Non réclamé"

            log_embed = discord.Embed(
                title="🔒 Ticket Fermé",
                color=config.get("color", 0xFF0000),
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

            log_embed.add_field(name="👤 Utilisateur",  value=f"<@{ticket['user_id']}>", inline=True)
            log_embed.add_field(name="📂 Catégorie",    value=f"{config.get('emoji','')} {config.get('label','N/A')}", inline=True)
            log_embed.add_field(name="🙋 Pris en charge", value=claimed, inline=True)
            log_embed.add_field(name="🔒 Fermé par",    value=closer.mention, inline=True)
            log_embed.add_field(name="⏱️ Durée",        value=duration, inline=True)
            log_embed.add_field(name="💬 Messages",     value=str(msg_count), inline=True)
            log_embed.add_field(name="📅 Ouvert le",    value=f"<t:{int(ticket['opened_at'].timestamp())}:f>", inline=True)
            log_embed.add_field(name="📅 Fermé le",     value=f"<t:{int(now.timestamp())}:f>", inline=True)
            log_embed.add_field(name="📝 Raison",       value=reason, inline=False)
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")
        else:
            log_embed = discord.Embed(
                title="🔒 Ticket Fermé",
                description=f"Salon : `{channel.name}`\nFermé par {closer.mention}\nRaison : {reason}",
                color=0xFF0000,
                timestamp=now,
            )
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")

        await log_channel.send(embed=log_embed, file=transcript)

    open_tickets.pop(channel.id, None)
    _save_tickets(open_tickets)

    await channel.send("🔒 Ce ticket sera supprimé dans **5 secondes**…")
    await asyncio.sleep(5)
    await channel.delete(reason=f"Ticket fermé par {closer} — {reason}")


# ─────────────────────────────────────────────────────────────────────────────
#  VIEW : BOUTONS DU TICKET (persistants)
# ─────────────────────────────────────────────────────────────────────────────

class TicketControlView(discord.ui.View):
    """Boutons Claim, Notify et Fermer le ticket — persistants après redémarrage."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── ✋ Claim ────────────────────────────────────────────────────────────
    @discord.ui.button(
        label="Claim",
        emoji="✋",
        style=discord.ButtonStyle.primary,
        custom_id="ds_ticket_claim",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = open_tickets.get(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(
                "❌ Données du ticket introuvables.", ephemeral=True
            )
            return

        if ticket.get("claimed_by"):
            claimer = interaction.guild.get_member(ticket["claimed_by"])
            name    = claimer.display_name if claimer else f"<@{ticket['claimed_by']}>"
            await interaction.response.send_message(
                f"❌ Ce ticket est déjà pris en charge par **{name}**.", ephemeral=True
            )
            return

        ticket["claimed_by"] = interaction.user.id
        _save_tickets(open_tickets)

        config = TICKET_CONFIG.get(ticket["type"], {})
        embed  = discord.Embed(
            description=f"✋ **{interaction.user.display_name}** a pris en charge ce ticket.",
            color=config.get("color", 0x5865F2),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed)

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
                "❌ Données du ticket introuvables.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(ticket["user_id"])
        if not member:
            await interaction.response.send_message(
                "❌ Impossible de trouver le créateur du ticket.", ephemeral=True
            )
            return

        config = TICKET_CONFIG[ticket["type"]]
        embed  = discord.Embed(
            title="📬 Nouvelle réponse — Delta Solutions",
            description=(
                f"Hey {member.mention}, un membre du staff a répondu à ton ticket !\n\n"
                f"🎟️ Retourne dans ton ticket : {interaction.channel.mention}"
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
                f"✅ {member.mention} a été notifié par MP.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Impossible d'envoyer un MP (MPs désactivés côté utilisateur).",
                ephemeral=True,
            )

    # ── ✖️ Fermer le ticket ────────────────────────────────────────────────
    @discord.ui.button(
        label="Fermer le ticket",
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
            placeholder="Sélectionnez une option…",
            options=options,
            custom_id="ds_ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        key    = self.values[0]
        config = TICKET_CONFIG[key]
        guild  = interaction.guild
        user   = interaction.user

        # Vérification : ticket déjà ouvert ?
        for ch_id, data in list(open_tickets.items()):
            if data["user_id"] == user.id:
                ch = guild.get_channel(ch_id)
                if ch:
                    await interaction.response.send_message(
                        f"❌ Tu as déjà un ticket ouvert : {ch.mention}", ephemeral=True
                    )
                    return
                else:
                    # Salon supprimé manuellement, on nettoie
                    open_tickets.pop(ch_id, None)
                    _save_tickets(open_tickets)

        # Catégorie "Tickets" (création auto si absente)
        category = discord.utils.get(guild.categories, name="Tickets")
        if category is None:
            category = await guild.create_category("Tickets")

        role = guild.get_role(config["role_id"])

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
                f"Hey {user.mention}, merci de nous avoir contacté !\n\n"
                f"{config['open_msg']}"
            ),
            color=config["color"],
            timestamp=opened_at,
        )
        embed.add_field(
            name="📋 Instructions",
            value=(
                "• Décris ton problème **clairement et en détail**\n"
                "• Joins des **captures d'écran** si nécessaire\n"
                "• Sois patient, un membre du staff va t'aider rapidement"
            ),
            inline=False,
        )
        embed.add_field(name="👤 Utilisateur",  value=user.mention,                                   inline=True)
        embed.add_field(name="📂 Catégorie",    value=f"{config['emoji']} {config['label']}",         inline=True)
        embed.add_field(name="🔢 Ticket n°",    value=f"`#{ticket_number:04d}`",                      inline=True)
        embed.add_field(name="📅 Ouvert",       value=f"<t:{int(opened_at.timestamp())}:R>",          inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Delta Solutions — Support System")
        if BANNER_URL:
            embed.set_image(url=BANNER_URL)

        # Ping du rôle concerné + le créateur du ticket
        ping = role.mention if role else user.mention
        await channel.send(
            content=f"{ping} | {user.mention}",
            embed=embed,
            view=TicketControlView(),
        )

        await interaction.response.send_message(
            f"✅ Ton ticket a été créé : {channel.mention}", ephemeral=True
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
    description="Déployer le panel de tickets Delta Solutions dans ce salon",
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Hey, besoin d'aide ? 👋",
        description=(
            "Tu es au bon endroit.\n\n"
            "Que tu aies une question, un problème, ou juste besoin de parler à quelqu'un — "
            "notre équipe est disponible et prête à t'aider. Choisis l'option qui correspond "
            "à ta situation dans le menu ci-dessous et on sera là rapidement.\n\n"
            "**Avec quoi pouvons-nous t'aider ?**\n"
            "🛡️ **Support** — Quelque chose ne fonctionne pas ? On est là\n"
            "🔄 **HWID Reset** — Besoin d'un reset de ton HWID ?\n"
            "🛒 **Purchase** — Une question sur une commande ou un paiement ?\n"
            "📸 **Media** — Demande de collab ou de partenariat média ?\n\n"
            "**Avant d'ouvrir un ticket**\n"
            "Prends un moment pour vérifier que ta question n'est pas déjà répondue quelque part "
            "sur le serveur. Sinon — vas-y, on ne mord pas 😄"
        ),
        color=0x5865F2,
    )
    embed.set_footer(text="Delta Solutions — Support System")
    if BANNER_URL:
        embed.set_image(url=BANNER_URL)

    await interaction.channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message("✅ Panel de tickets déployé !", ephemeral=True)


@setup.error
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ Tu dois être **administrateur** pour utiliser cette commande.",
            ephemeral=True,
        )

# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /adduser
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="adduser",
    description="Ajouter un utilisateur au ticket actuel",
)
@app_commands.describe(member="Le membre à ajouter au ticket")
async def adduser(interaction: discord.Interaction, member: discord.Member):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    if interaction.channel.id not in open_tickets:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un salon de ticket.", ephemeral=True
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
        description=f"✅ {member.mention} a été ajouté au ticket par {interaction.user.mention}.",
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
    await interaction.response.send_message(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDE /removeuser
# ─────────────────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="removeuser",
    description="Retirer un utilisateur du ticket actuel",
)
@app_commands.describe(member="Le membre à retirer du ticket")
async def removeuser(interaction: discord.Interaction, member: discord.Member):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    ticket = open_tickets.get(interaction.channel.id)
    if not ticket:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un salon de ticket.", ephemeral=True
        )
        return

    if member.id == ticket["user_id"]:
        await interaction.response.send_message(
            "❌ Impossible de retirer le créateur du ticket.", ephemeral=True
        )
        return

    await interaction.channel.set_permissions(member, overwrite=None)

    embed = discord.Embed(
        description=f"🚫 {member.mention} a été retiré du ticket par {interaction.user.mention}.",
        color=0xED4245,
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

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "❌ Seul l'auteur de la commande peut confirmer.", ephemeral=True
            )
            return

        self.stop()
        await interaction.response.edit_message(
            content="⏳ Fermeture de tous les tickets en cours…", view=None
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
                title="🗑️ Fermeture massive de tickets",
                description=(
                    f"**{closed}** ticket(s) supprimé(s)\n"
                    f"**{failed}** échec(s)\n\n"
                    f"Exécuté par {interaction.user.mention}"
                ),
                color=0xED4245,
                timestamp=datetime.now(timezone.utc),
            )
            log_embed.set_footer(text="Delta Solutions — Ticket Logs")
            await log_channel.send(embed=log_embed)

        await interaction.followup.send(
            f"✅ **{closed}** ticket(s) fermé(s){f', {failed} erreur(s)' if failed else ''}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ Annulé.", view=None)


@bot.tree.command(
    name="closeall",
    description="Fermer et supprimer TOUS les tickets ouverts",
)
async def closeall(interaction: discord.Interaction):
    if not _has_staff_role(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    count = len(open_tickets)
    if count == 0:
        await interaction.response.send_message(
            "ℹ️ Aucun ticket ouvert en ce moment.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⚠️ Tu es sur le point de fermer **{count}** ticket(s). Cette action est **irréversible**.",
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
