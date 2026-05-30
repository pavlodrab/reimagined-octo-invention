"""
bot.py  —  Telegram entry point for Chelsea Voting Mini App
"""
import logging
import os
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from db import *

from logging_setup import init_logging

init_logging()
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
MINI_APP_URL    = os.getenv("MINI_APP_URL", "https://your-domain.com")
OWNER_ID        = int(os.getenv("OWNER_ID", "0"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    btn = KeyboardButton(
        text="⚽ Открыть голосование",
        web_app=WebAppInfo(url=MINI_APP_URL)
    )
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True)
    await update.message.reply_html(
        f"Привет, {user.mention_html()}!\n\n"
        "Это бот для оценки игроков Челси после матчей.\n"
        "Нажмите кнопку ниже, чтобы открыть мини-приложение.",
        reply_markup=kb,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (
        "<b>Available commands:</b>\n\n"
        "/start - Open the voting mini app\n"
        "/stats - Your personal statistics\n"
        "/top - Top-3 players of current match\n"
        "/streak - Your voting streak info\n"
        "/predict &lt;player_name&gt; - Quick prediction\n"
        "/help - This help message"
    )
    if _is_owner(user_id):
        text += (
            "\n\n<b>👑 Owner-only commands:</b>\n"
            "/admin_add &lt;user_id&gt; [username] - Grant admin\n"
            "/admin_remove &lt;user_id&gt; - Revoke admin\n"
            "/admins - List current admins"
        )
    await update.message.reply_html(text)


# ── Owner / admin management ─────────────────────────────────────────────

def _is_owner(uid: int) -> bool:
    """A user is the owner if their id matches OWNER_ID env or the DB-stored owner_id."""
    if OWNER_ID and uid == OWNER_ID:
        return True
    try:
        return uid == get_owner_id()
    except Exception:
        return False


async def admin_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_html("❌ Только владелец бота может выдавать админку.")
        return
    if not context.args:
        await update.message.reply_html(
            "Usage: <code>/admin_add &lt;user_id&gt; [username]</code>\n"
            "Example: <code>/admin_add 123456789 johndoe</code>"
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ user_id должен быть числом.")
        return
    if target_id <= 0:
        await update.message.reply_html("❌ user_id должен быть положительным числом.")
        return
    username = context.args[1] if len(context.args) > 1 else ''
    add_admin(target_id, username, user_id)
    add_log(user_id, "add_admin_via_bot", target_user_id=target_id,
            details={"username": username})
    uname_disp = f"@{username}" if username else "(без username)"
    await update.message.reply_html(
        f"✅ Админ добавлен: <code>{target_id}</code> {uname_disp}"
    )


async def admin_remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_html("❌ Только владелец бота может убирать админку.")
        return
    if not context.args:
        await update.message.reply_html(
            "Usage: <code>/admin_remove &lt;user_id&gt;</code>"
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ user_id должен быть числом.")
        return
    if target_id == get_owner_id():
        await update.message.reply_html("❌ Нельзя убрать админку у владельца. Поменяй OWNER_ID env.")
        return
    remove_admin(target_id)
    add_log(user_id, "remove_admin_via_bot", target_user_id=target_id)
    await update.message.reply_html(f"✅ Админ удалён: <code>{target_id}</code>")


async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_html("❌ Только владелец бота может смотреть список админов.")
        return
    admins = list_admins()
    owner_id = get_owner_id()
    text = "<b>👥 Админы:</b>\n\n"
    text += f"👑 Owner: <code>{owner_id if owner_id else '(не задан)'}</code>\n"
    if admins:
        text += "\n<b>Дополнительные админы:</b>"
        for a in admins:
            uname = f"@{a['username']}" if a.get('username') else '(без username)'
            text += f"\n🛡 <code>{a['user_id']}</code> — {uname}"
    else:
        text += "\n<i>(других админов нет)</i>"
    await update.message.reply_html(text)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_profile(user_id, update.effective_user.username or '', update.effective_user.first_name or '')
    profile_stats = get_profile_stats(user_id)
    xp_data = get_user_xp(user_id)
    streak_data = get_user_streak(user_id)

    fire = "\U0001f525" if streak_data['current_streak'] >= 5 else ""
    text = (
        f"<b>\U0001f4ca Your Statistics</b>\n\n"
        f"\u26bd Votes cast: {profile_stats.get('total_votes', 0)}\n"
        f"\U0001f4c8 Avg rating given: {profile_stats.get('avg_rating_given', 0)}\n"
        f"\u2728 XP: {xp_data['total_xp']}\n"
        f"\U0001f3c5 Level: {xp_data['level']}\n"
        f"\U0001f525 Streak: {streak_data['current_streak']} {fire}\n"
        f"\U0001f3c6 Max streak: {streak_data['max_streak']}"
    )
    await update.message.reply_html(text)


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = get_current_poll()
    if not poll:
        await update.message.reply_html("No active poll right now.")
        return
    results = get_results(poll['poll_id'])
    if not results:
        await update.message.reply_html("No votes yet for the current match.")
        return

    match_id = poll.get('match_id', '')
    conn = get_connection()
    try:
        text = f"<b>\U0001f3c6 Top-3: {poll.get('title', 'Current Match')}</b>\n\n"
        medals = ['\U0001f947', '\U0001f948', '\U0001f949']
        for i, r in enumerate(results[:3]):
            player_row = conn.execute(
                'SELECT name FROM players WHERE player_id = ? AND match_id = ?',
                (r['player_id'], match_id)
            ).fetchone()
            name = player_row['name'] if player_row else r['player_id']
            text += f"{medals[i]} {name} - {r['avg_rating']}\n"
    finally:
        conn.close()

    total = get_total_votes_for_poll(poll['poll_id'])
    text += f"\n\U0001f465 Total voters: {total}"
    await update.message.reply_html(text)


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_profile(user_id, update.effective_user.username or '', update.effective_user.first_name or '')
    streak_data = get_user_streak(user_id)

    current = streak_data['current_streak']
    max_s = streak_data['max_streak']
    fire = "\U0001f525" * min(current, 5) if current >= 5 else ""

    text = (
        f"<b>\U0001f525 Voting Streak</b>\n\n"
        f"Current streak: {current} matches {fire}\n"
        f"Record streak: {max_s} matches\n"
    )
    if current >= 5:
        text += "\n\U0001f3c5 You have the Fire badge! Keep it up!"
    elif current >= 3:
        text += f"\n\U0001f4aa {5 - current} more to get the Fire badge!"
    else:
        text += "\nVote in consecutive matches to build your streak!"

    await update.message.reply_html(text)


async def predict_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_profile(user_id, update.effective_user.username or '', update.effective_user.first_name or '')

    poll = get_current_poll()
    if not poll:
        await update.message.reply_html("No active poll. Can't make a prediction right now.")
        return
    if poll['status'] != 'open':
        await update.message.reply_html("Current poll is closed. Wait for the next match!")
        return

    # Get player name from args
    if not context.args:
        await update.message.reply_html(
            "Usage: /predict &lt;player_name&gt;\n"
            "Example: /predict Palmer"
        )
        return

    search_name = ' '.join(context.args).lower()
    match_id = poll.get('match_id', '')

    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT player_id, name FROM players WHERE match_id = ?', (match_id,)
        ).fetchall()
    finally:
        conn.close()

    # Find matching players (partial case-insensitive match)
    matches = [(r['player_id'], r['name']) for r in rows if search_name in r['name'].lower()]

    if not matches:
        await update.message.reply_html(f"No player found matching '<b>{search_name}</b>'.")
        return
    if len(matches) > 1:
        names = '\n'.join([f"\u2022 {m[1]}" for m in matches])
        await update.message.reply_html(f"Multiple matches found:\n{names}\n\nBe more specific.")
        return

    player_id, player_name = matches[0]
    add_prediction(poll['poll_id'], user_id, player_id)
    await update.message.reply_html(
        f"\u2705 Prediction submitted!\n"
        f"You predicted <b>{player_name}</b> as best player for:\n"
        f"<i>{poll.get('title', 'Current Match')}</i>"
    )


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Set TELEGRAM_TOKEN environment variable")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("streak", streak_cmd))
    app.add_handler(CommandHandler("predict", predict_cmd))
    # Owner-only admin management commands
    app.add_handler(CommandHandler("admin_add", admin_add_cmd))
    app.add_handler(CommandHandler("admin_remove", admin_remove_cmd))
    app.add_handler(CommandHandler("admins", admins_cmd))
    logger.info("Bot started (polling)")
    app.run_polling()


if __name__ == "__main__":
    main()
