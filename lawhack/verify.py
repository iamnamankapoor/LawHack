"""Check who a drafted text says is speaking against the attribution registry."""

import re
from enum import Enum

from lawhack.retrieval import BM25, coverage
from lawhack.schema import Registry, RegistryEntry, Speaker, Zone
from lawhack.segmenter import split_sentences

SUPPORT_MIN = 0.6  # share of a claim's content words found in its best segment

# Order matters: "la cour d'appel" must be tested before "la Cour".
_CLAIM_CUES: list[tuple[re.Pattern[str], Speaker]] = [
    (re.compile(r"cour d'appel|juges? du fond|l'arr[êe]t (attaqu[ée]|d'appel)|juridiction du fond|premiers? juges?", re.I), Speaker.JURIDICTION_FOND),
    (re.compile(r"\b(le|la|les) (demandeu?r(esse)?s?|requérant|auteur du pourvoi)\b|\ble moyen\b|fait grief|reproche", re.I), Speaker.DEMANDEUR),
    (re.compile(r"\b(le|la|les) défendeu?r(esse)?s?\b", re.I), Speaker.DEFENDEUR),
    (re.compile(r"avocat général|ministère public|parquet", re.I), Speaker.MINISTERE_PUBLIC),
    (re.compile(r"\b(la )?cour de cassation\b|\bla (haute )?(cour|juridiction)\b(?! d'appel)|\bla chambre\b", re.I), Speaker.COUR_CASSATION),
    (re.compile(r"\b(l'article|le code|la loi|ce texte)\b", re.I), Speaker.LOI),
]


class Verdict(str, Enum):
    OK = "OK"
    A_VERIFIER = "A_VERIFIER"
    MAL_ATTRIBUE = "MAL_ATTRIBUE"
    NON_SOURCE = "NON_SOURCE"
    SANS_ATTRIBUTION = "SANS_ATTRIBUTION"


def claimed_speaker(sentence: str) -> Speaker | None:
    """First speaker explicitly named in the sentence (the grammatical subject in practice)."""
    found = [(m.start(), speaker) for pattern, speaker in _CLAIM_CUES if (m := pattern.search(sentence))]
    return min(found, key=lambda x: x[0])[1] if found else None


def speakers_of(entry: RegistryEntry) -> set[str]:
    """Voices a claim may legitimately attribute this segment to.

    The chain head is always the Cour de cassation reporting someone else, so it only counts
    when the Cour is the speaker itself; the reported voices (chain[1:]) always count, e.g.
    « la cour d'appel a retenu à bon droit » is both the Cour's and the cour d'appel's.
    """
    return {entry.speaker.value, *(s.value for s in entry.chain[1:])}


def _strip_cues(sentence: str) -> str:
    for pattern, _ in _CLAIM_CUES:
        sentence = pattern.sub(" ", sentence)
    return sentence


def check(registry: Registry, text: str, threshold: float = 0.8) -> list[dict]:
    entries = [e for e in registry.entries if e.zone is not Zone.METADONNEES]
    index = BM25([e.text for e in entries])
    results = []
    for s, e in split_sentences(text):
        sentence = text[s:e].strip()
        if not sentence:
            continue
        claim = claimed_speaker(sentence)
        query = _strip_cues(sentence)
        hits = index.top(query, k=3)
        best = max(hits, key=lambda h: coverage(query, entries[h[0]].text), default=None)
        support = coverage(query, entries[best[0]].text) if best else 0.0
        entry = entries[best[0]] if best and support >= SUPPORT_MIN else None

        if entry is None:
            verdict = Verdict.NON_SOURCE
        elif claim is None:
            verdict = Verdict.SANS_ATTRIBUTION
        elif claim.value not in speakers_of(entry):
            verdict = Verdict.MAL_ATTRIBUE
        elif entry.speaker.confidence < threshold:
            verdict = Verdict.A_VERIFIER
        else:
            verdict = Verdict.OK
        results.append({"sentence": sentence, "claimed_speaker": claim.value if claim else None,
                        "verdict": verdict.value, "support": round(support, 2), "entry": entry})
    return results
