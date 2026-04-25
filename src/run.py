import asyncio
import os

from dotenv import load_dotenv
from hypercorn.asyncio import serve
from hypercorn.config import Config

from main import app

load_dotenv()

PORT = os.getenv("MANAGER_PORT")
if PORT is None or len(PORT) == 0:
    raise KeyError("The MANAGER_PORT environment variable is required but missing")

async def main():
    config = Config()
    config.bind = ["0.0.0.0:" + PORT]
    await serve(app, config)

if __name__ == "__main__":
    asyncio.run(main())

# By @peterservices
