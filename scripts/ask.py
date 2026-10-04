"""Usage: python scripts/ask.py <arret.pdf> "question" ["question" …]"""

import asyncio
import sys

from dotenv import load_dotenv

from lawhack.answer import ask
from lawhack.pipeline import analyse, load
from lawhack.system_one import TypeSafeSystemOne


def main() -> None:
    load_dotenv()
    registry, solution = analyse(load(sys.argv[1]))
    print(f"Solution : {solution.value}")

    async def run() -> None:
        client = TypeSafeSystemOne()
        for question in sys.argv[2:]:
            answer = await ask(registry, question, client, solution=solution)
            print(f"\nQ: {question}\nR: {answer.render()}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
