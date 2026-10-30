#!/usr/bin/env bash
set -u

# اجرای چرخه استاندارد و زمان‌بندی‌شده (پیش‌فرض حدود ۲۵ دقیقه در هر نوبت زمانی)
# همراه با کمی نوسان تصادفی (Jitter) و خروج امن جهت جلوگیری از حساسیت و ساسپند شدن اکانت گیت‌هاب
BASE_RUNTIME_SECONDS="${MAX_RUNTIME_SECONDS:-1500}"
JITTER_SECONDS=$((RANDOM % 45))
TARGET_RUNTIME_SECONDS=$((BASE_RUNTIME_SECONDS - JITTER_SECONDS))
START_TIME=$(date +%s)
BACKOFF_SECONDS=5

echo "Starting scheduled sync cycle..."

while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TIME))

  if [ "$ELAPSED" -ge "$TARGET_RUNTIME_SECONDS" ]; then
    echo "Scheduled cycle window reached ($ELAPSED s). Stopping gracefully..."
    break
  fi

  REMAINING=$((TARGET_RUNTIME_SECONDS - ELAPSED))
  timeout --signal=SIGINT --kill-after=10 "$REMAINING" python3 bot.py
  EXIT_CODE=$?

  # خروج طبیعی در پایان بازه زمانی (کد 124 یا 130 ناشی از SIGINT)
  if [ "$EXIT_CODE" -eq 124 ] || [ "$EXIT_CODE" -eq 130 ] || [ "$EXIT_CODE" -eq 0 ]; then
    echo "Sync cycle completed cleanly."
    break
  fi

  # اگر توکن تنظیم نشده بود (Exit code 2)، بلافاصله خارج شو
  if [ "$EXIT_CODE" -eq 2 ]; then
    echo "Configuration error: missing BOT_TOKEN. Exiting..."
    exit 2
  fi

  echo "Process exited with code $EXIT_CODE. Retrying in ${BACKOFF_SECONDS}s..."
  sleep "$BACKOFF_SECONDS"
  if [ "$BACKOFF_SECONDS" -lt 60 ]; then
    BACKOFF_SECONDS=$((BACKOFF_SECONDS * 2))
  fi
done
