# 📦 MMM Analytics Bot & Mini App — Bulutli Ombor va Savdo Tahlili

**MMM Analytics Bot** — Telegram guruhlaridagi savdo, kirim, chiqim va to'lov xabarlarini AI (Google Gemini) yordamida avtomatik o'qib, tahlil qilib boruvchi, mijozlar qarz daftari (CRM ledger) va zamonaviy **Telegram Mini App** interfeysiga ega professional platforma.

---

## 🌟 Asosiy Imkoniyatlar

1. **Naqd va Nasiya savdoni avtomatik ajratish**:
   - Mijoz ismi ko'rsatilgan savdolar avtomatik **Nasiya** sifatida qabul qilinadi va mijoz qarz balansiga qo'shiladi.
   - Mijoz ismi ko'rsatilmagan savdolar (masalan: *"2ta olmanok 170 dan"*) avtomatik **Naqd** savdo sifatida qayd etiladi.
2. **3 ta Nol Qoidasi (Avtomatik Narxlash)**:
   - Agar narx 1000 dan kichik yozilsa (masalan: `170`, `175`, `65`), bot uning oxiriga 3 ta nol qo'shib o'qiydi (`170,000`, `175,000`, `65,000`).
3. **Pul Keldi / To'lovlar va Dollar Konvertatsiyasi**:
   - Mijoz to'lovlari (masalan: *"Ali aka 100$ berdi"* yoki *"Vali 500000 to'ladi"*) alohida to'lovlar reestriga yoziladi va mijozning nasiya qarzidan ayirib tashlanadi.
   - Xabarda dollar summasi bo'lsa (masalan: `(100$)`, `$50`), Markaziy Bankning (CBU) jonli kursi bo'yicha so'mga aylantiriladi.
4. **Mijozlar Bazasi (CRM Ledger)**:
   - Har bir mijozning umumiy nasiyasi, umumiy to'lagan pullari va joriy qarz balansi avtomatik yuritiladi.
5. **Zamonaviy Telegram Mini App**:
   - Chiroyli Dark Glassmorphism dizayni.
   - Dinamik Chart.js grafiklari va diagrammalari.
   - 4 ta toifa: Boshqaruv paneli (Dashboard), Naqd, Nasiya, Pul Keldi va Mijozlar Bazasi.
   - Jonli Markaziy Bank USD kursi vidjeti.
   - Mini App orqali yangi yozuv qo'shish va Excel yuklab olish.
6. **Xotirada (In-Memory) Excel Eksporti**:
   - Server diskida fayl to'planib qolmaydi — Excel hisobotlar to'g'ridan-to'g'ri operativ xotirada (`io.BytesIO`) shakllanib jo'natiladi.
7. **Bulutga Tayyor Me'morchilik (Cloud-Ready Architecture)**:
   - **Baza**: Turso Cloud Database (libSQL) yoki zaxira lokal SQLite.
   - **Xosting**: Koyeb (Docker orqali bepul, uzluksiz ishlaydi).
   - **Dual Rejim**: Polling yoki Serverless Webhook.

---

## 📁 Loyiha Tuzilmasi

```
telegram_warehouse_bot/
├── config.py             # Konfiguratsiya va atrof-muhit o'zgaruvchilari
├── database.py           # Turso / SQLite birlashgan ma'lumotlar bazasi qatlami
├── currency.py           # Markaziy Bank (CBU) jonli valyuta kursi servisi
├── ai_parser.py          # Google Gemini AI orqali xabarlarni tahlil qilish
├── excel_export.py       # In-memory Excel (.xlsx) hisobot generatori
├── webapp.py             # Flask Web API, /health va Mini App backend
├── main.py               # Bot va veb-serverni birlashtiruvchi markaziy yadro
├── Dockerfile            # Koyeb va Docker konteyner fayli
├── koyeb.yaml            # Koyeb bulut xosting konfiguratsiyasi
├── requirements.txt      # Mos va sinovdan o'tgan kutubxonalar ro'yxati
├── .env.example          # Konfiguratsiya namunasi
├── static/
│   └── index.html        # Telegram Mini App (Chart.js, Glassmorphism SPA)
└── scripts/
    ├── test_suite.py     # 6 bosqichli avtomatlashtirilgan testlar
    ├── backup_db.py      # JSON va SQLite zaxira nusxa olish skripti
    └── migrate_to_turso.py # Lokal bazani Turso Cloud ga o'tkazish skripti
```

---

## 🧪 Avtomatlashtirilgan Testlar

Loyiha to'liq sinovdan o'tkazilgan. Testlarni ishga tushirish uchun:

```bash
python scripts/test_suite.py
```

Test natijalari:
- ✅ **1. Database Repository & libSQL driver**: PASSED
- ✅ **2. Mijozlar Bazasi (CRM Ledger) hisob-kitobi**: PASSED
- ✅ **3. AI Parser (Naqd, Nasiya, 3 ta nol, Dollar qoidalari)**: PASSED
- ✅ **4. CBU Currency Service (Jonli USD kursi)**: PASSED
- ✅ **5. In-Memory Excel Generation**: PASSED
- ✅ **6. Flask Web API & /health Check**: PASSED

---

## 💾 Ma'lumotlar Bazasini Zaxiralash (Backup)

Barcha yozuvlar va mijozlar balansini istalgan vaqtda JSON va SQLite formatida zaxiralash:

```bash
python scripts/backup_db.py
```
Zaxira nusxalar `backups/` papkasiga vaqt tamg'asi bilan saqlanadi.

---

## ☁️ Koyeb va Turso orqali 24/7 Bepul Bulutga Joylash

### 1-bosqich: Turso Cloud Ma'lumotlar Bazasini Sozlash (Bepul)
1. [turso.tech](https://turso.tech) saytida bepul ro'yxatdan o'ting.
2. Yangi baza yarating:
   ```bash
   turso db create mmm-analytics
   turso db show mmm-analytics --url
   turso db tokens create mmm-analytics
   ```
3. Olingan `libsql://...` URL va Auth Tokenni `.env` ga kiriting.
4. Lokal ma'lumotlarni Turso ga o'tkazish uchun skriptni ishga tushiring:
   ```bash
   python scripts/migrate_to_turso.py
   ```

### 2-bosqich: Koyeb da Ishga Tushirish (Bepul)
1. Ushbu loyihani shaxsiy GitHub hisobingizga yuklang (`git push origin main`).
2. [koyeb.com](https://koyeb.com) da bepul ro'yxatdan o'ting.
3. **Create App** -> **GitHub** -> Repozitariyingizni tanlang.
4. **Builder**: `Dockerfile` avtomatik tanlanadi.
5. **Instance**: `nano` (bepul).
6. **Environment Variables** bo'limida quyidagilarni kiriting:
   - `BOT_TOKEN`: Sizning bot tokeningiz
   - `GEMINI_API_KEY`: Google Gemini API kaliti
   - `ADMIN_IDS`: `6656667725`
   - `TURSO_DATABASE_URL`: `libsql://mmm-analytics-...turso.io`
   - `TURSO_AUTH_TOKEN`: Turso tokeningiz
   - `NOTIFY_IN_GROUP`: `false`
   - `BOT_MODE`: `polling`
7. **Deploy** tugmasini bosing!
8. Koyeb bergan bepul HTTPS domenini (masalan: `https://mmm-analytics-xyz.koyeb.app`) Telegram @BotFather orqali botingizning **Menu Button** (Mini App) URL manziliga qo'ying!

---

## 🔄 Tiklash va Rollback Jarayoni (Recovery)

Agar bulut bazada muammo yuzaga kelsa yoki lokal rejimga qaytish kerak bo'lsa:
1. `.env` faylida `TURSO_DATABASE_URL` parametrini bo'sh qoldiring — bot darhol lokal `warehouse.db` ga o'tadi.
2. Zaxira nusxani tiklash uchun `backups/` papkasidagi oxirgi `.db` faylini `warehouse.db` deb qayta nomlang.
3. Botni qayta ishga tushiring: `python main.py`.
