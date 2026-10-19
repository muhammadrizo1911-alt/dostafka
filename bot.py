# =====================================================================
#                        SOZLAMALAR (QO'LDA YOZING)
# =====================================================================
TOKEN = "8877210409:AAGgaRlFve7ChlERphyNrRmKF038N4RVax0"   # BotFather tokeni
ADMIN_IDS = {5538156384}              # Telegram ID ingiz, masalan: {123456789}  (bir nechta: {111, 222})

STEP_METERS = 100            # har necha metrga
STEP_PRICE = 600             # necha so'm
MIN_PRICE = 3000             # minimal narx (so'm)
ROAD_FACTOR = 1.3            # to'g'ri chiziq -> yo'l koeffitsienti
MAX_DISTANCE_KM = 50         # maksimal masofa (km)
DB_PATH = "orders.db"        # Railway Volume bo'lsa: "/data/orders.db"

# True  = yangi buyurtma darhol barcha haydovchilarga ketadi (admin faqat xabar oladi)
# False = avval admin «Qabul qilish» ni bosadi, shundan keyin haydovchilarga ketadi
AUTO_DISPATCH = True
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

HTML = ParseMode.HTML

# ----------------------------- HOLATLAR -----------------------------
PICKUP, DELIVERY, PHONE, NOTE, PAYMENT, CONFIRM = range(6)
D_ID, D_NAME = range(6, 8)

# ----------------------------- TUGMALAR -----------------------------
BTN_NEW = "🚚 Yangi buyurtma"
BTN_MY = "📋 Buyurtmalarim"
BTN_TARIFF = "💰 Tariflar"
BTN_CANCEL = "❌ Bekor qilish"
BTN_SKIP = "⏭ O'tkazib yuborish"
BTN_CARD = "💳 Karta"
BTN_CASH = "💵 Naqd pul"
BTN_CONFIRM = "✅ Tasdiqlash"
BTN_ADMIN = "🛠 Admin panel"
BTN_DRV_OPEN = "📥 Bo'sh buyurtmalar"
BTN_DRV_MINE = "🚛 Mening ishlarim"

CANCEL_FILTER = filters.Regex(f"^{re.escape(BTN_CANCEL)}$")

STATUS_TEXT = {
    "new": "🕐 Kutilmoqda",
    "accepted": "🔎 Haydovchi qidirilmoqda",
    "assigned": "🚚 Haydovchi yo'lda",
    "delivered": "🏁 Yetkazildi",
    "rejected": "❌ Rad etildi",
    "cancelled": "🚫 Bekor qilindi",
}

ORDER_SELECT = (
    "SELECT o.*, d.name AS driver_name, d.phone AS driver_phone "
    "FROM orders o LEFT JOIN drivers d ON d.user_id = o.driver_id "
)


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
                created_at TEXT,
                driver_id INTEGER
            )
            """
        )
        try:  # eski bazalar uchun
            conn.execute("ALTER TABLE orders ADD COLUMN driver_id INTEGER")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drivers (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                phone TEXT,
                active INTEGER DEFAULT 1,
                added_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch (
                order_id INTEGER,
                chat_id INTEGER,
                message_id INTEGER
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
        return conn.execute(ORDER_SELECT + "WHERE o.id = ?", (order_id,)).fetchone()


def set_status(order_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))


def add_driver(user_id: int, name: str, phone: str | None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO drivers (user_id, name, phone, active, added_at) VALUES (?,?,?,1,?)",
            (user_id, name, phone, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )


def remove_driver(user_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM drivers WHERE user_id = ?", (user_id,))


def list_drivers():
    with db() as conn:
        return conn.execute("SELECT * FROM drivers WHERE active = 1 ORDER BY name").fetchall()


def is_driver(user_id: int) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM drivers WHERE user_id = ? AND active = 1", (user_id,)
        ).fetchone() is not None


def save_dispatch(order_id: int, chat_id: int, message_id: int) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO dispatch (order_id, chat_id, message_id) VALUES (?,?,?)",
            (order_id, chat_id, message_id),
        )


def get_dispatch(order_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT chat_id, message_id FROM dispatch WHERE order_id = ?", (order_id,)
        ).fetchall()


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


def real_admins() -> list[int]:
    return [a for a in ADMIN_IDS if a != 0]


def menu_for(user_id: int) -> ReplyKeyboardMarkup:
    rows = [[BTN_NEW], [BTN_MY, BTN_TARIFF]]
    if is_driver(user_id):
        rows.append([BTN_DRV_OPEN, BTN_DRV_MINE])
    if is_admin(user_id):
        rows.append([BTN_ADMIN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def cancel_kb(*extra_rows) -> ReplyKeyboardMarkup:
    rows = list(extra_rows) + [[BTN_CANCEL]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def order_text(o, mode: str = "customer") -> str:
    """mode: customer | admin | driver_preview | driver"""
    lines = [
        f"📦 <b>Buyurtma #{o['id']}</b>",
        f"📊 Holat: {STATUS_TEXT.get(o['status'], o['status'])}",
    ]
    if mode in ("admin", "driver"):
        who = f"👤 {esc(o['full_name'])}"
        if mode == "admin" and o["username"]:
            who += f" (@{esc(o['username'])})"
        lines.append(who)
    if mode != "driver_preview":
        lines.append(f"📞 {esc(o['phone'])}")
    lines += [
        f"📍 <a href=\"{map_link(o['pickup_lat'], o['pickup_lon'])}\">Olish manzili</a>",
        f"🏁 <a href=\"{map_link(o['delivery_lat'], o['delivery_lon'])}\">Yetkazish manzili</a>",
        f"📏 Masofa: {fmt_distance(o['distance'])}",
        f"💵 Summa: <b>{fmt_money(o['price'])}</b>",
        f"💳 To'lov: {esc(o['payment'])}",
    ]
    if o["note"]:
        lines.append(f"📝 Izoh: {esc(o['note'])}")
    if o["driver_id"] and mode in ("customer", "admin"):
        drv = f"🚚 Haydovchi: {esc(o['driver_name'])}"
        if o["driver_phone"]:
            drv += f", {esc(o['driver_phone'])}"
        lines.append(drv)
    lines.append(f"🕒 {o['created_at']}")
    return "\n".join(lines)


async def notify_admins(context, text: str, kb=None) -> None:
    for admin_id in real_admins():
        try:
            await context.bot.send_message(
                admin_id, text, parse_mode=HTML, reply_markup=kb, disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning("Adminga (%s) xabar yuborilmadi: %s", admin_id, e)


async def notify_user(context, user_id: int, text: str) -> None:
    try:
        await context.bot.send_message(user_id, text, parse_mode=HTML)
    except Exception as e:
        logger.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", user_id, e)


def take_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚚 Buyurtmani olish", callback_data=f"drv:take:{order_id}")]]
    )


def done_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏁 Yetkazildi", callback_data=f"drv:done:{order_id}")]]
    )


async def dispatch_order(context, order_id: int) -> int:
    """Buyurtmani barcha faol haydovchilarga yuboradi. Nechta haydovchiga yetganini qaytaradi."""
    order = get_order(order_id)
    sent = 0
    for d in list_drivers():
        try:
            m = await context.bot.send_message(
                d["user_id"],
                "🔔 <b>Yangi buyurtma!</b>\n\n" + order_text(order, "driver_preview"),
                parse_mode=HTML,
                reply_markup=take_kb(order_id),
                disable_web_page_preview=True,
            )
            save_dispatch(order_id, d["user_id"], m.message_id)
            sent += 1
        except Exception as e:
            logger.warning("Haydovchiga (%s) yuborilmadi: %s", d["user_id"], e)
    return sent


async def close_dispatch(context, order_id: int, text: str, skip=None) -> None:
    """Haydovchilarga yuborilgan xabarlarni yopadi (tugmasiz matn qoladi)."""
    for row in get_dispatch(order_id):
        if skip and (row["chat_id"], row["message_id"]) == skip:
            continue
        try:
            await context.bot.edit_message_text(
                text, chat_id=row["chat_id"], message_id=row["message_id"]
            )
        except Exception:
            pass


# ----------------------------- ASOSIY BUYRUQLAR -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user = update.effective_user
    extra = ""
    if is_driver(user.id):
        extra = "\n\n🚛 Siz haydovchisiz: yangi buyurtmalar shu yerga keladi."
    if is_admin(user.id):
        extra += "\n\n🛠 Siz adminsiz: «Admin panel» tugmasi orqali haydovchilarni boshqaring."
    await update.message.reply_text(
        f"Assalomu alaykum, {esc(user.first_name)}! 🚚\n\n"
        "Dostavka xizmatiga xush kelibsiz!\n"
        "Buyurtma berish uchun pastdagi tugmani bosing." + extra,
        reply_markup=menu_for(user.id),
        parse_mode=HTML,
    )
    return ConversationHandler.END


async def tariff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "💰 <b>Tariflar</b>\n\n"
        f"• Har {STEP_METERS} metrga: <b>{fmt_money(STEP_PRICE)}</b>\n"
        f"• Minimal narx: <b>{fmt_money(MIN_PRICE)}</b>\n"
        f"• Maksimal masofa: {MAX_DISTANCE_KM:.0f} km\n\n"
        "Masofa yo'l egriligini hisobga olgan holda hisoblanadi.",
        parse_mode=HTML,
        reply_markup=menu_for(update.effective_user.id),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = (
        "🚚 <b>Dostavka bot</b>\n\n"
        "/start — Bosh menyu\n"
        "/order — Yangi buyurtma\n"
        "/myorders — Mening buyurtmalarim\n"
        "/tariff — Tariflar\n"
        "/cancel — Joriy buyurtmani bekor qilish\n"
        "/help — Yordam"
    )
    if is_driver(uid):
        text += "\n\n🚛 <b>Haydovchi:</b>\n«📥 Bo'sh buyurtmalar» va «🚛 Mening ishlarim» tugmalari"
    if is_admin(uid):
        text += "\n\n👑 <b>Admin:</b>\n/admin — admin panel\n/orders — oxirgi buyurtmalar\n/stats — statistika"
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=menu_for(uid))


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with db() as conn:
        rows = conn.execute(
            ORDER_SELECT + "WHERE o.user_id = ? ORDER BY o.id DESC LIMIT 5", (uid,)
        ).fetchall()
    if not rows:
        await update.message.reply_text("Sizda hali buyurtmalar yo'q.", reply_markup=menu_for(uid))
        return
    for o in rows:
        await update.message.reply_text(order_text(o), parse_mode=HTML, disable_web_page_preview=True)


# ----------------------------- BUYURTMA JARAYONI -----------------------------
def pickup_btn():
    return [KeyboardButton("📍 Olish manzilini yuborish", request_location=True)]


def delivery_btn():
    return [KeyboardButton("📍 Yetkazish manzilini yuborish", request_location=True)]


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📦 Buyurtmani <b>qayerdan</b> olishimiz kerak?\n\n"
        "1️⃣ Hozirgi joyingiz bo'lsa — <b>«📍 Olish manzilini yuborish»</b> tugmasini bosing.\n"
        "2️⃣ Boshqa joy bo'lsa — 📎 (skrepka) → <b>Lokatsiya</b> → xaritada kerakli joyni belgilab, "
        "<b>«Tanlangan lokatsiyani yuborish»</b> ni bosing.",
        reply_markup=cancel_kb(pickup_btn()),
        parse_mode=HTML,
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
        reply_markup=cancel_kb(delivery_btn()),
        parse_mode=HTML,
    )
    return DELIVERY


async def delivery_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    lat1, lon1 = context.user_data["pickup"]
    distance = haversine(lat1, lon1, loc.latitude, loc.longitude)

    if distance < 50:
        await update.message.reply_text(
            "⚠️ Olish va yetkazish manzillari juda yaqin. Iltimos, yetkazish manzilini qayta yuboring.",
            reply_markup=cancel_kb(delivery_btn()),
        )
        return DELIVERY
    if distance * ROAD_FACTOR / 1000 > MAX_DISTANCE_KM:
        await update.message.reply_text(
            f"⚠️ Masofa juda uzoq (maksimum {MAX_DISTANCE_KM:.0f} km). "
            "Iltimos, boshqa manzil yuboring yoki /cancel bosing.",
            reply_markup=cancel_kb(delivery_btn()),
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
        parse_mode=HTML,
    )
    return PHONE


async def phone_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _save_phone(update, context, update.message.contact.phone_number)


async def phone_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    digits = re.sub(r"\D", "", update.message.text.strip())
    if len(digits) == 9:
        digits = "998" + digits
    if not (len(digits) == 12 and digits.startswith("998")):
        await update.message.reply_text(
            "⚠️ Raqam noto'g'ri. Misol: <code>+998901234567</code>", parse_mode=HTML
        )
        return PHONE
    return await _save_phone(update, context, "+" + digits)


async def _save_phone(update, context, phone: str) -> int:
    context.user_data["phone"] = phone if phone.startswith("+") else "+" + phone
    await update.message.reply_text(
        "📝 Buyurtma haqida izoh yozing (masalan: <i>«3-qavat, 12-xona, qo'ng'iroq qiling»</i>) "
        "yoki o'tkazib yuboring:",
        reply_markup=cancel_kb([BTN_SKIP]),
        parse_mode=HTML,
    )
    return NOTE


async def note_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["note"] = "" if text == BTN_SKIP else text[:300]
    await update.message.reply_text(
        "💳 To'lov usulini tanlang:", reply_markup=cancel_kb([BTN_CARD, BTN_CASH])
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
        parse_mode=HTML,
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
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ <b>Buyurtma #{order_id} qabul qilindi!</b>\n\n"
        + ("Haydovchi qidirilmoqda, tez orada xabar beramiz. 🚚" if AUTO_DISPATCH
           else "Tez orada operatorimiz siz bilan bog'lanadi. 🚚"),
        reply_markup=menu_for(user.id),
        parse_mode=HTML,
    )

    if AUTO_DISPATCH:
        set_status(order_id, "accepted")
        sent = await dispatch_order(context, order_id)
        order = get_order(order_id)
        info = (
            f"\n\n📤 {sent} ta haydovchiga yuborildi."
            if sent
            else "\n\n⚠️ <b>Haydovchilar yo'q yoki yuborilmadi!</b> Admin panel orqali haydovchi qo'shing."
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚫 Bekor qilish", callback_data=f"ord:cancelled:{order_id}")]]
        )
        await notify_admins(context, "🔔 <b>Yangi buyurtma!</b>\n\n" + order_text(order, "admin") + info, kb)
    else:
        order = get_order(order_id)
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Qabul qilish", callback_data=f"ord:accepted:{order_id}"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"ord:rejected:{order_id}"),
            ]]
        )
        await notify_admins(context, "🔔 <b>Yangi buyurtma!</b>\n\n" + order_text(order, "admin"), kb)

    return ConversationHandler.END


async def wrong_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Iltimos, olish manzilini lokatsiya sifatida yuboring (tugma yoki 📎 → Lokatsiya).",
        reply_markup=cancel_kb(pickup_btn()),
    )
    return PICKUP


async def wrong_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Iltimos, yetkazish manzilini lokatsiya sifatida yuboring (tugma yoki 📎 → Lokatsiya).",
        reply_markup=cancel_kb(delivery_btn()),
    )
    return DELIVERY


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Bekor qilindi. Davom etish uchun tugmalardan foydalaning.",
        reply_markup=menu_for(update.effective_user.id),
    )
    return ConversationHandler.END


# ----------------------------- ADMIN: BUYURTMALAR -----------------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return

    _, action, oid = query.data.split(":")
    order = get_order(int(oid))
    if not order:
        await query.answer("Buyurtma topilmadi", show_alert=True)
        return

    if action in ("accepted", "rejected") and order["status"] != "new":
        await query.answer(f"Allaqachon: {STATUS_TEXT.get(order['status'])}", show_alert=True)
        return
    if action == "cancelled" and order["status"] not in ("new", "accepted", "assigned"):
        await query.answer(f"Bekor qilib bo'lmaydi: {STATUS_TEXT.get(order['status'])}", show_alert=True)
        return

    set_status(order["id"], action)
    await query.answer(STATUS_TEXT[action])
    order = get_order(order["id"])
    kb = None
    extra = ""

    if action == "accepted":
        sent = await dispatch_order(context, order["id"])
        extra = (
            f"\n\n📤 {sent} ta haydovchiga yuborildi."
            if sent
            else "\n\n⚠️ <b>Haydovchilar yo'q yoki yuborilmadi!</b>"
        )
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚫 Bekor qilish", callback_data=f"ord:cancelled:{order['id']}")]]
        )
        await notify_user(context, order["user_id"],
                          f"✅ Buyurtmangiz #{order['id']} qabul qilindi. Haydovchi qidirilmoqda.")
    elif action == "rejected":
        await notify_user(context, order["user_id"],
                          f"❌ Afsus, buyurtmangiz #{order['id']} rad etildi. Iltimos, qayta urinib ko'ring.")
    else:  # cancelled
        await close_dispatch(context, order["id"], f"🚫 Buyurtma #{order['id']} bekor qilindi.")
        await notify_user(context, order["user_id"], f"🚫 Buyurtmangiz #{order['id']} bekor qilindi.")

    await query.edit_message_text(
        "🔔 <b>Buyurtma</b>\n\n" + order_text(order, "admin") + extra,
        parse_mode=HTML,
        reply_markup=kb,
        disable_web_page_preview=True,
    )


def orders_summary() -> str:
    with db() as conn:
        rows = conn.execute(ORDER_SELECT + "ORDER BY o.id DESC LIMIT 10").fetchall()
    if not rows:
        return "Buyurtmalar yo'q."
    lines = []
    for o in rows:
        drv = f" | 🚚 {esc(o['driver_name'])}" if o["driver_id"] and o["driver_name"] else ""
        lines.append(
            f"#{o['id']} | {STATUS_TEXT.get(o['status'])} | {fmt_money(o['price'])} | {esc(o['phone'])}{drv}"
        )
    return "📋 <b>Oxirgi buyurtmalar:</b>\n\n" + "\n".join(lines)


def stats_text() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE status='delivered'"
        ).fetchone()
        day = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders "
            "WHERE status='delivered' AND created_at LIKE ?",
            (today + "%",),
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('accepted','assigned')"
        ).fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
        drivers = conn.execute("SELECT COUNT(*) FROM drivers WHERE active=1").fetchone()[0]
    return (
        "📊 <b>Statistika</b>\n\n"
        f"Bugun yetkazilgan: {day[0]} ta, {fmt_money(day[1])}\n"
        f"Jami yetkazilgan: {total[0]} ta, {fmt_money(total[1])}\n"
        f"Jarayonda: {active} ta\n"
        f"Kutilayotgan (admin tasdig'i): {new} ta\n"
        f"Haydovchilar: {drivers} ta"
    )


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id):
        await update.message.reply_text(orders_summary(), parse_mode=HTML)


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id):
        await update.message.reply_text(stats_text(), parse_mode=HTML)


# ----------------------------- ADMIN PANEL -----------------------------
def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Haydovchi qo'shish", callback_data="adm:add")],
            [InlineKeyboardButton("👥 Haydovchilar", callback_data="adm:drivers")],
            [
                InlineKeyboardButton("📋 Buyurtmalar", callback_data="adm:orders"),
                InlineKeyboardButton("📊 Statistika", callback_data="adm:stats"),
            ],
        ]
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Sizda admin huquqi yo'q.\n"
            f"Sizning Telegram ID ingiz: <code>{update.effective_user.id}</code>\n"
            "Admin bo'lish uchun shu raqamni bot.py dagi ADMIN_IDS ga yozing.",
            parse_mode=HTML,
        )
        return
    await update.message.reply_text(
        "🛠 <b>Admin panel</b>", parse_mode=HTML, reply_markup=admin_panel_kb()
    )


def drivers_view():
    drivers = list_drivers()
    if not drivers:
        return "👥 Haydovchilar yo'q. «➕ Haydovchi qo'shish» orqali qo'shing.", None
    lines = [
        f"{i}. {esc(d['name'])}" + (f" — {esc(d['phone'])}" if d["phone"] else "")
        + f" (<code>{d['user_id']}</code>)"
        for i, d in enumerate(drivers, 1)
    ]
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🗑 {d['name']}", callback_data=f"adm:del:{d['user_id']}")] for d in drivers]
    )
    return "👥 <b>Haydovchilar:</b>\n\n" + "\n".join(lines) + "\n\nO'chirish uchun ismni bosing.", kb


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return
    await query.answer()
    parts = query.data.split(":")
    action = parts[1]

    if action == "drivers":
        text, kb = drivers_view()
        await query.message.reply_text(text, parse_mode=HTML, reply_markup=kb)
    elif action == "del":
        remove_driver(int(parts[2]))
        text, kb = drivers_view()
        await query.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
        await notify_user(context, int(parts[2]), "ℹ️ Siz haydovchilar ro'yxatidan chiqarildingiz.")
    elif action == "orders":
        await query.message.reply_text(orders_summary(), parse_mode=HTML)
    elif action == "stats":
        await query.message.reply_text(stats_text(), parse_mode=HTML)


# ----------------------------- ADMIN: HAYDOVCHI QO'SHISH -----------------------------
async def add_driver_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    await query.message.reply_text(
        "➕ <b>Haydovchi qo'shish</b>\n\n"
        "Quyidagilardan birini yuboring:\n"
        "• haydovchining <b>kontaktini</b> (📎 → Kontakt), yoki\n"
        "• haydovchining <b>Telegram ID</b> raqamini (u @userinfobot ga /start yuborib bilib oladi).\n\n"
        "⚠️ Haydovchi botga kamida bir marta /start bosgan bo'lishi kerak.",
        parse_mode=HTML,
        reply_markup=cancel_kb(),
    )
    return D_ID


async def _finish_add_driver(update, context, user_id: int, name: str, phone) -> int:
    add_driver(user_id, name, phone)
    notified = True
    try:
        await context.bot.send_message(
            user_id,
            "🚛 Siz <b>haydovchi</b> sifatida qo'shildingiz!\n"
            "Yangi buyurtmalar shu yerga keladi. Menyuni yangilash uchun /start bosing.",
            parse_mode=HTML,
            reply_markup=menu_for(user_id),
        )
    except Exception:
        notified = False
    msg = f"✅ Haydovchi qo'shildi: <b>{esc(name)}</b> (<code>{user_id}</code>)"
    if not notified:
        msg += "\n\n⚠️ Unga xabar yuborib bo'lmadi: haydovchi botga /start bosishi kerak."
    await update.message.reply_text(msg, parse_mode=HTML, reply_markup=menu_for(update.effective_user.id))
    context.user_data.pop("new_driver_id", None)
    return ConversationHandler.END


async def add_driver_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    c = update.message.contact
    if not c.user_id:
        await update.message.reply_text(
            "Bu kontakt Telegram foydalanuvchisi emas. Telegram ID raqamini yuboring."
        )
        return D_ID
    name = " ".join(x for x in [c.first_name, c.last_name] if x)
    return await _finish_add_driver(update, context, c.user_id, name, c.phone_number)


async def add_driver_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Faqat raqam (Telegram ID) yoki kontakt yuboring.")
        return D_ID
    context.user_data["new_driver_id"] = int(text)
    await update.message.reply_text("Haydovchining ismini yozing:", reply_markup=cancel_kb())
    return D_NAME


async def add_driver_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()[:60]
    return await _finish_add_driver(update, context, context.user_data["new_driver_id"], name, None)


# ----------------------------- HAYDOVCHI -----------------------------
async def driver_open_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_driver(uid):
        return
    with db() as conn:
        rows = conn.execute(
            ORDER_SELECT + "WHERE o.status = 'accepted' AND o.driver_id IS NULL ORDER BY o.id DESC LIMIT 10"
        ).fetchall()
    if not rows:
        await update.message.reply_text("📭 Hozircha bo'sh buyurtmalar yo'q.")
        return
    for o in rows:
        m = await update.message.reply_text(
            order_text(o, "driver_preview"),
            parse_mode=HTML,
            reply_markup=take_kb(o["id"]),
            disable_web_page_preview=True,
        )
        save_dispatch(o["id"], uid, m.message_id)


async def driver_my_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not is_driver(uid):
        return
    with db() as conn:
        rows = conn.execute(
            ORDER_SELECT + "WHERE o.driver_id = ? AND o.status = 'assigned' ORDER BY o.id DESC", (uid,)
        ).fetchall()
        done = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE driver_id = ? AND status = 'delivered'",
            (uid,),
        ).fetchone()
    await update.message.reply_text(
        f"🏁 Yetkazgan buyurtmalaringiz: <b>{done[0]}</b> ta, jami {fmt_money(done[1])}",
        parse_mode=HTML,
    )
    if not rows:
        await update.message.reply_text("Faol buyurtmalaringiz yo'q.")
        return
    for o in rows:
        await update.message.reply_text(
            order_text(o, "driver"),
            parse_mode=HTML,
            reply_markup=done_kb(o["id"]),
            disable_web_page_preview=True,
        )


async def driver_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    if not is_driver(uid):
        await query.answer("Siz haydovchi emassiz", show_alert=True)
        return

    _, action, oid = query.data.split(":")
    oid = int(oid)

    if action == "take":
        with db() as conn:
            cur = conn.execute(
                "UPDATE orders SET driver_id = ?, status = 'assigned' "
                "WHERE id = ? AND status = 'accepted' AND driver_id IS NULL",
                (uid, oid),
            )
            ok = cur.rowcount == 1
        if not ok:
            await query.answer("Bu buyurtma allaqachon olingan yoki bekor qilingan", show_alert=True)
            try:
                await query.edit_message_text(f"⛔ Buyurtma #{oid} endi mavjud emas.")
            except Exception:
                pass
            return

        await query.answer("✅ Buyurtma sizniki!")
        order = get_order(oid)
        await query.edit_message_text(
            "🚛 <b>Buyurtma sizga biriktirildi</b>\n\n" + order_text(order, "driver"),
            parse_mode=HTML,
            reply_markup=done_kb(oid),
            disable_web_page_preview=True,
        )
        await close_dispatch(
            context, oid, f"⛔ Buyurtma #{oid} boshqa haydovchi tomonidan olindi.",
            skip=(query.message.chat_id, query.message.message_id),
        )
        drv = f"<b>{esc(order['driver_name'])}</b>" + (f", {esc(order['driver_phone'])}" if order["driver_phone"] else "")
        await notify_user(context, order["user_id"],
                          f"🚚 Buyurtmangiz #{oid} uchun haydovchi topildi: {drv}. U yo'lga chiqdi!")
        await notify_admins(context, f"🚚 Haydovchi {drv} buyurtma #{oid} ni oldi.")

    elif action == "done":
        order = get_order(oid)
        if not order or order["driver_id"] != uid or order["status"] != "assigned":
            await query.answer("Bu buyurtmani yakunlab bo'lmaydi", show_alert=True)
            return
        set_status(oid, "delivered")
        await query.answer("🏁 Yetkazildi deb belgilandi")
        order = get_order(oid)
        await query.edit_message_text(
            "🏁 <b>Yetkazildi</b>\n\n" + order_text(order, "driver"),
            parse_mode=HTML,
            disable_web_page_preview=True,
        )
        await notify_user(context, order["user_id"],
                          f"🏁 Buyurtmangiz #{oid} yetkazildi. Rahmat, yana kutamiz! 🚚")
        await notify_admins(context, f"🏁 Buyurtma #{oid} yetkazildi ({esc(order['driver_name'])}).")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Xatolik:", exc_info=context.error)


# ----------------------------- ISHGA TUSHIRISH -----------------------------
def main() -> None:
    if not TOKEN or ":" not in TOKEN or " " in TOKEN:
        logger.error("bot.py tepasidagi TOKEN noto'g'ri yoki bo'sh. BotFather tokenini qo'shtirnoq ichiga yozing.")
        raise SystemExit(1)
    if not real_admins():
        logger.warning("ADMIN_IDS yozilmagan (bot.py tepasida): admin panel va xabarlar ishlamaydi!")
    init_db()
    app = Application.builder().token(TOKEN).build()

    text_only = filters.TEXT & ~filters.COMMAND & ~CANCEL_FILTER
    cancel_fallbacks = [
        CommandHandler("cancel", cancel),
        MessageHandler(CANCEL_FILTER, cancel),
        CommandHandler("start", start),
    ]

    order_conv = ConversationHandler(
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
        fallbacks=cancel_fallbacks + [CommandHandler("order", order_start)],
        allow_reentry=True,
    )

    driver_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_driver_start, pattern=r"^adm:add$")],
        states={
            D_ID: [MessageHandler(filters.CONTACT, add_driver_contact),
                   MessageHandler(text_only, add_driver_id)],
            D_NAME: [MessageHandler(text_only, add_driver_name)],
        },
        fallbacks=cancel_fallbacks,
        allow_reentry=True,
    )

    app.add_handler(order_conv)
    app.add_handler(driver_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tariff", tariff))
    app.add_handler(CommandHandler("myorders", my_orders))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_MY)}$"), my_orders))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_TARIFF)}$"), tariff))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_ADMIN)}$"), admin_panel))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_DRV_OPEN)}$"), driver_open_orders))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BTN_DRV_MINE)}$"), driver_my_jobs))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^ord:"))
    app.add_handler(CallbackQueryHandler(driver_callback, pattern=r"^drv:"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^adm:(drivers|orders|stats|del:\d+)$"))
    app.add_error_handler(error_handler)

    logger.info("Bot ishga tushmoqda...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
