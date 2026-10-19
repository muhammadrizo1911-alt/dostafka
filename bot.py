import os
import logging
from math import radians, cos, sin, asin, sqrt

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# States
PICKUP, DELIVERY, PAYMENT = range(3)

# Token (Railway yoki .env dan olinadi)
TOKEN = os.getenv("BOT_TOKEN")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi masofani metrlarda hisoblaydi (Haversine)."""
    R = 6371000  # Yer radiusi (metr)

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))

    return R * c


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botni boshlash va birinchi lokatsiyani so'rash."""
    user = update.effective_user
    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 🚚\n\n"
        "Dostavka xizmatiga xush kelibsiz!\n\n"
        "📦 Buyurtmani **qayerdan** olishimiz kerak?\n"
        "Pastdagi tugma orqali lokatsiyangizni yuboring.",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Olish manzilini yuborish", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
        parse_mode="Markdown",
    )
    return PICKUP


async def pickup_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Olish manzilini qabul qilish."""
    location = update.message.location
    if not location:
        await update.message.reply_text(
            "Iltimos, lokatsiya yuboring (tugmadan foydalaning)."
        )
        return PICKUP

    context.user_data["pickup"] = (location.latitude, location.longitude)

    await update.message.reply_text(
        "✅ Olish manzili qabul qilindi!\n\n"
        "📦 Endi buyurtmani **qayerga** yetkazishimiz kerak?\n"
        "Pastdagi tugma orqali yetkazish manzilini yuboring.",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Yetkazish manzilini yuborish", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
        parse_mode="Markdown",
    )
    return DELIVERY


async def delivery_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Yetkazish manzilini qabul qilish va hisob-kitob qilish."""
    location = update.message.location
    if not location:
        await update.message.reply_text(
            "Iltimos, lokatsiya yuboring (tugmadan foydalaning)."
        )
        return DELIVERY

    context.user_data["delivery"] = (location.latitude, location.longitude)

    lat1, lon1 = context.user_data["pickup"]
    lat2, lon2 = context.user_data["delivery"]

    distance = haversine(lat1, lon1, lat2, lon2)  # metr
    # Har 200 metrga 600 so'm
    price = (distance / 200) * 600
    price = round(price)  # butun songa yaxlitlash

    context.user_data["distance"] = distance
    context.user_data["price"] = price

    text = (
        "📊 **Hisob-kitob natijasi:**\n\n"
        f"📏 Masofa: **{distance:.0f}** metr\n"
        f"💰 Tarif: har 200 metrga **600 so'm**\n"
        f"💵 **Jami to'lov: {price} so'm**\n\n"
        "To'lov usulini tanlang:"
    )

    keyboard = ReplyKeyboardMarkup(
        [["💳 Karta", "💵 Naqd pul"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    return PAYMENT


async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """To'lov usulini qabul qilish va buyurtmani yakunlash."""
    method = update.message.text.strip()

    if method not in ["💳 Karta", "💵 Naqd pul"]:
        await update.message.reply_text(
            "Iltimos, faqat tugmalardan birini tanlang:\n💳 Karta yoki 💵 Naqd pul"
        )
        return PAYMENT

    price = context.user_data.get("price", 0)
    distance = context.user_data.get("distance", 0)

    await update.message.reply_text(
        "✅ **Buyurtma qabul qilindi!**\n\n"
        f"📏 Masofa: {distance:.0f} metr\n"
        f"💵 Summa: **{price} so'm**\n"
        f"💳 To'lov usuli: **{method}**\n\n"
        "Tez orada operatorimiz siz bilan bog'lanadi.\n"
        "Rahmat! 🚚",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )

    # Bu yerda admin chat_id ga xabar yuborish mumkin (keyinroq qo'shishingiz mumkin)
    # Masalan: await context.bot.send_message(chat_id=ADMIN_ID, text=...)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Buyurtmani bekor qilish."""
    await update.message.reply_text(
        "Buyurtma bekor qilindi. Qayta boshlash uchun /start bosing.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Yordam."""
    await update.message.reply_text(
        "🚚 **Dostavka bot**\n\n"
        "/start — Yangi buyurtma berish\n"
        "/cancel — Buyurtmani bekor qilish\n"
        "/help — Yordam\n\n"
        "Bot sizdan olish va yetkazish manzilini so'raydi, "
        "masofani avtomatik hisoblaydi va narxni ko'rsatadi."
    )


def main() -> None:
    if not TOKEN:
        raise ValueError(
            "BOT_TOKEN topilmadi! Railway da Environment Variables ga "
            "BOT_TOKEN qo'shing yoki .env faylida saqlang."
        )

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PICKUP: [
                MessageHandler(filters.LOCATION, pickup_location),
            ],
            DELIVERY: [
                MessageHandler(filters.LOCATION, delivery_location),
            ],
            PAYMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, payment_method),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),  # qayta boshlash mumkin
        ],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))

    logger.info("Bot ishga tushmoqda...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
