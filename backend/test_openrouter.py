from openai import AsyncOpenAI
import asyncio
import os


async def main():

    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )

    result = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL"),
        messages=[
            {
                "role": "user",
                "content": "你好，测试SellerAI"
            }
        ]
    )

    print(result.choices[0].message.content)


asyncio.run(main())
