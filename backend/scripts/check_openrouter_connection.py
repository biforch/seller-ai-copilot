"""Manual connectivity check for OpenRouter API. Not collected by pytest."""

import asyncio
import os

from openai import AsyncOpenAI


async def main() -> None:
    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )

    result = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini"),
        messages=[
            {
                "role": "user",
                "content": "Hello, SellerAI connectivity test",
            }
        ],
    )

    print(result.choices[0].message.content)


if __name__ == "__main__":
    asyncio.run(main())
