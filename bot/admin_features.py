"""STAR PRONO: persistent Telegram admin panel (python-telegram-bot v20+)."""
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from bot import db

LOG = logging.getLogger(__name__)
ADMIN_ID = 1395567047
DB_KEY = "db"
DATA_PATH = Path(os.environ.get("STARPRONO_DATA_PATH", "/data/starprono.sqlite3"))
DEFAULT_WELCOME = "⚽ BIENVENUE SUR STAR PRONO BOT ⭐\n\nBonjour {name} 👋\n\n🎯 Retrouvez nos coupons et analyses du jour.\n🎁 CODE PROMO : {promo}\n📢 https://t.me/starprono624\n\n🔞 Jouez de façon responsable."
DEFAULT_HELP = "📖 AIDE — STAR PRONO BOT\n\n/start — Accueil\n/coupons — Coupons du jour\n/admin — Administration\n\n🎁 Code promo : {promo}"


def _connect():
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_PATH)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS coupons (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, file_id TEXT, media_type TEXT, created_at TEXT NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS broadcasts (id INTEGER PRIMARY KEY AUTOINCREMENT, sent INTEGER, failed INTEGER, created_at TEXT NOT NULL)")
    con.commit()
    return con


def get_setting(key, default=""):
    with _connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with _connect() as con:
        con.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_promo():
    return get_setting("promo", "STAR624")


def welcome_text(name):
    return get_setting("welcome", DEFAULT_WELCOME).replace("{name}", name).replace("{promo}", get_promo())


def help_text():
    return get_setting("help", DEFAULT_HELP).replace("{promo}", get_promo())


def _keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Gérer les coupons", callback_data="admin_coupons")],
        [InlineKeyboardButton("✏️ Modifier les messages", callback_data="admin_messages")],
        [InlineKeyboardButton("🎁 Gérer le code promo", callback_data="admin_promo")],
        [InlineKeyboardButton("📢 Annonces", callback_data="admin_annonces")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin_stats")],
    ])


def _back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Retour au panneau", callback_data="admin_home")]])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ Accès réservé à l'administrateur.")
        return
    context.user_data.pop("admin_action", None)
    await update.effective_message.reply_text("🔐 ADMINISTRATION STAR PRONO BOT\n\n👇 Sélectionnez une rubrique :", reply_markup=_keyboard())


async def _stats(context):
    pool = context.bot_data.get(DB_KEY)
    try:
        ids = list(set(await db.list_user_ids(pool))) if pool is not None else []
        users = str(len(ids)) if pool is not None else "indisponible"
    except Exception:
        LOG.exception("Impossible de lire les utilisateurs")
        users = "indisponible"
    with _connect() as con:
        coupons = con.execute("SELECT COUNT(*) AS n FROM coupons").fetchone()["n"]
        last = con.execute("SELECT sent,failed,created_at FROM broadcasts ORDER BY id DESC LIMIT 1").fetchone()
    last_text = f"{last['sent']} envoyés, {last['failed']} échecs ({last['created_at']})" if last else "Aucune"
    return f"📊 STATISTIQUES\n\n👥 Utilisateurs : {users}\n📋 Coupons enregistrés : {coupons}\n📢 Dernière annonce : {last_text}"


async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        await query.answer("⛔ Accès interdit", show_alert=True)
        return
    await query.answer()
    action = query.data
    context.user_data.pop("admin_action", None)
    if action == "admin_home":
        await query.message.reply_text("🔐 Panneau administrateur", reply_markup=_keyboard())
    elif action == "admin_coupons":
        await query.message.reply_text("📋 Coupons : choisissez une action.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Ajouter un coupon", callback_data="admin_add_coupon")],
            [InlineKeyboardButton("📚 Voir les coupons", callback_data="admin_list_coupons")],
            [InlineKeyboardButton("🗑 Supprimer un coupon", callback_data="admin_delete_coupon")],
            [InlineKeyboardButton("⬅️ Retour", callback_data="admin_home")],
        ]))
    elif action == "admin_add_coupon":
        context.user_data["admin_action"] = "add_coupon"
        await query.message.reply_text("Envoyez le texte, une photo avec légende ou une image du coupon. /annuler pour quitter.")
    elif action == "admin_list_coupons":
        await show_coupons(query.message)
        await query.message.reply_text("Retour au panneau :", reply_markup=_back())
    elif action == "admin_delete_coupon":
        context.user_data["admin_action"] = "delete_coupon"
        await query.message.reply_text("Envoyez l'identifiant numérique du coupon à supprimer (voir la liste). /annuler pour quitter.")
    elif action == "admin_messages":
        await query.message.reply_text("✏️ Quel message modifier ?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Message d'accueil", callback_data="admin_edit_welcome")],
            [InlineKeyboardButton("📖 Texte d'aide", callback_data="admin_edit_help")],
            [InlineKeyboardButton("⬅️ Retour", callback_data="admin_home")],
        ]))
    elif action in ("admin_edit_welcome", "admin_edit_help"):
        key = "welcome" if action.endswith("welcome") else "help"
        context.user_data["admin_action"] = "edit_" + key
        await query.message.reply_text("Envoyez le nouveau texte. Variables disponibles : {name} et {promo}. /annuler pour quitter.")
    elif action == "admin_promo":
        context.user_data["admin_action"] = "edit_promo"
        await query.message.reply_text(f"🎁 Code actuel : {get_promo()}\nEnvoyez le nouveau code (lettres/chiffres, 3 à 30 caractères). /annuler pour quitter.")
    elif action == "admin_annonces":
        context.user_data["admin_action"] = "announce"
        await query.message.reply_text("📢 Envoyez le texte ou une photo avec légende à diffuser. Une confirmation sera demandée. /annuler pour quitter.")
    elif action == "admin_stats":
        await query.message.reply_text(await _stats(context), reply_markup=_back())


async def show_coupons(message):
    with _connect() as con:
        rows = con.execute("SELECT * FROM coupons ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        await message.reply_text("📋 Aucun coupon enregistré.")
        return
    for row in rows:
        title = f"📋 Coupon #{row['id']} — {row['created_at']}"
        if row["media_type"] == "photo":
            await message.reply_photo(row["file_id"], caption=(title + "\n" + (row["text"] or ""))[:1024])
        else:
            await message.reply_text((title + "\n" + (row["text"] or ""))[:4096])


async def coupons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_coupons(update.effective_message)
    await update.effective_message.reply_text("📢 Canal : https://t.me/starprono624")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    context.user_data.pop("admin_action", None)
    context.user_data.pop("pending_announcement", None)
    await update.effective_message.reply_text("Opération annulée.", reply_markup=_back())


async def admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    action = context.user_data.get("admin_action")
    if not action:
        return
    msg = update.effective_message
    value = (msg.text or msg.caption or "").strip()
    if action == "add_coupon":
        if not value and not msg.photo:
            await msg.reply_text("Envoyez un texte ou une photo.")
            return
        with _connect() as con:
            cur = con.execute("INSERT INTO coupons(text,file_id,media_type,created_at) VALUES (?,?,?,?)", (
                value, msg.photo[-1].file_id if msg.photo else None,
                "photo" if msg.photo else "text", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
            coupon_id = cur.lastrowid
        await msg.reply_text(f"✅ Coupon #{coupon_id} enregistré. Il apparaît maintenant dans /coupons.")
    elif action == "delete_coupon":
        if not value.isdigit():
            await msg.reply_text("Envoyez uniquement l'identifiant numérique.")
            return
        with _connect() as con:
            deleted = con.execute("DELETE FROM coupons WHERE id=?", (int(value),)).rowcount
        await msg.reply_text("✅ Coupon supprimé." if deleted else "Coupon introuvable.")
    elif action in ("edit_welcome", "edit_help"):
        if not value or len(value) > 3500:
            await msg.reply_text("Envoyez un texte entre 1 et 3500 caractères.")
            return
        set_setting(action.removeprefix("edit_"), value)
        await msg.reply_text("✅ Message mis à jour.")
    elif action == "edit_promo":
        if not 3 <= len(value) <= 30 or not value.isalnum():
            await msg.reply_text("Code invalide : 3 à 30 lettres ou chiffres, sans espaces.")
            return
        set_setting("promo", value.upper())
        await msg.reply_text(f"✅ Code promo enregistré : {get_promo()}")
    elif action == "announce":
        if not value and not msg.photo:
            await msg.reply_text("Envoyez un texte ou une photo.")
            return
        context.user_data["pending_announcement"] = (msg.chat_id, msg.message_id)
        context.user_data.pop("admin_action", None)
        await msg.reply_text("⚠️ Confirmer l'envoi à tous les utilisateurs enregistrés ?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Envoyer", callback_data="broadcast_confirm")],
            [InlineKeyboardButton("❌ Annuler", callback_data="broadcast_cancel")],
        ]))
        raise ApplicationHandlerStop
    context.user_data.pop("admin_action", None)
    await msg.reply_text("Retour au panneau :", reply_markup=_back())
    raise ApplicationHandlerStop


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        await query.answer("⛔ Accès interdit", show_alert=True)
        return
    if query.data == "broadcast_cancel":
        context.user_data.pop("pending_announcement", None)
        await query.answer("Annulé")
        await query.message.reply_text("Annonce annulée.")
        return
    pending = context.user_data.pop("pending_announcement", None)
    if pending is None:
        await query.answer("Annonce expirée", show_alert=True)
        return
    pool = context.bot_data.get(DB_KEY)
    if pool is None:
        await query.answer("Base utilisateurs indisponible", show_alert=True)
        return
    try:
        ids = list(set(await db.list_user_ids(pool)))
    except Exception:
        LOG.exception("Erreur de lecture des utilisateurs")
        await query.answer("Erreur base de données", show_alert=True)
        return
    await query.answer()
    await query.message.reply_text(f"📢 Diffusion en cours vers {len(ids)} comptes…")
    sent = failed = 0
    for uid in ids:
        if uid == ADMIN_ID:
            continue
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=pending[0], message_id=pending[1])
            sent += 1
            await asyncio.sleep(0.06)
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 1)
            try:
                await context.bot.copy_message(chat_id=uid, from_chat_id=pending[0], message_id=pending[1])
                sent += 1
            except TelegramError:
                failed += 1
        except (Forbidden, TelegramError):
            failed += 1
    with _connect() as con:
        con.execute("INSERT INTO broadcasts(sent,failed,created_at) VALUES (?,?,?)", (sent, failed, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    await query.message.reply_text(f"✅ Diffusion terminée : {sent} envoyés, {failed} échecs.", reply_markup=_back())


def register_admin_features(application):
    # Register these BEFORE the generic text and callback handlers.
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("annuler", cancel))
    application.add_handler(CommandHandler("coupons", coupons_command))
    application.add_handler(CallbackQueryHandler(admin_button, pattern=r"^admin_"))
    application.add_handler(CallbackQueryHandler(broadcast_callback, pattern=r"^broadcast_(confirm|cancel)$"))
    application.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.PHOTO, admin_input), group=-1)
