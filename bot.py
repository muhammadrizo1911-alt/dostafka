# =====================================================================
#                        SOZLAMALAR (QO'LDA YOZING)
# =====================================================================
TOKEN = "8877210409:AAGgaRlFve7ChlERphyNrRmKF038N4RVax0"   # BotFather tokeni
ADMIN_IDS = {5538156384}              # Telegram ID ingiz, masalan: {123456789}  (bir nechta: {111, 222})

STEP_METERS = 200            # har necha metrga
STEP_PRICE = 600             # necha so'm
MIN_PRICE = 3000             # minimal narx (so'm)
ROAD_FACTOR = 1.3            # to'g'ri chiziq -> yo'l koeffitsienti
MAX_DISTANCE_KM = 50         # maksimal masofa (km)
DB_PATH = "orders.db"        # Railway Volume bo'lsa: "/data/orders.db"
# =====================================================================

import os
import re
import html
import sqlite3
import logging
from datetime import datetime
from math import radians, cos, sin, asin, sqrt, ceil

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------- HOLATLAR -----------------------------
PICKUP, DELIVERY, PHONE, NOTE, PAYMENT, CONFIRM = range(6)

# ----------------------------- TUGMALAR -----------------------------
BTN_NEW = "🚚 Yangi buyurtma"
BTN_MY = "📋 Buyurtmalarim"
BTN_TARIFF = "💰 Tariflar"
BTN_CANCEL = "❌ Bekor qilish"
BTN_SKIP = "⏭ O'tkazib yuborish"
BTN_CARD = "💳 Karta"
BTN_CASH = "💵 Naqd pul"
BTN_CONFIRM = "✅ Tasdiqlash"

MAIN_MENU = ReplyKeyboardMarkup(
    [[BTN_NEW], [BTN_MY, BTN_TARIFF]], resize_keyboard=True
)
CANCEL_FILTER = filters.Regex(f"^{re.escape(BTN_CANCEL)}$")

STATUS_TEXT = {
    "new": "🕐 Kutilmoqda",
    "accepted": "✅ Qabul qilindi",
    "rejected": "❌ Rad etildi",
    "cancelled": "🚫 Bekor qilindi",
}


# ----------------------------- BAZA -----------------------------
def db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                pickup_lat REAL, pickup_lon REAL,
                delivery_lat REAL, delivery_lon REAL,
                distance REAL,
                price INTEGER,
                payment TEXT,
                note TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT
            )
            """
        )


def save_order(data: dict) -> int:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO orders (user_id, username, full_name, phone,
                pickup_lat, pickup_lon, delivery_lat, delivery_lon,
                distance, price, payment, note, status, created_at)
            VALUES (:user_id, :username, :full_name, :phone,
                :pickup_lat, :pickup_lon, :delivery_lat, :delivery_lon,
                :distance, :price, :payment, :note, 'new', :created_at)
            """,
            data,
        )
        return cur.lastrowid


def get_order(order_id: int):
    with db() as conn:
        return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def set_status(order_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))


# ----------------------------- YORDAMCHI -----------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi to'g'ri chiziq masofasi (metr)."""
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return R * 2 * asin(sqrt(a))


def calc_price(distance_m: float) -> int:
    """Narx: yo'l koeffitsienti bilan, 100 so'mga yuqoriga yaxlitlanadi, minimal narx bilan."""
    raw = (distance_m * ROAD_FACTOR / STEP_METERS) * STEP_PRICE
    price = ceil(raw / 100) * 100
    return max(price, MIN_PRICE)


def fmt_money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


def fmt_distance(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


def map_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat},{lon}"


def esc(s) -> str:
    return html.escape(str(s or ""))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS and user_id != 0


def order_text(o, for_admin: bool = False) -> str:
    lines = [
        f"📦 <b>Buyurtma #{o['id']}</b>",
        f"📊 Holat: {STATUS_TEXT.get(o['status'], o['status'])}",
    ]
    if for_admin:
        lines.append(f"👤 {esc(o['full_name'])}" + (f" (@{esc(o['username'])})" if o["username"] else ""))
    lines += [
        f"📞 {esc(o['phone'])}",
        f"📍 <a href=\"{map_link(o['pickup_lat'], o['pickup_lon'])}\">Olish manzili</a>",
        f"🏁 <a href=\"{map_link(o['delivery_lat'], o['delivery_lon'])}\">Yetkazish manzili</a>",
        f"📏 Masofa: {fmt_distance(o['distance'])}",
        f"💵 Summa: <b>{fmt_money(o['price'])}</b>",
        f"💳 To'lov: {esc(o['payment'])}",
    ]
    if o["note"]:
        lines.append(f"📝 Izoh: {esc(o['note'])}")
    lines.append(f"🕒 {o['created_at']}")
    return "\n".join(lines)


def cancel_kb(*extra_rows) -> ReplyKeyboardMarkup:
    rows = list(extra_rows) + [[BTN_CANCEL]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


# ----------------------------- ASOSIY BUYRUQLAR -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user = update.effective_user
    await update.message.reply_text(
        f"Assalomu alaykum, {esc(user.first_name)}! 🚚\n\n"
        "Dostavka xizmatiga xush kelibsiz!\n"
        "Buyurtma berish uchun pastdagi tugmani bosing.",
        reply_markup=MAIN_MENU,
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def tariff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💰 <b>Tariflar</b>\n\n"
        f"• Har {STEP_METERS} metrga: <b>{fmt_money(STEP_PRICE)}</b>\n"
        f"• Minimal narx: <b>{fmt_money(MIN_PRICE)}</b>\n"
        f"• Maksimal masofa: {MAX_DISTANCE_KM:.0f} km\n\n"
        "Masofa yo'l egriligini hisobga olgan holda hisoblanadi.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🚚 <b>Dostavka bot</b>\n\n"
        "/start — Bosh menyu\n"
        "/order — Yangi buyurtma\n"
        "/myorders — Mening buyurtmalarim\n"
        "/tariff — Tariflar\n"
        "/cancel — Joriy buyurtmani bekor qilish\n"
        "/help — Yordam"
    )
    if is_admin(update.effective_user.id):
        text += "\n\n👑 <b>Admin:</b>\n/orders — oxirgi 10 ta buyurtma\n/stats — statistika"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU)


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text("Sizda hali buyurtmalar yo'q.", reply_markup=MAIN_MENU)
        return
    for o in rows:
        await update.message.reply_text(
            order_text(o), parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


# ----------------------------- BUYURTMA JARAYONI -----------------------------
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📦 Buyurtmani <b>qayerdan</b> olishimiz kerak?\n\n"
        "1️⃣ Hozirgi joyingiz bo'lsa — <b>«📍 Olish manzilini yuborish»</b> tugmasini bosing.\n"
        "2️⃣ Boshqa joy bo'lsa — 📎 (skrepka) → <b>Lokatsiya</b> → xaritada kerakli joyni belgilab, "
        "<b>«Tanlangan lokatsiyani yuborish»</b> ni bosing.",
        reply_markup=cancel_kb([KeyboardButton("📍 Olish manzilini yuborish", request_location=True)]),
        parse_mode=ParseMode.HTML,
    )
    return PICKUP


async def pickup_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    context.user_data["pickup"] = (loc.latitude, loc.longitude)
    await update.message.reply_text(
        "✅ Olish manzili qabul qilindi!\n\n"
        "🏁 Endi buyurtmani <b>qayerga</b> yetkazamiz?\n\n"
        "1️⃣ Hozirgi joyingizga bo'lsa — <b>«📍 Yetkazish manzilini yuborish»</b> tugmasini bosing.\n"
        "2️⃣ Boshqa joyga bo'lsa — 📎 (skrepka) → <b>Lokatsiya</b> → xaritada kerakli joyni qo'lda belgilab, "
        "<b>«Tanlangan lokatsiyani yuborish»</b> ni bosing.",
        reply_markup=cancel_kb([KeyboardButton("📍 Yetkazish manzilini yuborish", request_location=True)]),
        parse_mode=ParseMode.HTML,
    )
    return DELIVERY


async def delivery_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    lat1, lon1 = context.user_data["pickup"]
    distance = haversine(lat1, lon1, loc.latitude, loc.longitude)

    if distance < 50:
        await update.message.reply_text(
            "⚠️ Olish va yetkazish manzillari juda yaqin. Iltimos, yetkazish manzilini qayta yuboring.",
            reply_markup=cancel_kb([KeyboardButton("📍 Yetkazish manzilini yuborish", request_location=True)]),
        )
        return DELIVERY
    if distance * ROAD_FACTOR / 1000 > MAX_DISTANCE_KM:
        await update.message.reply_text(
            f"⚠️ Masofa juda uzoq (maksimum {MAX_DISTANCE_KM:.0f} km). "
            "Iltimos, boshqa manzil yuboring yoki /cancel bosing."
        )
        return DELIVERY

    price = calc_price(distance)
    context.user_data.update(
        delivery=(loc.latitude, loc.longitude), distance=distance * ROAD_FACTOR, price=price
    )

    await update.message.reply_text(
        "📊 <b>Hisob-kitob:</b>\n\n"
        f"📏 Taxminiy masofa: <b>{fmt_distance(distance * ROAD_FACTOR)}</b>\n"
        f"💵 <b>Jami: {fmt_money(price)}</b>\n\n"
        "📞 Endi telefon raqamingizni yuboring (tugma orqali yoki yozib: +998901234567):",
        reply_markup=cancel_kb([KeyboardButton("📞 Raqamni yuborish", request_contact=True)]),
        parse_mode=ParseMode.HTML,
    )
    return PHONE


async def phone_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _save_phone(update, context, update.message.contact.phone_number)


async def phone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        digits = "998" + digits
    if not (len(digits) == 12 and digits.startswith("998")):
        await update.message.reply_text(
            "⚠️ Raqam noto'g'ri. Misol: <code>+998901234567</code>", parse_mode=ParseMode.HTML
        )
        return PHONE
    return await _save_phone(update, context, "+" + digits)


async def _save_phone(update, context, phone: str) -> int:
    context.user_data["phone"] = phone if phone.startswith("+") else "+" + phone
    await update.message.reply_text(
        "📝 Buyurtma haqida izoh yozing (masalan: <i>«3-qavat, 12-xona, qo'ng'iroq qiling»</i>) "
        "yoki o'tkazib yuboring:",
        reply_markup=cancel_kb([BTN_SKIP]),
        parse_mode=ParseMode.HTML,
    )
    return NOTE


async def note_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["note"] = "" if text == BTN_SKIP else text[:300]
    await update.message.reply_text(
        "💳 To'lov usulini tanlang:",
        reply_markup=cancel_kb([BTN_CARD, BTN_CASH]),
    )
    return PAYMENT


async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    method = update.message.text.strip()
    if method not in (BTN_CARD, BTN_CASH):
        await update.message.reply_text(f"Iltimos, tugmalardan birini tanlang: {BTN_CARD} yoki {BTN_CASH}")
        return PAYMENT

    d = context.user_data
    d["payment"] = method
    note = f"\n📝 Izoh: {esc(d['note'])}" if d.get("note") else ""
    await update.message.reply_text(
        "🧾 <b>Buyurtmani tekshiring:</b>\n\n"
        f"📏 Masofa: {fmt_distance(d['distance'])}\n"
        f"💵 Summa: <b>{fmt_money(d['price'])}</b>\n"
        f"💳 To'lov: {method}\n"
        f"📞 Telefon: {esc(d['phone'])}{note}\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=cancel_kb([BTN_CONFIRM]),
        parse_mode=ParseMode.HTML,
    )
    return CONFIRM


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip() != BTN_CONFIRM:
        await update.message.reply_text("Tasdiqlash uchun tugmani bosing yoki bekor qiling.")
        return CONFIRM

    d, user = context.user_data, update.effective_user
    order_id = save_order(
        {
            "user_id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "phone": d["phone"],
            "pickup_lat": d["pickup"][0],
            "pickup_lon": d["pickup"][1],
            "delivery_lat": d["delivery"][0],
            "delivery_lon": d["delivery"][1],
            "distance": d["distance"],
            "price": d["price"],
            "payment": d["payment"],
            "note": d.get("note", ""),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )

    await update.message.reply_text(
        f"✅ <b>Buyurtma #{order_id} qabul qilindi!</b>\n\n"
        "Tez orada operatorimiz siz bilan bog'lanadi. Rahmat! 🚚",
        reply_markup=MAIN_MENU,
        parse_mode=ParseMode.HTML,
    )

    # Adminlarga xabar
    order = get_order(order_id)
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Qabul qilish", callback_data=f"ord:accepted:{order_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"ord:rejected:{order_id}"),
        ]]
    )
    for admin_id in [a for a in ADMIN_IDS if a != 0]:
        try:
            await context.bot.send_message(
                admin_id,
                "🔔 <b>Yangi buyurtma!</b>\n\n" + order_text(order, for_admin=True),
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning("Adminga (%s) xabar yuborilmadi: %s", admin_id, e)

    context.user_data.clear()
    return ConversationHandler.END


async def wrong_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Iltimos, olish manzilini lokatsiya sifatida yuboring (tugma yoki 📎 → Lokatsiya).",
        reply_markup=cancel_kb([KeyboardButton("📍 Olish manzilini yuborish", request_location=True)]),
    )
    return PICKUP


async def wrong_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Iltimos, yetkazish manzilini lokatsiya sifatida yuboring (tugma yoki 📎 → Lokatsiya).",
        reply_markup=cancel_kb([KeyboardButton("📍 Yetkazish manzilini yuborish", request_location=True)]),
    )
    return DELIVERY


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Buyurtma bekor qilindi. Yangi buyurtma uchun tugmani bosing.",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


# ----------------------------- ADMIN -----------------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return

    _, status, oid = query.data.split(":")
    order = get_order(int(oid))
    if not order:
        await query.answer("Buyurtma topilmadi", show_alert=True)
        return
    if order["status"] != "new":
        await query.answer(f"Allaqachon: {STATUS_TEXT.get(order['status'])}", show_alert=True)
        return

    set_status(order["id"], status)
    await query.answer(STATUS_TEXT[status])
    order = get_order(order["id"])
    await query.edit_message_text(
        "🔔 <b>Buyurtma</b>\n\n" + order_text(order, for_admin=True),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    try:
        msg = (
            f"✅ Buyurtmangiz #{order['id']} qabul qilindi. Tez orada kuryer yo'lga chiqadi!"
            if status == "accepted"
            else f"❌ Afsus, buyurtmangiz #{order['id']} rad etildi. Iltimos, qayta urinib ko'ring."
        )
        await context.bot.send_message(order["user_id"], msg)
    except Exception as e:
        logger.warning("Mijozga xabar yuborilmadi: %s", e)


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    with db() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        await update.message.reply_text("Buyurtmalar yo'q.")
        return
    lines = [
        f"#{o['id']} | {STATUS_TEXT.get(o['status'])} | {fmt_money(o['price'])} | {esc(o['phone'])}"
        for o in rows
    ]
    await update.message.reply_text("📋 Oxirgi buyurtmalar:\n\n" + "\n".join(lines))


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE status='accepted'"
        ).fetchone()
        day = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders "
            "WHERE status='accepted' AND created_at LIKE ?",
            (today + "%",),
        ).fetchone()
        new = conn.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
    await update.message.reply_text(
        "📊 <b>Statistika</b>\n\n"
        f"Bugun: {day[0]} ta, {fmt_money(day[1])}\n"
        f"Jami qabul qilingan: {total[0]} ta, {fmt_money(total[1])}\n"
        f"Kutilayotgan: {new} ta",
        parse_mode=ParseMode.HTML,
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Xatolik:", exc_info=context.error)


# ----------------------------- ISHGA TUSHIRISH -----------------------------
def main() -> None:
    if not TOKEN or ":" not in TOKEN or " " in TOKEN:
        logger.error("bot.py tepasidagi TOKEN noto'g'ri yoki bo'sh. BotFather tokenini qo'shtirnoq ichiga yozing.")
        raise SystemExit(1)
    if not any(ADMIN_IDS):
        logger.warning("ADMIN_IDS yozilmagan (bot.py tepasida): buyurtma xabarlari hech kimga yuborilmaydi!")
    init_db()
    app = Application.builder().token(TOKEN).build()

    text_only = filters.TEXT & ~filters.COMMAND & ~CANCEL_FILTER

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("order", order_start),
            MessageHandler(filters.Regex(f"^{re.escape(BTN_NEW)}$"), order_start),
        ],
        states={
            PICKUP: [MessageHandler(filters.LOCATION, pickup_location),
                     MessageHandler(text_only, wrong_pickup)],
            DELIVERY: [MessageHandler(filters.LOCATION, delivery_location),
                       MessageHandler(text_only, wrong_delivery)],
            PHONE: [MessageHandler(filters.CONTACT, phone_contact),
                    MessageHandler(text_only, phone_text)],
            NOTE: [MessageHandler(text_only, note_received)],
            PAYMENT: [MessageHandler(text_only, payment_method)],
            CONFIRM: [MessageHandler(text_only, confirm_order)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(CANCEL_FILTER, cancel),
            CommandHandler("start", start),
            CommandHandler("order", order_start),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tariff", tariff))
    app.add_handler(CommandHandler("myorders", my_orders))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_MY)}$"), my_orders))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_TARIFF)}$"), tariff))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^ord:"))
    app.add_error_handler(error_handler)

    logger.info("Bot ishga tushmoqda...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
