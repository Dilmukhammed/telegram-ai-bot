import asyncio
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


async def main() -> None:
    client = AsyncOpenAI(
        base_url=os.getenv("OPENAI_BASE_URL"),
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    models = [
        os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "text-embedding-004",
        "embedding-001",
        "openai/text-embedding-3-small",
    ]
    for model in models:
        if not model:
            continue
        try:
            response = await client.embeddings.create(model=model, input="hello")
            print("ok", model, len(response.data[0].embedding))
            return
        except Exception as exc:
            print("fail", model, str(exc)[:160])
    print("no working embedding model found")


if __name__ == "__main__":
    asyncio.run(main())
