# from dotenv import load_dotenv

# from argparse import ArgumentParser
from asyncio import run
from logging import basicConfig, INFO

from bot import start
from db import init_db


# def parse_args():
#     parser = ArgumentParser(description="D&D 5e TRPG Discord Bot")
#     parser.add_argument(
#         "--env",
#         default=".env",
#         help="指定要載入的 .env 檔案路徑(預設: .env)",
#     )
#     return parser.parse_args()


async def main():
    async with init_db():
        await start()


if __name__ == "__main__":
    # args = parse_args()
    # load_dotenv(dotenv_path=args.env, override=True)
    basicConfig(
        level=INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        run(main=main())
    except KeyboardInterrupt:
        pass
