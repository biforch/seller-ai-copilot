import asyncio
import os
from openai import AsyncOpenAI


async def test():
    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=120
    )

    r = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": "Generate a short Amazon title for a coffee mug"
            }
        ]
    )

    print(r.choices[0].message.content)


asyncio.run(test())
