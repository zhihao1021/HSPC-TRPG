from dotenv import load_dotenv

from asyncio import run


async def main():
    from bot import start
    from db import init_db

    async with init_db():
        await start()


if __name__ == "__main__":
    load_dotenv()
    try:
        run(main=main())
    except KeyboardInterrupt:
        pass
