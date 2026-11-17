"""Telegram update handlers."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import commands, db


logger = logging.getLogger(__name__)

ADMIN_ID = 1395567047


# Keys used to read shared connections from Application.bot_data.
DB_KEY = "db"

# Message counts are intentionally process-local and reset after a redeploy.
_LOCAL_MESSAGE_COUNTS: dict[int, int] = {}



BOT_COMMANDS = (
    ("start", "🏠 Accueil principal"),
    ("help", "📖 Aide et assistance"),
    ("about", "ℹ️ À propos de STAR PRONO"),
    ("ping", "✅ Vérifier le bot"),
    ("coupons", "🎯 Coupons du jour"),
)

MENU_HELP = "📖 Aide et assistance"
MENU_ABOUT = "ℹ️ À propos de STAR PRONO"
MENU_PING = "✅ Vérifier le bot"


HELP_TEXT = """📖 AIDE — STAR PRONO BOT

Bienvenue sur votre assistant football.

🏠 /start - Menu principal
📖 /help - Aide et assistance
ℹ️ /about - Informations du bot
✅ /ping - Vérifier le fonctionnement
🎯 /coupons - Consulter les coupons

🎁 Code promo : STAR624

⭐ STAR PRONO — Analysez avant de jouer.
"""



DYNAMIC_CALLBACK_PREFIX = "command:"


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    rows: list[list[str]] = [[MENU_HELP, MENU_ABOUT], [MENU_PING]]
    custom_rows: dict[int, list[str]] = {}
    for button in commands.reply_menu_buttons():
        custom_rows.setdefault(button["row_index"], []).append(button["label"])
    rows.extend(custom_rows[index] for index in sorted(custom_rows))
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose a menu item",
    )


def _dynamic_commands_text() -> str:
    items = commands.menu_commands()
    if not items:
        
    

        return ""
    lines = [f"/{name} - {description}" for name, description in items]
    return "\n\nAvailable menu commands:\n" + "\n".join(lines)


def _dynamic_commands_keyboard() -> InlineKeyboardMarkup | None:
    items = commands.menu_commands()
    if not items:
        return None

    buttons = [
        InlineKeyboardButton(
            description or f"/{name}",
            callback_data=f"{DYNAMIC_CALLBACK_PREFIX}{name}",
        )
        for name, description in items
    ]
    
    rows = [
        buttons[index:index + 2]
        for index in range(0, len(buttons), 2)
    ]

    rows.append([
        InlineKeyboardButton(
            "📋 Coupons du jour",
            url="https://t.me/starprono624"
        )
    ])

    rows.append([
        InlineKeyboardButton(
            "🎁 Code promo STAR624",
            callback_data="promo_star624"
        )
    ])

    return InlineKeyboardMarkup(rows)




async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return

    pool = context.bot_data.get(DB_KEY)
    if pool is not None:
        await db.upsert_user(
            pool,
            user.id,
            user.username,
            user.first_name
        )

    name = user.first_name or "cher membre"

    await message.reply_text(
        f"⚽ BIENVENUE SUR STAR PRONO BOT ⭐\n\n"
        f"Bonjour {name} 👋\n\n"
        "🎯 Retrouvez nos coupons et analyses du jour.\n"
        "📊 Découvrez nos pronostics sportifs.\n\n"
        "🎁 CODE PROMO : STAR624\n\n"
        "📢 Notre canal Telegram :\n"
        "https://t.me/starprono624\n\n"
        "👇 Sélectionnez un bouton pour continuer.\n\n"
        "⭐ STAR PRONO — Analysez avant de jouer. 🔞",
        
            )

    await message.reply_text(
        "👇 Voici votre menu principal :",
        reply_markup=ReplyKeyboardRemove()
    )

    dynamic_keyboard = _dynamic_commands_keyboard()
    if dynamic_keyboard is not None:
        await message.reply_text(
            "🎯 Choisissez votre service :",
            reply_markup=dynamic_keyboard
        )



async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        HELP_TEXT
        + _dynamic_commands_text()
        + "\n\nSend a normal text message and the bot will echo it back.",
        reply_markup=_dynamic_commands_keyboard(),
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        "This bot is built with python-telegram-bot and is ready to deploy on Railway."
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    del context
    await message.reply_text("pong")


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    text = message.text.strip()
    if text == MENU_HELP:
        await help_command(update, context)
    elif text == MENU_ABOUT:
        await about(update, context)
    elif text == MENU_PING:
        await ping(update, context)


async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or not message.text or user is None:
        return

    target = commands.button_target(message.text.strip())
    if target is not None:
        if target == "help":
            await help_command(update, context)
        elif target == "about":
            await about(update, context)
        elif target == "ping":
            await ping(update, context)
        elif target == "start":
            await start(update, context)
        else:
            command = commands.lookup(target)
            if command is None:
                await message.reply_text("This button's command is currently unavailable.")
            else:
                await commands.send(message, command)
        return

    count = _LOCAL_MESSAGE_COUNTS[user.id] = _LOCAL_MESSAGE_COUNTS.get(user.id, 0) + 1
    await message.reply_text(f"You sent (#{count}):\n{message.text}")


def _parse_command_name(text: str) -> str:
    """Extract the bare command name from message text (e.g. '/promo@bot a' -> 'promo')."""
    token = text.strip().split(maxsplit=1)[0]  # '/promo@bot'
    token = token.lstrip("/")
    token = token.split("@", 1)[0]  # drop optional @botusername
    return token.lower()


async def dynamic_command_dispatcher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any command not served by a built-in handler.

    Looks the command up in the panel-managed registry and replies with its
    configured response, falling back to the 'unknown command' message.
    """
    del context
    message = update.effective_message
    if message is None or not message.text:
        return

    command = commands.lookup(_parse_command_name(message.text))
    if command is not None:
        await commands.send(message, command)
        return

    await message.reply_text("Unknown command. Type /help for assistance.")




async def dynamic_command_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Run a panel-managed command selected from an inline button.


    del context
    query = update.callback_query
    if query is None or query.data is None:
        return

    name = query.data.removeprefix(DYNAMIC_CALLBACK_PREFIX)
    command = commands.lookup(name)
    if command is None:
        await query.answer("This command is no longer available.", show_alert=True)
        return

    await query.answer()
    if query.message is not None:
        await commands.send(query.message, command)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error

    # Transient polling/network errors (e.g. a brief 409 Conflict during a
    # Railway redeploy when two instances overlap) are self-healing, so log them
    # as warnings without a traceback instead of alarming-looking errors.
    if isinstance(error, (Conflict, NetworkError, TimedOut)):
        logger.warning("Transient Telegram error: %s", error)
        return

    logger.exception("Error while processing update: %s", update, exc_info=error)

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Sorry, an error occurred while processing your message."
        )


async def set_bot_commands(application: Application) -> None:
    # Publish the built-in commands plus any panel-managed ones to Telegram.
    menu = list(BOT_COMMANDS) + commands.menu_commands()
    await application.bot.set_my_commands(menu)


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
async def coupons_du_jour(update, context):
    clavier = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📋 Voir les coupons du jour",
            url="https://t.me/starprono624"
        )]
    ])
    await update.message.reply_text(
        "⚽ STAR PRONO BOT\n\n"
        "Retrouvez nos coupons et analyses du jour "
        "sur notre canal Telegram 👇",
        reply_markup=clavier
    )

async def promo_star624(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    await query.message.reply_text(
        "🎁 CODE PROMO : STAR624\n\n"
        "⚽ Bienvenue sur STAR PRONO BOT !\n\n"
        "Utilisez notre code promo STAR624 "
        "lors de votre inscription.\n\n"
        "📢 Canal Telegram : https://t.me/starprono624"
    )



async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    message = update.effective_message

    if user is None or message is None:
        return

    if user.id != ADMIN_ID:
        await message.reply_text(
            "⛔ Accès réservé à l'administrateur."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 Gérer les coupons",
                callback_data="admin_coupons"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ Modifier les messages",
                callback_data="admin_messages"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 Gérer le code promo",
                callback_data="admin_promo"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Annonces",
                callback_data="admin_annonces"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Statistiques",
                callback_data="admin_stats"
            )
        ]
    ])

    await message.reply_text(
        "🔐 ADMINISTRATION STAR PRONO BOT\n\n"
        "Bienvenue dans votre espace privé.\n\n"
        "👇 Sélectionnez une rubrique :",
        reply_markup=keyboard
    )


async def admin_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return

    user = update.effective_user
    if user is None or user.id != ADMIN_ID:
        await query.answer(
            "⛔ Accès interdit.",
            show_alert=True
        )
        return

    await query.answer()

    await query.message.reply_text(
        "⚙️ Cette rubrique sera configurée "
        "prochainement."
    )

def register_handlers(application: Application) -> None:
    
    application.add_handler(
        CallbackQueryHandler(
            promo_star624,
            pattern="^promo_star624$"
        )
    )

    application.add_handler(CommandHandler("start", start))
    
    application.add_handler(
        CommandHandler("coupons", coupons_du_jour)
    )

    
    

    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(
        CallbackQueryHandler(
            dynamic_command_button,
            pattern=f"^{DYNAMIC_CALLBACK_PREFIX}[a-z0-9_]{{1,32}}$",
        )
    )
    # Any other /command is resolved dynamically from the panel-managed registry.
    application.add_handler(MessageHandler(filters.COMMAND, dynamic_command_dispatcher))
    application.add_handler(
        MessageHandler(filters.Regex(f"^({MENU_HELP}|{MENU_ABOUT}|{MENU_PING})$"), menu_button)
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_message))



