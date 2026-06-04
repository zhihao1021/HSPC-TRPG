from asyncio import run, get_running_loop, wait_for, Queue, sleep as asleep


async def task():
    queue = Queue()
    await wait_for(queue.get(), timeout=None)
    print("done")


async def main():
    loop = get_running_loop()
    t = loop.create_task(task())
    await asleep(1)
    t.cancel()
    print("cancelled")

if __name__ == "__main__":
    run(main())
