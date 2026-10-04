"""Split the case-file documents into pages, paragraphs and sentences with stable ids.

Document format (see dossier/*.md): a front matter block, then pages separated by
`<!-- page N -->`, section titles as `## ` lines, paragraphs separated by blank lines,
optionally numbered `12. ...`.
"""
import json
import pathlib
import re

import os

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOSSIER = pathlib.Path(os.environ.get("DOSSIER_DIR", ROOT / "dossier"))

PAGE_RE = re.compile(r"^<!-- page (\d+) -->\s*$", re.M)
PARA_NUM_RE = re.compile(r"^(\d{1,3})\.\s+")
# Candidate sentence boundary: end punctuation (optionally followed by a closing quote/bracket),
# whitespace, then something that can start a sentence.
BOUNDARY_RE = re.compile(r"([.!?…]+(?:[\s  ]*[»\")])?)(\s+)(?=[«\"(A-ZÀ-ÖØ-Ý0-9])")
ABBREVIATIONS = {"m", "mm", "mme", "mmes", "me", "mes", "mlle", "dr", "pr", "st", "ste", "n", "no", "art",
                 "al", "c", "civ", "com", "soc", "cass", "crim", "p", "pp", "cf", "etc", "ibid", "op", "cit",
                 "s", "ss", "av", "bd", "r", "sas", "sarl", "sa", "rcs", "cpc", "vol", "réf", "ref", "tél",
                 "janv", "févr", "fév", "avr", "juil", "sept", "oct", "nov", "déc", "dec", "req", "ord",
                 "trib", "adm", "jur", "concl", "obs", "préc", "spéc", "env", "cjue", "cedh", "ta", "caa", "ce",
                 "plén", "bull", "inf", "sup"}


def parse_front_matter(raw):
    if not raw.startswith("---"):
        return {}, raw
    end = raw.index("\n---", 3)
    meta = {}
    for line in raw[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    if "version" in meta:
        meta["version"] = int(meta["version"])
    return meta, raw[end + 4:].lstrip("\n")


def split_sentences(text):
    """French-aware sentence split; never splits inside « ... » or after an abbreviation."""
    out, start = [], 0
    for m in BOUNDARY_RE.finditer(text):
        end = m.end(1)
        before = text[start:end]
        if before.count("«") > before.count("»"):
            continue  # inside a quotation
        word = re.search(r"([A-Za-zÀ-ÿ°]+)\.?[»\")]?$", text[start:m.start(1) + 1])
        if word and m.group(1).startswith(".") and word.group(1).lower().rstrip("°") in ABBREVIATIONS:
            continue
        if word and len(word.group(1)) == 1 and word.group(1).isupper():
            continue  # initials such as "J. Levinson"
        sentence = text[start:end].strip()
        if sentence:
            out.append((start, end, sentence))
        start = m.end(2)
    tail = text[start:].strip()
    if tail:
        out.append((start, start + len(text[start:].rstrip()), tail))
    return out


def load_document(path):
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    pages = []
    parts = PAGE_RE.split(body)  # ["", "1", text, "2", text, ...]
    for i in range(1, len(parts), 2):
        pages.append({"page": int(parts[i]), "text": parts[i + 1].strip("\n")})
    if not pages:
        pages = [{"page": 1, "text": body.strip()}]
    sentences, section, para_seq = [], None, 0
    for pg in pages:
        offset = 0
        for block in re.split(r"\n\s*\n", pg["text"]):
            block_start = pg["text"].find(block, offset)
            offset = block_start + len(block)
            stripped = block.strip()
            if not stripped:
                continue
            if stripped.startswith("## "):
                section = stripped[3:].strip()
                continue
            para_seq += 1
            num = PARA_NUM_RE.match(stripped)
            para = int(num.group(1)) if num else None
            text = stripped[num.end():] if num else stripped
            text_start = block_start + block.find(text)
            flat = " ".join(text.split())
            for k, (s, e, sent) in enumerate(split_sentences(flat), 1):
                label = f"§{para}" if para is not None else f"b{para_seq}"
                sentences.append({
                    "id": f"{meta.get('id', path.stem)}.p{pg['page']}.{label}.s{k}",
                    "doc": meta.get("id", path.stem), "page": pg["page"], "para": para,
                    "section": section, "text": sent,
                    # where to highlight in the page text (approximate when line breaks were collapsed)
                    "page_offset": pg["text"].find(sent[:40], text_start) if sent else -1,
                })
    return {"meta": meta, "pages": pages, "sentences": sentences}


def load_dossier(folder=DOSSIER):
    docs = [load_document(p) for p in sorted(folder.glob("*.md"))]
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    return case, docs


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    case, docs = load_dossier()
    for d in docs:
        m = d["meta"]
        print(f"{m.get('id'):<22} {m.get('author'):<7} v{m.get('version')} {m.get('date')}  "
              f"pages={len(d['pages'])} sentences={len(d['sentences'])}")
    print("total sentences:", sum(len(d["sentences"]) for d in docs))
