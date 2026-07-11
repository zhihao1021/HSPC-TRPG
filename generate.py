from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))  # UTC+8

time = datetime(2026, 7, 8, 6, tzinfo=TZ)

with open("result.txt", "w", encoding="utf-8") as f:
    for _ in range(36):
        f.write(f"{time.isoformat()}\n")
        time += timedelta(minutes=160)
