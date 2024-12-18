import asyncio
import logging

from asyncqueue.consumer import AsyncWorker
from example._components import create_broker, configuration, create_result_backend
from example.tasks import router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with create_broker() as broker:
        worker = AsyncWorker(
            broker=broker,
            configuration=configuration,
            tasks=router,
            concurrency=20,
            result_backend=create_result_backend(),
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
