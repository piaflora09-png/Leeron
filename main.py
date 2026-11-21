import os
import re
import threading
from datetime import datetime, timezone
import discord
from discord import app_commands, ui
from flask import Flask, send_from_directory

# ==========================================
# CONFIGURATION (RENDER ENV VARS OR FALLBACKS)
# ==========================================
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
GUILD_ID = int(os.getenv("GUILD_ID", "1514779623492288623"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "1514797762607054918"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "1514779623937015838"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1573660684343054356"))
PORT = int(os.getenv("PORT", "8080"))

TICKET_CONFIG = {
    "order": {
        "label": "Order Issue",
        "emoji": "🛒",
        "description": "Problem with your purchase",
        "style": discord.ButtonStyle.primary,
        "accent": 0x38BDF8,
        "prefix": "order",
        "field_1_label": "Order ID / Receipt Reference",
        "field_1_placeholder": "e.g. ORD-94821 or payment transaction ID",
        "field_2_label": "What Went Wrong With Your Order?",
        "field_2_placeholder": "Describe the item bought, amount, and issue...",
    },
    "middleman": {
        "label": "Middleman Request",
        "emoji": "🤝",
        "description": "Need a trusted middleman",
        "style": discord.ButtonStyle.success,
        "accent": 0xA855F7,
        "prefix": "mm",
        "field_1_label": "Trade Items & Other Trader (@user / ID)",
        "field_1_placeholder": "Items/currency involved and trader username or ID",
        "field_2_label": "Agreed Terms & Notes",
        "field_2_placeholder": "List agreed terms, rules, or any special notes...",
    },
    "report": {
        "label": "Report a User",
        "emoji": "⚠️",
        "description": "Report rule violations",
        "style": discord.ButtonStyle.danger,
        "accent": 0xEF4444,
        "prefix": "report",
        "field_1_label": "Reported User (Username or ID)",
        "field_1_placeholder": "Who are you reporting?",
        "field_2_label": "Violation & Evidence Links",
        "field_2_placeholder": "Explain the rule break and paste proof links...",
    },
    "general": {
        "label": "General Support",
        "emoji": "❓",
        "description": "Any other questions",
        "style": discord.ButtonStyle.secondary,
        "accent": 0x8B5CF6,
        "prefix": "support",
        "field_1_label": "Topic / Question Summary",
        "field_1_placeholder": "What is your question about?",
        "field_2_label": "Details",
        "field_2_placeholder": "Write your question or request clearly...",
    },
}

# ==========================================
# FLASK WEB SERVER (SERVES INDEX.HTML & HEALTH)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)


@app.route("/")
def serve_index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "online", "bot": "V2 Ticket System"}, 200


def run_web_server():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)


# ==========================================
# STATE PARSING HELPERS FOR V2 CARDS
# ==========================================
def extract_ticket_state_from_message(message: discord.Message) -> tuple[str, str, list[int]]:
    """Extracts field_1, field_2, and confirmed user IDs from an existing V2 ticket card."""
    f1_val = "See details above"
    f2_val = "See details above"
    confirmed_ids: list[int] = []

    for item in message.components:
        if isinstance(item, ui.Container):
            for child in item.children:
                if isinstance(child, ui.TextDisplay):
                    text = child.content
                    if "**Confirmations:**" in text:
                        found = re.findall(r"`(\d+)`", text.split("**Confirmations:**", 1)[1])
                        for uid_str in found:
                            uid = int(uid_str)
                            if uid not in confirmed_ids:
                                confirmed_ids.append(uid)
                    elif "**" in text and "\n\n" in text:
                        blocks = text.split("\n\n", 1)
                        b1 = blocks[0].split("\n", 1)
                        b2 = blocks[1].split("\n", 1)
                        if len(b1) == 2:
                            f1_val = b1[1]
                        if len(b2) == 2:
                            f2_val = b2[1]

    return f1_val, f2_val, confirmed_ids


# ==========================================
# COMPONENTS V2 BUILDERS
# ==========================================
def build_panel_layout() -> ui.LayoutView:
    """Main V2 ticket panel with Container, TextDisplay, Separator, and ActionRows."""
    view = ui.LayoutView(timeout=None)

    container = ui.Container(accent_color=0x7C3AED)
    container.add_item(
        ui.TextDisplay(
            "# 🎫 Ticket & Middleman Desk\n"
            "Click a button below to open a private ticket. Fill out the form so our team can help right away."
        )
    )
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    container.add_item(
        ui.TextDisplay(
            "🛒 **Order Issue** — Problem with your purchase\n"
            "🤝 **Middleman Request** — Need a trusted middleman\n"
            "⚠️ **Report a User** — Report rule violations\n"
            "❓ **General Support** — Any other questions"
        )
    )
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    row_top = ui.ActionRow(
        ui.Button(
            label="Order Issue",
            emoji="🛒",
            style=discord.ButtonStyle.primary,
            custom_id="v2_ticket_open:order",
        ),
        ui.Button(
            label="Middleman Request",
            emoji="🤝",
            style=discord.ButtonStyle.success,
            custom_id="v2_ticket_open:middleman",
        ),
    )
    row_bottom = ui.ActionRow(
        ui.Button(
            label="Report a User",
            emoji="⚠️",
            style=discord.ButtonStyle.danger,
            custom_id="v2_ticket_open:report",
        ),
        ui.Button(
            label="General Support",
            emoji="❓",
            style=discord.ButtonStyle.secondary,
            custom_id="v2_ticket_open:general",
        ),
    )

    container.add_item(row_top)
    container.add_item(row_bottom)
    view.add_item(container)
    return view


def build_ticket_welcome_layout(
    category_key: str,
    opener: discord.Member,
    field_1_value: str,
    field_2_value: str,
    claimed_by: discord.Member | None = None,
    confirmed_ids: list[int] | None = None,
) -> ui.LayoutView:
    """V2 welcome card inside a newly created ticket channel."""
    cfg = TICKET_CONFIG[category_key]
    confirmed_ids = confirmed_ids or []
    view = ui.LayoutView(timeout=None)

    status_text = (
        f"Claimed by {claimed_by.mention}"
        if claimed_by
        else "Open — Waiting for Staff"
    )

    container = ui.Container(accent_color=cfg["accent"])
    container.add_item(
        ui.TextDisplay(
            f"# {cfg['emoji']} {cfg['label']} Ticket\n"
            f"**Opened By:** {opener.mention} (`{opener.id}`)\n"
            f"**Status:** {status_text}"
        )
    )
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    container.add_item(
        ui.TextDisplay(
            f"**{cfg['field_1_label']}**\n{field_1_value.strip() or 'N/A'}\n\n"
            f"**{cfg['field_2_label']}**\n{field_2_value.strip() or 'N/A'}"
        )
    )

    if category_key == "middleman":
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        if confirmed_ids:
            conf_lines = "\n".join(f"• <@{uid}> (`{uid}`)" for uid in confirmed_ids)
            conf_text = f"**Confirmations:** ({len(confirmed_ids)})\n{conf_lines}"
        else:
            conf_text = "**Confirmations:** (0)\n• None yet — press **Confirm Trade** once ready."
        container.add_item(ui.TextDisplay(conf_text))

    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    buttons: list[ui.Button] = [
        ui.Button(
            label="Claim Ticket",
            emoji="🛡️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"v2_ticket_claim:{category_key}:{opener.id}",
            disabled=claimed_by is not None,
        )
    ]

    if category_key == "middleman":
        buttons.append(
            ui.Button(
                label="Confirm Trade",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"v2_ticket_confirm:{category_key}:{opener.id}",
            )
        )

    buttons.append(
        ui.Button(
            label="Close Ticket",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id=f"v2_ticket_close:{category_key}:{opener.id}",
        )
    )

    container.add_item(ui.ActionRow(*buttons))
    view.add_item(container)
    return view


def build_close_log_layout(
    channel_name: str,
    category_key: str,
    opener_id: int,
    closed_by: discord.Member,
    reason: str,
) -> ui.LayoutView:
    """V2 log card posted when a ticket closes."""
    cfg = TICKET_CONFIG.get(category_key, TICKET_CONFIG["general"])
    closed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    view = ui.LayoutView(timeout=None)
    container = ui.Container(accent_color=0xEF4444)
    container.add_item(
        ui.TextDisplay(
            f"# 🔒 Ticket Closed — `{channel_name}`\n"
            f"**Category:** {cfg['emoji']} {cfg['label']}\n"
            f"**Opener ID:** `{opener_id}`\n"
            f"**Closed By:** {closed_by.mention} (`{closed_by.id}`)\n"
            f"**Closed At:** {closed_at}\n"
            f"**Reason:** {reason.strip() or 'No reason provided'}"
        )
    )
    view.add_item(container)
    return view


# ==========================================
# MODALS
# ==========================================
class TicketCreateModal(ui.Modal):
    def __init__(self, category_key: str):
        cfg = TICKET_CONFIG[category_key]
        super().__init__(title=f"{cfg['emoji']} {cfg['label']}")
        self.category_key = category_key

        self.field_1 = ui.TextInput(
            label=cfg["field_1_label"][:45],
            placeholder=cfg["field_1_placeholder"][:100],
            style=discord.TextStyle.short,
            required=True,
            max_length=150,
        )
        self.field_2 = ui.TextInput(
            label=cfg["field_2_label"][:45],
            placeholder=cfg["field_2_placeholder"][:100],
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )

        self.add_item(self.field_1)
        self.add_item(self.field_2)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This can only be used inside a Discord server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        cfg = TICKET_CONFIG[self.category_key]
        safe_user = "".join(
            ch for ch in interaction.user.name.lower() if ch.isalnum() or ch in ("-", "_")
        )[:16] or str(interaction.user.id)
        channel_name = f"{cfg['prefix']}-{safe_user}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
            ),
        }

        staff_role = guild.get_role(STAFF_ROLE_ID) if STAFF_ROLE_ID else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

        category_obj = (
            guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        )
        parent_category = (
            category_obj if isinstance(category_obj, discord.CategoryChannel) else None
        )

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=parent_category,
                overwrites=overwrites,
                topic=f"ticket:{self.category_key}|opener:{interaction.user.id}",
                reason=f"{cfg['label']} opened by {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Missing **Manage Channels** permission to create the ticket channel.",
                ephemeral=True,
            )
            return

        mentions = f"{interaction.user.mention}"
        if staff_role:
            mentions += f" {staff_role.mention}"

        await ticket_channel.send(content=mentions)
        await ticket_channel.send(
            view=build_ticket_welcome_layout(
                category_key=self.category_key,
                opener=interaction.user,
                field_1_value=self.field_1.value,
                field_2_value=self.field_2.value,
            )
        )

        await interaction.followup.send(
            f"✅ Ticket opened: {ticket_channel.mention}", ephemeral=True
        )


class TicketCloseModal(ui.Modal, title="🔒 Close Ticket"):
    reason = ui.TextInput(
        label="Reason for Closing",
        placeholder="e.g. Issue resolved, trade completed, or invalid report",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=400,
    )

    def __init__(self, category_key: str, opener_id: int):
        super().__init__()
        self.category_key = category_key
        self.opener_id = opener_id

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        guild = interaction.guild
        if not isinstance(channel, discord.TextChannel) or not guild:
            await interaction.response.send_message(
                "Cannot close this channel.", ephemeral=True
            )
            return

        if not isinstance(interaction.user, discord.Member):
            return

        await interaction.response.send_message("🔒 Closing ticket...", ephemeral=True)

        if LOG_CHANNEL_ID:
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if isinstance(log_channel, discord.TextChannel):
                await log_channel.send(
                    view=build_close_log_layout(
                        channel_name=channel.name,
                        category_key=self.category_key,
                        opener_id=self.opener_id,
                        closed_by=interaction.user,
                        reason=self.reason.value,
                    )
                )

        await channel.delete(reason=f"Ticket closed by {interaction.user}")


# ==========================================
# BOT CLIENT & PERSISTENT BUTTON ROUTER
# ==========================================
class TicketBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
        else:
            await self.tree.sync()

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.component and interaction.data:
            custom_id = interaction.data.get("custom_id", "")

            if custom_id.startswith("v2_ticket_open:"):
                category_key = custom_id.split(":", 1)[1]
                if category_key in TICKET_CONFIG:
                    await interaction.response.send_modal(TicketCreateModal(category_key))
                return

            elif custom_id.startswith("v2_ticket_claim:"):
                _, category_key, opener_id_str = custom_id.split(":", 2)
                if not isinstance(interaction.user, discord.Member) or not interaction.guild:
                    return

                staff_role = (
                    interaction.guild.get_role(STAFF_ROLE_ID)
                    if STAFF_ROLE_ID
                    else None
                )
                is_staff = (
                    interaction.user.guild_permissions.manage_channels
                    or (staff_role in interaction.user.roles if staff_role else False)
                )

                if not is_staff:
                    await interaction.response.send_message(
                        "Only staff can claim tickets.", ephemeral=True
                    )
                    return

                opener = interaction.guild.get_member(int(opener_id_str))
                f1_val, f2_val, confirmed_ids = (
                    extract_ticket_state_from_message(interaction.message)
                    if interaction.message
                    else ("See details above", "See details above", [])
                )

                if opener and interaction.message:
                    await interaction.response.edit_message(
                        view=build_ticket_welcome_layout(
                            category_key=category_key,
                            opener=opener,
                            field_1_value=f1_val,
                            field_2_value=f2_val,
                            claimed_by=interaction.user,
                            confirmed_ids=confirmed_ids,
                        )
                    )
                    await interaction.followup.send(
                        f"🛡️ {interaction.user.mention} claimed this ticket."
                    )
                else:
                    await interaction.response.send_message(
                        f"🛡️ Claimed by {interaction.user.mention}."
                    )
                return

            elif custom_id.startswith("v2_ticket_confirm:"):
                _, category_key, opener_id_str = custom_id.split(":", 2)
                if not isinstance(interaction.user, discord.Member) or not interaction.guild:
                    return

                opener = interaction.guild.get_member(int(opener_id_str))
                if not opener or not interaction.message:
                    await interaction.response.send_message(
                        "Could not locate ticket details.", ephemeral=True
                    )
                    return

                f1_val, f2_val, confirmed_ids = extract_ticket_state_from_message(
                    interaction.message
                )

                if interaction.user.id in confirmed_ids:
                    await interaction.response.send_message(
                        "You have already confirmed this trade.", ephemeral=True
                    )
                    return

                confirmed_ids.append(interaction.user.id)

                staff_role = (
                    interaction.guild.get_role(STAFF_ROLE_ID)
                    if STAFF_ROLE_ID
                    else None
                )
                is_staff = (
                    interaction.user.guild_permissions.manage_channels
                    or (staff_role in interaction.user.roles if staff_role else False)
                )

                claimed_member: discord.Member | None = None
                for item in interaction.message.components:
                    if isinstance(item, ui.Container):
                        for child in item.children:
                            if isinstance(child, ui.TextDisplay) and "**Status:** Claimed by " in child.content:
                                m = re.search(r"<@!?(\d+)>", child.content)
                                if m:
                                    claimed_member = interaction.guild.get_member(int(m.group(1)))

                await interaction.response.edit_message(
                    view=build_ticket_welcome_layout(
                        category_key=category_key,
                        opener=opener,
                        field_1_value=f1_val,
                        field_2_value=f2_val,
                        claimed_by=claimed_member,
                        confirmed_ids=confirmed_ids,
                    )
                )

                opener_confirmed = opener.id in confirmed_ids
                staff_confirmed = any(
                    (
                        (member := interaction.guild.get_member(uid)) is not None
                        and (
                            member.guild_permissions.manage_channels
                            or (staff_role in member.roles if staff_role else False)
                        )
                    )
                    for uid in confirmed_ids
                )

                status_note = f"✅ {interaction.user.mention} confirmed the middleman trade."
                if opener_confirmed and (staff_confirmed or is_staff):
                    status_note += " Both the opener and middleman/staff have confirmed."

                await interaction.followup.send(status_note)
                return

            elif custom_id.startswith("v2_ticket_close:"):
                _, category_key, opener_id_str = custom_id.split(":", 2)
                await interaction.response.send_modal(
                    TicketCloseModal(
                        category_key=category_key, opener_id=int(opener_id_str)
                    )
                )
                return


bot = TicketBot()


@bot.tree.command(name="ticketpanel", description="Post the V2 Ticket System panel")
@app_commands.default_permissions(manage_guild=True)
async def ticketpanel(interaction: discord.Interaction):
    await interaction.response.send_message(view=build_panel_layout())


@bot.event
async def on_ready():
    print(f"Bot online as {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    if os.getenv("ENABLE_WEB_SERVER", "true").lower() == "true":
        threading.Thread(target=run_web_server, daemon=True).start()
    bot.run(TOKEN)
