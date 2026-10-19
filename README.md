# 🚚 Dostavka Bot (Telegram)

Lokatsiya orqali masofa va narxni hisoblaydigan, buyurtmalarni adminga yuboradigan dostavka bot.

## Imkoniyatlar
- Bosh menyu: Yangi buyurtma, Buyurtmalarim, Tariflar
- Olish va yetkazish lokatsiyasi (tugma yoki xaritadan tanlash)
- Narx: har 200 m ga 600 so'm, yo'l koeffitsienti (1.3), 100 so'mga yaxlitlash, minimal narx
- Telefon raqam (kontakt tugmasi yoki yozib), izoh, to'lov usuli
- Buyurtmani tasdiqlashdan oldin tekshirish
- Buyurtmalar SQLite bazada saqlanadi
- Adminga xabar + «Qabul qilish / Rad etish» tugmalari, mijozga avtomatik javob
- Admin buyruqlari: `/orders`, `/stats`
- Har bosqichda «Bekor qilish» tugmasi

## Sozlamalar (.env yoki Railway Variables)
| Nom | Izoh |
|---|---|
| `BOT_TOKEN` | BotFather tokeni (majburiy) |
| `ADMIN_IDS` | Admin Telegram ID lari, vergul bilan |
| `STEP_METERS`, `STEP_PRICE` | Tarif (200 m / 600 so'm) |
| `MIN_PRICE` | Minimal narx |
| `ROAD_FACTOR` | To'g'ri chiziq → yo'l koeffitsienti |
| `MAX_DISTANCE_KM` | Maksimal masofa |

## Lokal ishga tushirish
```bash
pip install -r requirements.txt
cp .env.example .env   # tokenni yozing
python bot.py
```

## Railway ga yuklash
1. Kodni GitHub ga yuklang (`.env` yuklanmaydi — `.gitignore` da)
2. Railway → New Project → Deploy from GitHub repo
3. Variables ga `BOT_TOKEN` va `ADMIN_IDS` ni qo'shing
4. Buyurtmalar bazasi saqlanib qolishi uchun Railway da **Volume** qo'shing (masalan `/data`) va `DB_PATH=/data/orders.db` qiling. Aks holda har deploy da baza tozalanadi.
