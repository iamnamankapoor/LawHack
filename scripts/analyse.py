"""Usage: python scripts/analyse.py <arret.pdf|arret.txt> [--no-cache]"""

import sys

from dotenv import load_dotenv

from lawhack.pipeline import analyse, load

LABELS = {"COUR_CASSATION": "Cour", "JURIDICTION_FOND": "Cour d'appel", "DEMANDEUR": "Demandeur",
          "DEFENDEUR": "Défendeur", "MINISTERE_PUBLIC": "Min. public", "LOI": "Loi", "INDETERMINE": "?"}


def main() -> None:
    load_dotenv()
    doc = load(sys.argv[1])
    registry, solution = analyse(doc, use_cache="--no-cache" not in sys.argv)
    print(f"Solution: {solution.value} · {len(registry.entries)} segments · {registry.seconds}s · "
          f"{registry.input_tokens} tokens · {registry.model}")
    for e in registry.entries:
        if e.zone.value == "introduction":
            continue
        flag = " ⚠" if e.speaker.confidence < 0.8 else ""
        para = f"§{e.paragraph}" if e.paragraph else "—"
        print(f"[{LABELS[e.speaker.value]} · {para} · {e.speaker.confidence:.0%}{flag}] {e.status.value:<8} {e.source:<4} {e.text[:90]}")


if __name__ == "__main__":
    main()
