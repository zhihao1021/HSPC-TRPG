from asyncio import all_tasks, ensure_future, gather, run
from logging import basicConfig, INFO
from signal import SIGINT, SIGTERM

from bot import bot
from config import CONFIG
from db import init_db


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
    # args = parse_args()
    # load_dotenv(dotenv_path=args.env, override=True)
    basicConfig(
        level=INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        start()
    except KeyboardInterrupt:
        pass
