"""Check who a drafted text says is speaking against the attribution registry."""

import re
from enum import Enum

from lawhack.retrieval import BM25, coverage
from lawhack.schema import Registry, RegistryEntry, Speaker, Zone
from lawhack.segmenter import split_sentences
from lawhack.solution import Solution

SUPPORT_MIN = 0.6  # share of a claim's content words found in its best segment

# Order matters: "la cour d'appel" must be tested before "la Cour".
_CLAIM_CUES: list[tuple[re.Pattern[str], Speaker]] = [
    (re.compile(r"cour d['’ ]\s?appel|juges? du fond|l['’ ]\s?arr[êe]t (attaqu[ée]|d['’ ]\s?appel)|juridiction du fond|premiers? juges?", re.I), Speaker.JURIDICTION_FOND),
    (re.compile(r"\b(le|la|les) (demandeu?r(esse)?s?|requérant|auteur du pourvoi)\b|\ble moyen\b|fait grief|reproche", re.I), Speaker.DEMANDEUR),
    (re.compile(r"\b(le|la|les) défendeu?r(esse)?s?\b", re.I), Speaker.DEFENDEUR),
    (re.compile(r"avocat général|ministère public|parquet", re.I), Speaker.MINISTERE_PUBLIC),
    (re.compile(r"\b(la )?cour de cassation\b|\bla (haute )?(cour|juridiction)\b(?! d['’ ]\s?appel)|\bla chambre\b", re.I), Speaker.COUR_CASSATION),
    (re.compile(r"\b(l['’]article|le code|la loi|ce texte)\b", re.I), Speaker.LOI),
]


class Verdict(str, Enum):
    OK = "OK"
    A_VERIFIER = "A_VERIFIER"
    MAL_ATTRIBUE = "MAL_ATTRIBUE"
    NON_SOURCE = "NON_SOURCE"
    SANS_ATTRIBUTION = "SANS_ATTRIBUTION"
    CONTREDIT = "CONTREDIT"


_SAYS_CASSATION = re.compile(r"\b(cass[ée]e?s?|casse(nt)?|annul[ée]e?s?|annule(nt)?|censur[ée]e?s?|censure(nt)?)\b", re.I)
_SAYS_REJET = re.compile(r"\b(rejet(é|ée|és|ées|te|tent)?|confirm[ée]e?s?|confirme(nt)?)\b.{0,40}\b(pourvoi|arr[êe]t|décision)|\bpourvoi\b.{0,30}\brejet", re.I)
_NEGATION = re.compile(r"\bn['’e]\s?\w+ (pas|point)\b|\bne (pas|point)\b|\bsans (casser|rejeter)\b", re.I)


def contradiction(sentence: str, claim: Speaker | None, solution: Solution | None) -> str | None:
    """A sentence stating an outcome the decision does not have, or giving the power to quash to another court."""
    says_cassation = bool(_SAYS_CASSATION.search(sentence)) and not _NEGATION.search(sentence)
    if says_cassation and claim is Speaker.JURIDICTION_FOND:
        return "Seule la Cour de cassation casse un arrêt : la cour d'appel est la juridiction dont l'arrêt est attaqué."
    if solution is None or solution is Solution.AUTRE or _NEGATION.search(sentence):
        return None
    if says_cassation and solution is Solution.REJET:
        return "Contredit par le dispositif : la Cour rejette le pourvoi (solution : REJET), elle ne casse pas l'arrêt."
    if _SAYS_REJET.search(sentence) and solution is not Solution.REJET:
        return f"Contredit par le dispositif : la Cour casse l'arrêt (solution : {solution.value.replace('_', ' ')})."
    return None


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


def strip_cues(sentence: str) -> str:
    for pattern, _ in _CLAIM_CUES:
        sentence = pattern.sub(" ", sentence)
    return sentence


_SEGMENT_REF = re.compile(r"\bS-(\d{3})\b")
_PARAGRAPH_REF = re.compile(r"§\s?(\d+)")
_BADGE = re.compile(r"\[[^\]]*\]")


def cited(registry: Registry, sentence: str) -> list[RegistryEntry]:
    """Segments the sentence cites explicitly ([S-013], §7): checked first, before any retrieval."""
    ids = {f"S-{n}" for n in _SEGMENT_REF.findall(sentence)}
    paragraphs = {int(n) for n in _PARAGRAPH_REF.findall(sentence)}
    return [e for e in registry.entries if e.id in ids or (e.paragraph in paragraphs and e.zone is not Zone.METADONNEES)]


def check(registry: Registry, text: str, threshold: float = 0.8, solution: Solution | None = None) -> list[dict]:
    entries = [e for e in registry.entries if e.zone is not Zone.METADONNEES]
    index = BM25([e.text for e in entries])
    results = []
    for s, e in split_sentences(text):
        sentence = text[s:e].strip()
        if not sentence:
            continue
        claim = claimed_speaker(_BADGE.sub(" ", sentence))
        query = strip_cues(_BADGE.sub(" ", _PARAGRAPH_REF.sub(" ", _SEGMENT_REF.sub(" ", sentence))))
        refs = cited(registry, sentence)
        best = max(refs, key=lambda c: coverage(query, c.text), default=None)
        wrong_citation = bool(refs) and coverage(query, best.text) < SUPPORT_MIN
        if not refs or wrong_citation:
            best = max((entries[i] for i, _ in index.top(query, k=3)), key=lambda c: coverage(query, c.text), default=None)
        support = coverage(query, best.text) if best else 0.0
        entry = best if best and support >= SUPPORT_MIN else None

        contradicted = contradiction(_BADGE.sub(" ", sentence), claim, solution)
        if contradicted:
            verdict = Verdict.CONTREDIT
            entry = entry or next((x for x in registry.entries if x.zone is Zone.DISPOSITIF), None)
        elif entry is None:
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
                        "verdict": verdict.value, "support": round(support, 2), "entry": entry,
                        "wrong_citation": wrong_citation, "contradiction": contradicted})
    return results
