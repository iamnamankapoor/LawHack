import asyncio
from pathlib import Path

from lawhack.attributor import build_registry
from lawhack.ingest import load_pdf, load_text
from lawhack.schema import Document, Registry, Zone
from lawhack.segmenter import segment
from lawhack.solution import Solution, detect_solution
from lawhack.system_one import SystemOneClient, TypeSafeSystemOne
from lawhack.zoning import zone_blocks

CACHE_DIR = Path("data/cache")


def load(path: str | Path) -> Document:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return load_pdf(path)
    return load_text(path.read_text())


def analyse(doc: Document, client: SystemOneClient | None = None, use_cache: bool = True) -> tuple[Registry, Solution]:
    blocks = zone_blocks(doc)
    solution = detect_solution(" ".join(b.text for b in blocks if b.zone is Zone.DISPOSITIF))
    cached = CACHE_DIR / f"{doc.id}.json"
    if use_cache and cached.exists():
        return Registry.model_validate_json(cached.read_text()), solution
    registry = asyncio.run(build_registry(doc.id, segment(blocks), client or TypeSafeSystemOne()))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_text(registry.model_dump_json(indent=2))
    return registry, solution
