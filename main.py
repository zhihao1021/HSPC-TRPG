from asyncio import all_tasks, ensure_future, gather
from logging import Formatter, getLogger, INFO, StreamHandler
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from signal import SIGINT, SIGTERM
from sys import stdout

from bot import bot
from config import CONFIG
from db import init_db

LOG_DIR = Path("logs")


def setup_logging() -> None:
    """設定 root logger:同時輸出到 stdout 與 logs/ 下的檔案(每日自動輪轉)。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = StreamHandler(stdout)
    stream_handler.setFormatter(formatter)

    # 每天午夜輪轉一次,保留所有歷史紀錄(backupCount=0 代表不刪舊檔)
    # 例如 bot.log, bot.log.2026-06-18, bot.log.2026-06-17, ...
    file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "bot.log",
        when="midnight",
        interval=1,
        backupCount=0,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = getLogger()
    root.setLevel(INFO)
    root.handlers.clear()
    root.addHandler(stream_handler)
    root.addHandler(file_handler)


def start():
    loop = bot.loop
    try:
        loop.add_signal_handler(SIGINT, loop.stop)
        loop.add_signal_handler(SIGTERM, loop.stop)
    except (NotImplementedError, RuntimeError):
        pass

    async def runner():
        try:
            async with init_db():
                await bot.start(CONFIG.discord.token)
        finally:
            if not bot.is_closed():
                await bot.close()

    def stop_loop_on_completion(f):
        loop.stop()

    future = ensure_future(runner(), loop=loop)
    future.add_done_callback(stop_loop_on_completion)
    try:
        loop.run_forever()
    finally:
        future.remove_done_callback(stop_loop_on_completion)

    try:
        tasks = {t for t in all_tasks(loop=loop) if not t.done()}
        for task in tasks:
            task.cancel()

        loop.run_until_complete(gather(*tasks, return_exceptions=True))
        for task in tasks:
            if task.cancelled():
                continue
            if task.exception() is not None:
                loop.call_exception_handler(
                    {
                        "message": "Unhandled exception during Client.run shutdown.",
                        "exception": task.exception(),
                        "task": task,
                    }
                )
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()

    if not future.cancelled():
        try:
            return future.result()
        except KeyboardInterrupt:
            return None


if __name__ == "__main__":
    setup_logging()
    try:
        start()
    except KeyboardInterrupt:
        pass
