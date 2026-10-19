# 🚚 Dostavka Bot (Telegram)

Mijoz uchun oddiy va qulay **dostavka bot**.

## Nima qiladi?

1. Salomlashadi
2. **Olish manzilini** so'raydi (Telegram lokatsiya)
3. **Yetkazish manzilini** so'raydi (Telegram lokatsiya)
4. Masofani avtomatik hisoblaydi
5. Narxni hisoblaydi: **har 200 metrga 600 so'm**
6. To'liq hisob-kitobni ko'rsatadi
7. To'lov usulini tanlash imkonini beradi: **Karta** yoki **Naqd pul**

---

## Lokal ishga tushirish

1. Python 3.10+ o'rnatilgan bo'lishi kerak
2. Kutubxonalarni o'rnating:

```bash
pip install -r requirements.txt
```

3. `.env` fayl yarating (`.env.example` dan nusxa oling):

```bash
cp .env.example .env
```

4. `.env` ichiga BotFather dan olgan tokeningizni yozing:

```
BOT_TOKEN=1234567890:ABCdef...
```

5. Botni ishga tushiring:

```bash
python bot.py
```

---

## Railway.com ga yuklash (online ishlashi uchun)

### 1. GitHub ga joylash

1. Yangi repository yarating (masalan: `dostavka-bot`)
2. Shu papkadagi barcha fayllarni yuklang (yoki `git push` qiling)
3. Repository public yoki private bo'lishi mumkin

### 2. Railway da deploy qilish

1. [railway.com](https://railway.com) ga kiring
2. **New Project** → **Deploy from GitHub repo** ni tanlang
3. O'z GitHub reposingizni tanlang
4. Railway avtomatik Python ni aniqlaydi

### 3. Environment Variable qo'shing

1. Project ichida **Variables** bo'limiga kiring
2. Yangi variable qo'shing:
   - **Name:** `BOT_TOKEN`
   - **Value:** BotFather dan olgan tokeningiz

### 4. Start Command

Railway odatda avtomatik ishlaydi. Agar kerak bo'lsa, Settings → Deploy da:

```
python bot.py
```

yoki `Procfile` dagi `worker: python bot.py` ishlatiladi.

### 5. Deploy

Deploy tugagach bot onlayn ishlay boshlaydi. Telegramda `/start` bosing va sinab ko'ring.

---

## BotFather orqali bot yaratish

1. Telegramda [@BotFather](https://t.me/BotFather) ni oching
2. `/newbot` yuboring
3. Botga nom bering (masalan: `Mening Dostavka Botim`)
4. Username bering (masalan: `mening_dostavka_bot`)
5. Sizga **token** beradi — uni Railway Variables ga qo'ying

---

## Texnik ma'lumot

- **Kutubxona:** `python-telegram-bot` 21.x
- **Masofa hisoblash:** Haversine formulasi
- **Narx:** `(masofa_metr / 200) * 600` so'm
- **Holatlar:** ConversationHandler (PICKUP → DELIVERY → PAYMENT)

---

## Keyingi qo'shimchalar (ixtiyoriy)

- Admin chat_id ga buyurtma haqida xabar yuborish
- Buyurtmalar tarixini saqlash (SQLite / PostgreSQL)
- Minimal narx qo'shish
- Vaqt bo'yicha cheklovlar

---

Yaratuvchi: Grok yordamida tayyorlandi 😊
