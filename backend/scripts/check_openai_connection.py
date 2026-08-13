"""Manual connectivity check for OpenAI API. Not collected by pytest."""

import asyncio
import os

from openai import AsyncOpenAI


async def test() -> None:
    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=120,
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": "Generate a short Amazon title for a coffee mug",
            }
        ],
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    asyncio.run(test())
