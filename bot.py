#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ربات هوشمند برنامه‌ریزی و شمارنده جلسات ماز (@mehrmazbot)
طراحی شده برای پایش دقیق پیشروی جلسات کنکور، تقویم کلاس‌ها و برنامه هفتگی
سازگار با اجرای زمان‌بندی‌شده استاندارد و سرور اختصاصی
"""

import os
import sys
import json
import sqlite3
import html
import re
import logging
from datetime import date, datetime, timedelta, timezone
import jdatetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# تنظیمات لاگینگ استاندارد (با محدودسازی لاگ‌های شبکه برای حفظ حریم خصوصی و امنیت توکن)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
logger = logging.getLogger("mehrmazbot")

# متغیرهای محیطی و پیکربندی
DB_PATH = os.environ.get("DB_PATH", "mehrmaz_bot.db")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "").strip()
ALLOWED_USER_IDS_RAW = os.environ.get("ALLOWED_USER_IDS", "").strip()

ALLOWED_USER_IDS = set()
if ADMIN_ID_RAW.isdigit():
    ALLOWED_USER_IDS.add(int(ADMIN_ID_RAW))
for uid_str in ALLOWED_USER_IDS_RAW.split(","):
    if uid_str.strip().isdigit():
        ALLOWED_USER_IDS.add(int(uid_str.strip()))

# تاریخ مبدا سیستم منطبق با پنل کاربری: جمعه ۸ آبان ۱۴۰۵
ANCHOR_JALALI = jdatetime.date(1405, 8, 8)
ANCHOR_GREGORIAN = ANCHOR_JALALI.togregorian()

# نگاشت روزهای هفته در jdatetime:
# 0: شنبه (Saturday)
# 1: یکشنبه (Sunday)
# 2: دوشنبه (Monday)
# 3: سه‌شنبه (Tuesday)
# 4: چهارشنبه (Wednesday)
# 5: پنجشنبه (Thursday)
# 6: جمعه (Friday)
WEEKDAY_NAMES = {
    0: "شنبه",
    1: "یکشنبه",
    2: "دوشنبه",
    3: "سه‌شنبه",
    4: "چهارشنبه",
    5: "پنجشنبه",
    6: "جمعه",
}

MONTH_NAMES = {
    1: "فروردین",
    2: "اردیبهشت",
    3: "خرداد",
    4: "تیر",
    5: "مرداد",
    6: "شهریور",
    7: "مهر",
    8: "آبان",
    9: "آذر",
    10: "دی",
    11: "بهمن",
    12: "اسفند",
}

PERSIAN_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "اردی بهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "ابان": 8,
    "آذر": 9,
    "اذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}

# ساختار دقیق دروس بر اساس اسکرین‌شات‌های پنل کاربری ماز:
DEFAULT_COURSES = [
    {
        "code": "math",
        "name": "ریاضی",
        "base_sessions": 7,
        "note": "طبق پنل: ۷ جلسه تا ۷ آبان",
        "schedule": [
            {"weekday": 1, "time": "۲۰:۱۵ تا ۲۳:۱۵"},
            {"weekday": 4, "time": "۱۵:۱۵ تا ۱۹:۰۰"},
            {"weekday": 5, "time": "۰۹:۰۰ تا ۱۱:۴۵"},
        ],
    },
    {
        "code": "bio",
        "name": "زیست‌شناسی (فرهمندنیا)",
        "base_sessions": 5,
        "note": "۵ جلسه اصلی + جلسه صفر (نقشه گنج) + ۱ حل تست + ۳ تکمیلی",
        "schedule": [
            {"weekday": 0, "time": "۱۸:۳۰ تا ۲۱:۴۵"},
            {"weekday": 3, "time": "۱۶:۴۵ تا ۲۰:۰۰"},
        ],
    },
    {
        "code": "phys",
        "name": "فیزیک (شجاعی)",
        "base_sessions": 6,
        "note": "۶ جلسه اصلی در پنل (مجموعاً ۱۳ ویدیو)",
        "schedule": [
            {"weekday": 2, "time": "۲۰:۱۵ تا ۲۳:۱۵"},
            {"weekday": 4, "time": "۲۰:۱۵ تا ۲۳:۱۵"},
        ],
    },
    {
        "code": "chem",
        "name": "شیمی",
        "base_sessions": 2,
        "note": "شروع از ۵ آبان - فیلم‌ها ۴ ساعته",
        "schedule": [
            {"weekday": 1, "time": "فیلم ۴ ساعته"},
            {"weekday": 5, "time": "فیلم ۴ ساعته"},
        ],
    },
    {
        "code": "geo",
        "name": "زمین‌شناسی",
        "base_sessions": 3,
        "note": "طبق پنل: جلسه ۴ در دوشنبه ۱۱ آبان",
        "schedule": [
            {"weekday": 2, "time": "۱۶:۴۵ تا ۱۸:۱۵"},
        ],
    },
    {
        "code": "farsi",
        "name": "فارسی",
        "base_sessions": 5,
        "note": "",
        "schedule": [
            {"weekday": 2, "time": "۱۵:۱۵ تا ۱۶:۳۰"},
        ],
    },
    {
        "code": "dini",
        "name": "دینی",
        "base_sessions": 4,
        "note": "",
        "schedule": [
            {"weekday": 3, "time": "۱۵:۱۵ تا ۱۶:۳۰"},
        ],
    },
    {
        "code": "eng",
        "name": "زبان",
        "base_sessions": 4,
        "note": "آفلاین",
        "schedule": [
            {"weekday": 0, "time": "۱۰:۰۰ تا ۱۱:۱۵"},
        ],
    },
    {
        "code": "arabi",
        "name": "عربی",
        "base_sessions": 3,
        "note": "",
        "schedule": [
            {"weekday": 4, "time": "۱۵:۱۵ تا ۱۶:۳۰"},
        ],
    },
]


def to_persian_digits(val) -> str:
    """تبدیل اعداد انگلیسی به فارسی جهت نمایش زیبا در تلگرام"""
    en = "0123456789"
    fa = "۰۱۲۳۴۵۶۷۸۹"
    s = str(val)
    for e, f in zip(en, fa):
        s = s.replace(e, f)
    return s


def to_english_digits(val: str) -> str:
    """تبدیل ارقام فارسی و عربی به انگلیسی جهت پردازش ریاضی و تاریخ"""
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    en = "0123456789"
    s = str(val)
    for f, a, e in zip(fa, ar, en):
        s = s.replace(f, e).replace(a, e)
    return s


def get_db_connection() -> sqlite3.Connection:
    """ایجاد اتصال بهینه و مطمئن با پشتیبانی از WAL و Timeout بالا"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    """راه‌اندازی ساختار دیتابیس و مقداردهی اولیه دروس"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS courses (
                code TEXT PRIMARY KEY,
                name TEXT,
                base_sessions INTEGER,
                note TEXT,
                schedule_json TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                selected_courses_json TEXT,
                default_days INTEGER DEFAULT 8
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS user_course_overrides (
                user_id INTEGER,
                code TEXT,
                custom_base INTEGER,
                PRIMARY KEY (user_id, code)
            )
            """
        )
        changed = False
        for item in DEFAULT_COURSES:
            c.execute("SELECT code FROM courses WHERE code = ?", (item["code"],))
            if not c.fetchone():
                c.execute(
                    "INSERT INTO courses (code, name, base_sessions, note, schedule_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        item["code"],
                        item["name"],
                        item["base_sessions"],
                        item["note"],
                        json.dumps(item["schedule"], ensure_ascii=False),
                    ),
                )
                changed = True
        if changed:
            conn.commit()


def get_all_courses() -> list:
    """دریافت لیست پایه‌ای کل دروس از دیتابیس"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT code, name, base_sessions, note, schedule_json FROM courses")
        rows = c.fetchall()

    order_map = {item["code"]: idx for idx, item in enumerate(DEFAULT_COURSES)}
    courses = []
    for r in rows:
        courses.append(
            {
                "code": r[0],
                "name": r[1],
                "base_sessions": r[2],
                "note": r[3] or "",
                "schedule": json.loads(r[4]),
            }
        )
    courses.sort(key=lambda x: order_map.get(x["code"], 99))
    return courses


def get_user_courses(user_id: int) -> list:
    """دریافت دروس به همراه تغییرات و سفارشی‌سازی‌های پایه مخصوص این کاربر"""
    courses = get_all_courses()
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT code, custom_base FROM user_course_overrides WHERE user_id = ?",
            (user_id,),
        )
        overrides = dict(c.fetchall())

    for course in courses:
        code = course["code"]
        if code in overrides:
            course["base_sessions"] = overrides[code]
    return courses


def update_user_course_base(user_id: int, code: str, new_base: int):
    """به‌روزرسانی تعداد جلسات پایه برای کاربر مشخص بدون خراب کردن تنظیمات بقیه"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_course_overrides (user_id, code, custom_base)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, code) DO UPDATE SET custom_base = excluded.custom_base
            """,
            (user_id, code, new_base),
        )
        conn.commit()


def reset_user_courses(user_id: int):
    """بازنشانی جلسات پایه کاربر به مقادیر پیش‌فرض پنل ماز (۸ آبان)"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM user_course_overrides WHERE user_id = ?", (user_id,))
        conn.commit()


def get_user_selected_courses(user_id: int) -> list:
    """دریافت کدهای دروس فعال‌شده توسط کاربر"""
    all_codes = [c["code"] for c in DEFAULT_COURSES]
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT selected_courses_json FROM user_prefs WHERE user_id = ?",
            (user_id,),
        )
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO user_prefs (user_id, selected_courses_json, default_days) VALUES (?, ?, 8)",
                (user_id, json.dumps(all_codes)),
            )
            conn.commit()
            return all_codes

    saved = json.loads(row[0])
    return [code for code in all_codes if code in saved]


def set_user_selected_courses(user_id: int, selected_codes: list):
    """ذخیره دروس انتخاب‌شده توسط کاربر"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO user_prefs (user_id, selected_courses_json, default_days)
            VALUES (?, ?, 8)
            ON CONFLICT(user_id) DO UPDATE SET selected_courses_json = excluded.selected_courses_json
            """,
            (user_id, json.dumps(selected_codes)),
        )
        conn.commit()


def format_jalali(jdate: jdatetime.date, include_year: bool = False) -> str:
    """قالب‌بندی خوانا و استاندارد تاریخ شمسی"""
    wname = WEEKDAY_NAMES[jdate.weekday()]
    month_name = MONTH_NAMES.get(jdate.month, "")
    day_str = to_persian_digits(jdate.day)
    if include_year or jdate.year != ANCHOR_JALALI.year:
        year_str = to_persian_digits(jdate.year)
        return f"{wname} {day_str} {month_name} {year_str}"
    return f"{wname} {day_str} {month_name}"


def get_today_jalali() -> jdatetime.date:
    """محاسبه دقیق تاریخ امروز ایران (UTC+3:30 ثابت پس از لغو تغییر ساعت)"""
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    now_tehran = datetime.now(tehran_tz)
    return jdatetime.date.fromgregorian(date=now_tehran.date())


def count_sessions_up_to(course: dict, target_g: date) -> int:
    """
    محاسبه تعداد کل جلسات برگزارشده یک درس تا پایان روز target_g
    مبنا: جمعه ۸ آبان ۱۴۰۵ (ANCHOR_GREGORIAN)
    """
    base = course["base_sessions"]
    sched_weekdays = [s["weekday"] for s in course["schedule"]]

    if target_g == ANCHOR_GREGORIAN:
        return base
    elif target_g > ANCHOR_GREGORIAN:
        total = base
        curr = ANCHOR_GREGORIAN + timedelta(days=1)
        while curr <= target_g:
            j_curr = jdatetime.date.fromgregorian(date=curr)
            w = j_curr.weekday()
            total += sched_weekdays.count(w)
            curr += timedelta(days=1)
        return total
    else:
        total = base
        curr = ANCHOR_GREGORIAN
        while curr > target_g:
            j_curr = jdatetime.date.fromgregorian(date=curr)
            w = j_curr.weekday()
            total -= sched_weekdays.count(w)
            curr -= timedelta(days=1)
        return max(0, total)


def generate_progression_report(
    start_j: jdatetime.date,
    end_j: jdatetime.date,
    selected_codes: list,
    user_id: int = 0,
) -> str:
    """تولید گزارش جامع و منظم پیشروی دروس در بازه زمانی درخواستی"""
    user_courses = get_user_courses(user_id) if user_id else get_all_courses()
    courses = [c for c in user_courses if c["code"] in selected_codes]

    if not courses:
        return "⚠️ هیچ درسی در فیلتر شما انتخاب نشده است! لطفاً از بخش «⚙️ فیلتر دروس» حداقل یک درس را فعال کنید."

    start_g = start_j.togregorian()
    end_g = end_j.togregorian()

    # در صورتی که تاریخ‌ها برعکس وارد شده باشند
    is_reversed = False
    if end_g < start_g:
        start_g, end_g = end_g, start_g
        start_j, end_j = end_j, start_j
        is_reversed = True

    days_diff = (end_g - start_g).days
    lines = []

    lines.append("📊 <b>گزارش وضعیت و پیشروی جلسات (پنل ماز)</b>")
    lines.append(f"📅 تاریخ شروع (مبنا) ⬅️ <code>{format_jalali(start_j)}</code>")
    if days_diff > 0:
        lines.append(
            f"🎯 تاریخ هدف ⬅️ <code>{format_jalali(end_j)}</code> ({to_persian_digits(days_diff)} روز پیشروی)"
        )
    else:
        lines.append(f"🎯 تاریخ هدف ⬅️ <code>{format_jalali(end_j)}</code>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # بخش اول: وضعیت در تاریخ شروع
    lines.append(f"📌 <b>جلسات تدریس‌شده تا {format_jalali(start_j)}:</b>")
    for c in courses:
        taught_count = count_sessions_up_to(c, start_g)
        note_str = f" <i>({html.escape(c['note'])})</i>" if c["note"] else ""
        lines.append(
            f"🔹 <b>{html.escape(c['name'])}:</b> {to_persian_digits(taught_count)} جلسه پیشروی کرده{note_str}"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # بخش دوم: تقویم روزبه‌روز جلساتی که در بازه پیشروی می‌کنند
    if days_diff > 0:
        section_title = (
            f"🚀 <b>برنامه روزبه‌روز جلسات از فردای {format_jalali(start_j)} تا {format_jalali(end_j)}:</b>"
        )
        lines.append(section_title)
        running_counts = {c["code"]: count_sessions_up_to(c, start_g) for c in courses}
        curr_g = start_g + timedelta(days=1)
        any_session_found = False

        while curr_g <= end_g:
            curr_j = jdatetime.date.fromgregorian(date=curr_g)
            w = curr_j.weekday()
            day_events = []

            for c in courses:
                for s in c["schedule"]:
                    if s["weekday"] == w:
                        running_counts[c["code"]] += 1
                        sess_num = running_counts[c["code"]]
                        day_events.append(
                            f"   🔸 <b>{html.escape(c['name'])}</b> ⬅️ جلسه {to_persian_digits(sess_num)} ({html.escape(s['time'])})"
                        )

            if day_events:
                any_session_found = True
                lines.append(f"\n🗓 <b>{format_jalali(curr_j)}:</b>")
                lines.extend(day_events)

            curr_g += timedelta(days=1)

        if not any_session_found:
            lines.append("   ⬅️ در این بازه کلاسی برای دروس انتخابی برگزار نمی‌شود.")

        lines.append("━━━━━━━━━━━━━━━━━━━━")

    # بخش سوم: جمع‌بندی نهایی تا پایان تاریخ هدف
    if days_diff > 0:
        lines.append(
            f"✅ <b>جمع‌بندی نهایی تا پایان {format_jalali(end_j)}:</b>"
        )
        for c in courses:
            start_cnt = count_sessions_up_to(c, start_g)
            end_cnt = count_sessions_up_to(c, end_g)
            added = end_cnt - start_cnt
            added_text = (
                f" (+{to_persian_digits(added)} جلسه جدید)" if added > 0 else " (بدون جلسه جدید)"
            )
            lines.append(
                f"🟢 <b>{html.escape(c['name'])}</b> ⬅️ جلسه {to_persian_digits(end_cnt)}{added_text}"
            )
    else:
        lines.append(f"✅ <b>جمع‌بندی:</b> کلیه مقادیر فوق تا پایان <code>{format_jalali(end_j)}</code> نهایی است.")

    return "\n".join(lines)


def build_weekly_schedule_text(selected_codes: list, user_id: int = 0) -> str:
    """ساخت متن برنامه هفتگی منظم کلاس‌ها"""
    user_courses = get_user_courses(user_id) if user_id else get_all_courses()
    courses = [c for c in user_courses if c["code"] in selected_codes]
    lines = ["📅 <b>برنامه هفتگی کلاس‌ها (منطبق با پنل ماز):</b>"]
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    for w in range(7):
        day_items = []
        for c in courses:
            for s in c["schedule"]:
                if s["weekday"] == w:
                    day_items.append(
                        f"   🔹 <b>{html.escape(c['name'])}:</b> {html.escape(s['time'])}"
                    )
        if day_items:
            lines.append(f"\n📌 <b>{WEEKDAY_NAMES[w]}:</b>")
            lines.extend(day_items)

    return "\n".join(lines)


def parse_user_date_input(text: str, today_j: jdatetime.date):
    """
    تحلیل دقیق متن ورودی کاربر برای استخراج تاریخ یا تعداد روز
    خروجی: تاپل (تاریخ شروع، تاریخ پایان) یا خطای 'INVALID_DATE' یا None
    """
    clean = to_english_digits(text.strip().lower())

    # عبارات متداول زمان
    if clean in ("امروز", "امروزو"):
        return today_j, today_j
    if clean in ("فردا", "فردارو"):
        target_g = today_j.togregorian() + timedelta(days=1)
        return today_j, jdatetime.date.fromgregorian(date=target_g)
    if clean in ("پس فردا", "پسفردا"):
        target_g = today_j.togregorian() + timedelta(days=2)
        return today_j, jdatetime.date.fromgregorian(date=target_g)
    if clean in ("یک هفته", "۱ هفته", "1 هفته"):
        target_g = today_j.togregorian() + timedelta(days=7)
        return today_j, jdatetime.date.fromgregorian(date=target_g)
    if clean in ("دو هفته", "۲ هفته", "2 هفته"):
        target_g = today_j.togregorian() + timedelta(days=14)
        return today_j, jdatetime.date.fromgregorian(date=target_g)

    # حالت ۱: عباراتی مانند '۱۰ روز'، '۱۰ روز دیگه'، 'تا ۱۰ روز بعد'
    m_days = re.search(r"(\d+)\s*(?:روز|day)", clean)
    if m_days:
        days = int(m_days.group(1))
        if 0 <= days <= 365:
            target_g = today_j.togregorian() + timedelta(days=days)
            return today_j, jdatetime.date.fromgregorian(date=target_g)

    # عدد خالص (مثلاً کاربر فقط نوشته 10)
    if clean.isdigit():
        days = int(clean)
        if 0 <= days <= 365:
            target_g = today_j.togregorian() + timedelta(days=days)
            return today_j, jdatetime.date.fromgregorian(date=target_g)

    # حالت ۲: فرمت ممیزدار مثل 1405/8/18 یا 8/18 یا 1405-08-18
    clean_date = clean.replace("تا", "").replace("از", "").strip()
    sep = "/" if "/" in clean_date else ("-" if "-" in clean_date else None)
    if sep:
        parts = [p.strip() for p in clean_date.split(sep) if p.strip().isdigit()]
        if len(parts) == 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if y < 100:
                y += 1400
            try:
                target_j = jdatetime.date(y, m, d)
                return today_j, target_j
            except ValueError:
                return "INVALID_DATE"
        elif len(parts) == 2:
            m, d = int(parts[0]), int(parts[1])
            try:
                target_j = jdatetime.date(today_j.year, m, d)
                return today_j, target_j
            except ValueError:
                return "INVALID_DATE"

    # حالت ۳: تاریخ حروفی مثل '۱۸ آبان'، 'آبان ۱۸'، 'تا ۵ آذر'
    words = clean.replace("تا", " ").replace("از", " ").replace("،", " ").split()
    digits = []
    found_month = None

    for w in words:
        if w.isdigit():
            digits.append(int(w))
        elif w in PERSIAN_MONTHS and found_month is None:
            found_month = PERSIAN_MONTHS[w]

    if found_month is not None and digits:
        found_year = today_j.year
        found_day = None

        if len(digits) == 1:
            found_day = digits[0]
        elif len(digits) >= 2:
            if digits[0] > 1300:
                found_year = digits[0]
                found_day = digits[1]
            elif digits[1] > 1300:
                found_day = digits[0]
                found_year = digits[1]
            else:
                found_day = digits[0]
                found_year = digits[1] if digits[1] > 100 else digits[1] + 1400

        if found_day is not None:
            try:
                target_j = jdatetime.date(found_year, found_month, found_day)
                return today_j, target_j
            except ValueError:
                return "INVALID_DATE"

    return None


def split_telegram_message(text: str, max_length: int = 3900) -> list:
    """تقسیم هوشمند پیام‌های طولانی به چند پارت استاندارد زیر ۴۰۹۶ کاراکتر تلگرام"""
    if len(text) <= max_length:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                chunks.append(line[:max_length])
                current_chunk = [line[max_length:]]
                current_len = len(current_chunk[0])
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


async def reply_safe(update: Update, text: str, reply_markup=None):
    """ارسال امن پیام با تقسیم خودکار در صورت عبور از سقف طول پیام"""
    chunks = split_telegram_message(text)
    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        await update.effective_message.reply_text(
            chunk,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد اصلی و دسترسی سریع بات"""
    keyboard = [
        ["🚀 پیشروی ۸ روز آینده", "📆 پیشروی ۱۰ روز آینده"],
        ["📌 وضعیت تا امروز", "📍 وضعیت مبدا (۸ آبان)"],
        ["⚙️ فیلتر دروس (انتخاب دروس)", "🗓 برنامه هفتگی کلاس‌ها"],
        ["✏️ ویرایش جلسات پایه", "ℹ️ راهنمای تاریخ دلخواه"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_filter_inline_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """کیبورد اینلاین جهت فعال/غیرفعال‌سازی دروس"""
    courses = get_all_courses()
    selected = get_user_selected_courses(user_id)
    buttons = []
    row = []
    for c in courses:
        is_sel = c["code"] in selected
        mark = "✅" if is_sel else "❌"
        btn = InlineKeyboardButton(
            f"{mark} {c['name']}", callback_data=f"toggle_{c['code']}"
        )
        row.append(btn)
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("☑️ انتخاب همه دروس", callback_data="filter_all"),
            InlineKeyboardButton("🔲 حذف همه", callback_data="filter_none"),
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                "🚀 نمایش پیشروی ۸ روز آینده با همین فیلتر", callback_data="run_8days"
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


def get_edit_inline_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """کیبورد اینلاین جهت ویرایش سفارشی جلسات پایه هر کاربر"""
    courses = get_user_courses(user_id)
    buttons = []
    for c in courses:
        cnt = to_persian_digits(c["base_sessions"])
        buttons.append(
            [
                InlineKeyboardButton("➕", callback_data=f"inc_{c['code']}"),
                InlineKeyboardButton(
                    f"{c['name']} ⬅️ {cnt} جلسه", callback_data="noop"
                ),
                InlineKeyboardButton("➖", callback_data=f"dec_{c['code']}"),
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 بازنشانی به مقادیر پیش‌فرض پنل (۸ آبان)", callback_data="reset_bases"
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


def is_authorized(user_id: int) -> bool:
    """بررسی دسترسی کاربر با پشتیبانی همزمان از ADMIN_ID و ALLOWED_USER_IDS"""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به دستور /start و پیام خوش‌آمدگویی اولیه"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.effective_message.reply_text("⛔ شما مجوز دسترسی به این بات را ندارید.")
        return

    today_j = get_today_jalali()
    msg = (
        "سلام! به بات برنامه‌ریز و شمارنده هوشمند جلسات ماز (<code>@mehrmazbot</code>) خوش آمدید.\n\n"
        f"📅 <b>امروز</b> ⬅️ <code>{format_jalali(today_j)}</code>\n"
        f"📍 <b>تاریخ مبدا سیستم</b> ⬅️ جمعه ۸ آبان ۱۴۰۵ (کالیبره‌شده با پنل شما)\n\n"
        "✅ به صورت پیش‌فرض <b>همه دروس</b> انتخاب هستند.\n\n"
        "🔹 با دکمه‌های زیر می‌توانید پیشروی ۸ یا ۱۰ روز آینده را ببینید، دروس دلخواهتان را فیلتر کنید، یا <b>هر تاریخ دلخواهی</b> (مثلاً <code>۱۸ آبان</code> یا <code>۱۰ روز</code> یا <code>۱۴۰۵/۸/۲۰</code>) را تایپ کنید تا دقیقاً محاسبه شود تا آن روز هر درس به کدام جلسه می‌رسد."
    )
    await reply_safe(update, msg, reply_markup=get_main_reply_keyboard())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های متنی کیبورد اصلی و پیام‌های ارسالی کاربر"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        return

    text = update.message.text.strip()
    today_j = get_today_jalali()
    selected = get_user_selected_courses(user_id)

    if text == "🚀 پیشروی ۸ روز آینده":
        end_g = today_j.togregorian() + timedelta(days=8)
        end_j = jdatetime.date.fromgregorian(date=end_g)
        report = generate_progression_report(today_j, end_j, selected, user_id=user_id)
        await reply_safe(update, report, reply_markup=get_main_reply_keyboard())
        return

    if text == "📆 پیشروی ۱۰ روز آینده":
        end_g = today_j.togregorian() + timedelta(days=10)
        end_j = jdatetime.date.fromgregorian(date=end_g)
        report = generate_progression_report(today_j, end_j, selected, user_id=user_id)
        await reply_safe(update, report, reply_markup=get_main_reply_keyboard())
        return

    if text == "📌 وضعیت تا امروز":
        report = generate_progression_report(ANCHOR_JALALI, today_j, selected, user_id=user_id)
        await reply_safe(update, report, reply_markup=get_main_reply_keyboard())
        return

    if text == "📍 وضعیت مبدا (۸ آبان)":
        report = generate_progression_report(ANCHOR_JALALI, ANCHOR_JALALI, selected, user_id=user_id)
        await reply_safe(update, report, reply_markup=get_main_reply_keyboard())
        return

    if text == "🗓 برنامه هفتگی کلاس‌ها":
        sched_text = build_weekly_schedule_text(selected, user_id=user_id)
        await reply_safe(update, sched_text, reply_markup=get_main_reply_keyboard())
        return

    if text == "⚙️ فیلتر دروس (انتخاب دروس)":
        filter_msg = (
            "⚙️ <b>تنظیم فیلتر دروس:</b>\n"
            "روی هر درس ضربه بزنید تا از گزارش پیشروی فعال یا غیرفعال شود:"
        )
        await update.message.reply_text(
            filter_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=get_filter_inline_keyboard(user_id),
        )
        return

    if text == "✏️ ویرایش جلسات پایه":
        edit_msg = (
            "✏️ <b>ویرایش تعداد جلسات پایه (مبدا جمعه ۸ آبان):</b>\n"
            "مقادیر زیر طبق پنل ماز تنظیم شده‌اند. در صورت نیاز با دکمه‌های زیر می‌توانید عدد پایه اختصاصی خود را تنظیم فرمایید:"
        )
        await update.message.reply_text(
            edit_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=get_edit_inline_keyboard(user_id),
        )
        return

    if text == "ℹ️ راهنمای تاریخ دلخواه":
        help_text = (
            "📖 <b>راهنمای محاسبه با تاریخ یا بازه دلخواه:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "شما می‌توانید هر زمان که مایل بودید، مستقیماً در چت بنویسید:\n\n"
            "1. <b>تعداد روز آینده:</b>\n"
            "مثلاً بنویسید: <code>8</code> یا <code>10 روز</code> یا <code>14 روز دیگه</code>\n"
            "⬅️ بات از امروز تا آن روز را روزبه‌روز محاسبه و لیست می‌کند.\n\n"
            "2. <b>تاریخ شمسی به حروف:</b>\n"
            "مثلاً بنویسید: <code>18 آبان</code> یا <code>25 آبان</code> یا <code>5 آذر</code>\n"
            "⬅️ بات تمام جلسات پیش‌رو تا آن تاریخ را محاسبه می‌کند.\n\n"
            "3. <b>تاریخ عددی:</b>\n"
            "مثلاً بنویسید: <code>8/20</code> یا <code>1405/8/20</code>\n\n"
            "4. <b>کلمات سریع:</b>\n"
            "می‌توانید کلماتی مثل <code>فردا</code>، <code>پس فردا</code>، یا <code>یک هفته</code> را نیز ارسال نمایید."
        )
        await reply_safe(update, help_text, reply_markup=get_main_reply_keyboard())
        return

    parsed = parse_user_date_input(text, today_j)

    if parsed == "INVALID_DATE":
        await reply_safe(
            update,
            "⚠️ <b>تاریخ واردشده نامعتبر است!</b>\n"
            "لطفاً دقت فرمایید روز یا ماه ورودی صحیح باشد (مثلاً آبان ۳۰ روز دارد).",
            reply_markup=get_main_reply_keyboard(),
        )
        return

    if parsed:
        start_j, target_j = parsed
        report = generate_progression_report(start_j, target_j, selected, user_id=user_id)
        await reply_safe(update, report, reply_markup=get_main_reply_keyboard())
    else:
        await reply_safe(
            update,
            "❓ <b>ورودی نامفهوم بود.</b>\n"
            "لطفاً از دکمه‌های منو استفاده فرمایید یا یک تاریخ مشخص (مثل <code>۱۸ آبان</code> یا عدد <code>۱۰</code> برای ۱۰ روز آینده) بنویسید.",
            reply_markup=get_main_reply_keyboard(),
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک‌های اینلاین کیبورد فیلتر و ویرایش جلسات"""
    query = update.callback_query
    user_id = query.from_user.id
    if not is_authorized(user_id):
        await query.answer("⛔ عدم دسترسی!", show_alert=True)
        return

    data = query.data
    if data == "noop":
        await query.answer()
        return

    try:
        if data.startswith("toggle_"):
            code = data.replace("toggle_", "")
            selected = get_user_selected_courses(user_id)
            if code in selected:
                selected.remove(code)
            else:
                selected.append(code)
            set_user_selected_courses(user_id, selected)
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_filter_inline_keyboard(user_id)
                )
            except BadRequest:
                pass
            await query.answer("فیلتر دروس به‌روزرسانی شد.")
            return

        if data == "filter_all":
            all_codes = [c["code"] for c in DEFAULT_COURSES]
            set_user_selected_courses(user_id, all_codes)
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_filter_inline_keyboard(user_id)
                )
            except BadRequest:
                pass
            await query.answer("همه دروس انتخاب شدند ✅")
            return

        if data == "filter_none":
            set_user_selected_courses(user_id, [])
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_filter_inline_keyboard(user_id)
                )
            except BadRequest:
                pass
            await query.answer("همه دروس از انتخاب خارج شدند.")
            return

        if data == "run_8days":
            today_j = get_today_jalali()
            end_g = today_j.togregorian() + timedelta(days=8)
            end_j = jdatetime.date.fromgregorian(date=end_g)
            selected = get_user_selected_courses(user_id)
            report = generate_progression_report(today_j, end_j, selected, user_id=user_id)
            await query.message.reply_text(
                report,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_reply_keyboard(),
                disable_web_page_preview=True,
            )
            await query.answer()
            return

        if data.startswith("inc_") or data.startswith("dec_"):
            code = data[4:]
            user_courses = get_user_courses(user_id)
            for c in user_courses:
                if c["code"] == code:
                    delta = 1 if data.startswith("inc_") else -1
                    new_val = max(0, c["base_sessions"] + delta)
                    update_user_course_base(user_id, code, new_val)
                    break
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_edit_inline_keyboard(user_id)
                )
            except BadRequest:
                pass
            await query.answer("تعداد جلسات پایه تغییر کرد.")
            return

        if data == "reset_bases":
            reset_user_courses(user_id)
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_edit_inline_keyboard(user_id)
                )
            except BadRequest:
                pass
            await query.answer("جلسات پایه به مقادیر پنل ماز بازنشانی شد ✅", show_alert=True)
            return

    except Exception as e:
        logger.error(f"Error handling callback query: {e}", exc_info=True)
        try:
            await query.answer("خطایی رخ داد، لطفاً مجدداً تلاش کنید.")
        except Exception:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت خطاهای غیرمنتظره و لاگ کردن بدون متوقف شدن بات"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ متاسفانه خطایی در پردازش رخ داد. لطفاً چند لحظه بعد مجدداً امتحان فرمایید."
            )
        except Exception:
            pass


def main():
    """نقطه ورود اصلی برنامه"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is missing! (Exit Code 2)")
        sys.exit(2)

    logger.info("Initializing database...")
    init_db()

    logger.info("Building Telegram Application...")
    app = Application.builder().token(BOT_TOKEN).build()

    # ثبت هندلرها
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Starting @mehrmazbot service cycle...")
    app.run_polling(
        drop_pending_updates=False,
        poll_interval=2.0,
        timeout=20,
    )


if __name__ == "__main__":
    main()
