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
from datetime import datetime, timezone

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
        return {
            int(k): {
                "user_id":   v["user_id"],
                "type":      v["type"],
                "opened_at": datetime.fromisoformat(v["opened_at"]),
            }
            for k, v in raw.items()
        }
    except Exception:
        return {}


def _save_tickets(tickets: dict) -> None:
    serializable = {
        str(ch_id): {
            "user_id":   d["user_id"],
            "type":      d["type"],
            "opened_at": d["opened_at"].isoformat(),
        }
        for ch_id, d in tickets.items()
    }
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


open_tickets: dict = _load_tickets()

# ─────────────────────────────────────────────────────────────────────────────
#  BOT
# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────────────────────────────────────
#  GÉNÉRATION DE TRANSCRIPTION
# ─────────────────────────────────────────────────────────────────────────────

async def generate_transcript(channel: discord.TextChannel) -> discord.File:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
    lines = [
        "═══════════════════════════════════════════════════",
        "       DELTA SOLUTIONS — Transcription ticket",
        f"  Salon   : #{channel.name}",
        f"  Généré  : {now}",
        "═══════════════════════════════════════════════════\n",
    ]

    async for msg in channel.history(limit=1000, oldest_first=True):
        ts      = msg.created_at.strftime("%d/%m/%Y %H:%M:%S")
        content = msg.content or ""
        for embed in msg.embeds:
            if embed.title:
                content += f" [EMBED: {embed.title}]"
            if embed.description:
                content += f" — {embed.description[:120]}"
        for att in msg.attachments:
            content += f" [FICHIER: {att.url}]"
        lines.append(f"[{ts}] {msg.author.display_name} ({msg.author.id}): {content}")

    raw = "\n".join(lines).encode("utf-8")
    return discord.File(io.BytesIO(raw), filename=f"transcript-{channel.name}.txt")

# ─────────────────────────────────────────────────────────────────────────────
#  VIEW : BOUTONS DU TICKET (persistants)
# ─────────────────────────────────────────────────────────────────────────────

class TicketControlView(discord.ui.View):
    """Boutons Notify et Fermer le ticket — persistants après redémarrage."""

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
        embed = discord.Embed(
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
        channel = interaction.channel
        ticket  = open_tickets.get(channel.id)

        await interaction.response.defer()

        # Génération de la transcription
        transcript = await generate_transcript(channel)

        # Envoi dans le salon de logs
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            if ticket:
                config = TICKET_CONFIG.get(ticket["type"], {})
                log_embed = discord.Embed(
                    title="🔒 Ticket Fermé",
                    color=config.get("color", 0xFF0000),
                    timestamp=datetime.now(timezone.utc),
                )
                log_embed.add_field(
                    name="👤 Utilisateur",
                    value=f"<@{ticket['user_id']}>",
                    inline=True,
                )
                log_embed.add_field(
                    name="📂 Catégorie",
                    value=f"{config.get('emoji', '')} {config.get('label', 'N/A')}",
                    inline=True,
                )
                log_embed.add_field(
                    name="🔒 Fermé par",
                    value=interaction.user.mention,
                    inline=True,
                )
                log_embed.add_field(
                    name="📅 Ouvert le",
                    value=ticket["opened_at"].strftime("%d/%m/%Y %H:%M:%S"),
                    inline=True,
                )
                log_embed.add_field(
                    name="📅 Fermé le",
                    value=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S"),
                    inline=True,
                )
                log_embed.set_footer(text="Delta Solutions — Ticket Logs")
            else:
                log_embed = discord.Embed(
                    title="🔒 Ticket Fermé",
                    description=f"Salon : `{channel.name}`\nFermé par {interaction.user.mention}",
                    color=0xFF0000,
                    timestamp=datetime.now(timezone.utc),
                )
                log_embed.set_footer(text="Delta Solutions — Ticket Logs")

            await log_channel.send(embed=log_embed, file=transcript)

        # Suppression des données de persistance
        open_tickets.pop(channel.id, None)
        _save_tickets(open_tickets)

        await channel.send("🔒 Ce ticket sera supprimé dans **5 secondes**…")
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket fermé par {interaction.user}")

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

        channel_name = (
            f"ticket-{config['label'].lower().replace(' ', '-')}-{user.name.lower()}"
        )
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket {config['label']} ouvert par {user}",
        )

        opened_at = datetime.now(timezone.utc)
        open_tickets[channel.id] = {
            "user_id":   user.id,
            "type":      key,
            "opened_at": opened_at,
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
        embed.add_field(name="👤 Utilisateur", value=user.mention,                                    inline=True)
        embed.add_field(name="📂 Catégorie",   value=f"{config['emoji']} {config['label']}",          inline=True)
        embed.add_field(name="📅 Ouvert",      value=f"<t:{int(opened_at.timestamp())}:R>",           inline=True)
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
