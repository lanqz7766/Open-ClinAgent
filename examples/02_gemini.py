"""Example: Google Gemini"""
import asyncio
from clinagent.engine import create_agent


async def main():
    agent = create_agent(
        "gemini-3-flash",
        api_key="AIza...",       # or set GEMINI_API_KEY in .env
    )
    result = await agent.invoke("Read README.md and suggest improvements")
    print(result.result)


if __name__ == "__main__":
    asyncio.run(main())
