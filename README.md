<div align="center">

# Eris Tunnel

**پنل وب مدیریت تانل SSH و Backhaul**
_A web panel for managing SSH and Backhaul tunnels_

[![License: MIT](https://img.shields.io/badge/License-MIT-7c5cff.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8%2B-22d3ee)
![Platform](https://img.shields.io/badge/platform-Linux%20%2B%20systemd-34d399)

</div>

---

## نصب تک‌دستوری / One-command install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/eris4444/eris-tunnel/main/install.sh)
```

بعد از نصب، آدرس پنل به همراه نام کاربری و رمز عبور نمایش داده می‌شود.
_After installation the panel URL, username and password are printed._

گزینه‌های اختیاری / optional flags:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/eris4444/eris-tunnel/main/install.sh) --port 8686 --username admin --lang en
```

| فلگ | توضیح |
| --- | --- |
| `--port <n>` | پورت پنل (پیش‌فرض: هنگام آپدیت پورت فعلی حفظ می‌شود، در نصب تازه یک پورت تصادفی) |
| `--username <name>` | نام کاربری ادمین (پیش‌فرض: `admin`) |
| `--password <pass>` | رمز عبور (پیش‌فرض: تصادفی و امن) |
| `--lang fa\|en` | زبان پیش‌فرض پنل |
| `--branch <name>` | برنچ سورس (پیش‌فرض: `main`) |

---

## امکانات / Features

- 🔐 **تانل SSH** — فوروارد `Local (-L)`، `Remote (-R)` و `SOCKS (-D)` با چند قانون روی یک تانل
- 🔁 **بک‌هاول** — پشتیبانی کامل از `tcp`, `tcpmux`, `udp`, `ws`, `wsmux`, `wss`, `wssmux` در دو نقش سرور و کلاینت
- ♻️ **اتصال مجدد خودکار** — هر تانل یک سرویس systemd با `Restart=always` است
- 📊 **داشبورد زنده** — CPU، رم، دیسک، پهنای باند لحظه‌ای، اتصالات فعال و آپ‌تایم
- ⚿ **مدیریت کلید SSH** — ساخت کلید `ed25519` یا وارد کردن کلید موجود، مستقیم از پنل
- 📜 **لاگ زنده** — خروجی `journalctl` هر تانل داخل پنل
- 🌐 **دوزبانه** — فارسی (RTL) و انگلیسی
- 🪶 **سبک** — فقط `fastapi` و `uvicorn`؛ بدون دیتابیس خارجی، بدون Node.js، بدون مرحله build

---

## دستورات مدیریتی / CLI

پس از نصب دستور `eris` در دسترس است:

```bash
eris info          # آدرس پنل و تنظیمات فعلی
eris status        # وضعیت سرویس پنل
eris log 200       # آخرین ۲۰۰ خط لاگ پنل
eris restart       # ری‌استارت پنل
eris reset         # ساخت رمز جدید برای ادمین
eris port 9000     # تغییر پورت پنل
eris update        # نصب مجدد آخرین نسخه (تنظیمات حفظ می‌شود)
eris uninstall     # حذف کامل
```

---

## راهنمای تانل SSH

۱. اگر می‌خواهید با کلید وصل شوید، از بخش **کلیدهای SSH** یک کلید بسازید و کلید عمومی
آن را در فایل `~/.ssh/authorized_keys` سرور مقصد قرار دهید.
۲. در بخش **تانل SSH** روی «تانل جدید» بزنید و مشخصات سرور را وارد کنید.
۳. یک یا چند قانون فوروارد اضافه کنید:

| نوع | کاربرد | مثال |
| --- | --- | --- |
| `Local (-L)` | سرویسی از سرور خارج را روی سرور محلی در دسترس می‌کند | `0.0.0.0:8080 → 127.0.0.1:80` |
| `Remote (-R)` | سرویس محلی را روی سرور خارج منتشر می‌کند | `0.0.0.0:443 ← 127.0.0.1:443` |
| `SOCKS (-D)` | یک پراکسی SOCKS5 روی سرور محلی می‌سازد | `0.0.0.0:1080` |

> برای فوروارد `Remote` باید روی سرور مقابل در `/etc/ssh/sshd_config` مقدار
> `GatewayPorts yes` تنظیم شده باشد، وگرنه پورت فقط روی `127.0.0.1` باز می‌شود.

دکمه **تست اتصال** قبل از ذخیره، صحت دسترسی را بررسی می‌کند.

---

## راهنمای بک‌هاول

اول از تب **بک‌هاول** باینری را نصب کنید (آخرین نسخه از
[Musixal/Backhaul](https://github.com/Musixal/Backhaul) متناسب با معماری سرور دانلود می‌شود).

**سمت سرور خارج** (نقش `server`):

| فیلد | مقدار نمونه |
| --- | --- |
| نقش | `سرور` |
| آدرس بایند | `0.0.0.0:3080` |
| پروتکل | `tcp` |
| توکن | یک رشته تصادفی (دکمه ↻) |
| پورت‌ها | `443`، `8080=80`، `2000-2100` |

**سمت سرور ایران** (نقش `client`):

| فیلد | مقدار نمونه |
| --- | --- |
| نقش | `کلاینت` |
| آدرس سرور | `IP_سرور_خارج:3080` |
| پروتکل | همان پروتکل سرور |
| توکن | **دقیقاً** همان توکن سرور |

قالب قوانین پورت: `443` (همان پورت)، `8080=80` (پورت ورودی=پورت مقصد)،
`2000-2100` (بازه)، `127.0.0.1:443=443` (بایند روی آی‌پی مشخص).

---

## ساختار فایل‌ها

```
/opt/eris-tunnel/          کد پنل و محیط پایتون
/etc/eris-tunnel/
├── config.json            تنظیمات پنل (۰۶۰۰)
├── eris.db                دیتابیس SQLite
├── bin/backhaul           باینری بک‌هاول
├── backhaul/*.toml        کانفیگ هر تانل بک‌هاول
├── keys/                  کلیدهای خصوصی SSH (۰۷۰۰)
└── env/                   رمزهای SSH ذخیره‌شده (۰۶۰۰)

/etc/systemd/system/
├── eris-tunnel.service        سرویس پنل
├── eris-ssh-<name>.service    هر تانل SSH
└── eris-backhaul-<name>.service
```

---

## نکات امنیتی / Security notes

- پنل روی **HTTP** سرو می‌شود. برای دسترسی از اینترنت آن را پشت Nginx با گواهی TLS
  قرار دهید یا فقط از طریق یک تانل SSH به آن وصل شوید.
- بلافاصله بعد از نصب، رمز عبور را از بخش **تنظیمات** تغییر دهید.
- پنل با دسترسی root اجرا می‌شود چون یونیت‌های systemd می‌سازد و مدیریت می‌کند.
- کلیدها و رمزهای SSH با مجوز `0600` ذخیره می‌شوند و هرگز در پاسخ API برنمی‌گردند.
- پورت پنل را در فایروال فقط برای آی‌پی خودتان باز بگذارید.

---

## اجرای محلی برای توسعه / Local development

```bash
git clone https://github.com/eris4444/eris-tunnel.git
cd eris-tunnel
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export ERIS_HOME="$PWD/.eris-dev"
python -m backend.cli setup --port 8686 --password admin1234
python -m backend.server
```

سپس `http://127.0.0.1:8686` را باز کنید. در این حالت مدیریت systemd کار نمی‌کند
ولی رابط کاربری و API کامل قابل بررسی است.

اجرای تست‌های خودکار / run the API smoke tests:

```bash
pip install httpx
python smoke_test.py
```

---

## حذف / Uninstall

```bash
eris uninstall              # حذف کامل شامل تنظیمات
bash /opt/eris-tunnel/uninstall.sh --keep-data   # حفظ تنظیمات
```

---

## پیش‌نیازها / Requirements

- لینوکس با systemd (Ubuntu، Debian، CentOS، Rocky، AlmaLinux، Arch، Alpine)
- Python 3.8 یا بالاتر
- دسترسی root

---

## License

MIT © [eris4444](https://github.com/eris4444)

Backhaul is a separate project by [Musixal](https://github.com/Musixal/Backhaul),
downloaded at runtime and distributed under its own license.
