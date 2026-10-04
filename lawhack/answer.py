"""System 2: retrieve registry segments with Jev, draft a cited answer with Mistral, verify with Jev."""

import asyncio
import os
import re
import time

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul

from lawhack.schema import Registry, RegistryEntry, Zone
from lawhack.segmenter import split_sentences
from lawhack.system_one import SystemOneClient

ANSWER_ABOVE = 0.8
WARN_ABOVE = 0.5
MAX_PARAGRAPHS = 4
MIN_PARAGRAPH_P = 0.05
COVER = 0.9
PARAGRAPH_CHARS = 1500
NONE = "NONE"

SPEAKER_LABELS = {
    "COUR_CASSATION": "Cour",
    "JURIDICTION_FOND": "Cour d'appel",
    "DEMANDEUR": "Demandeur",
    "DEFENDEUR": "Défendeur",
    "MINISTERE_PUBLIC": "Ministère public",
    "LOI": "Loi",
    "INDETERMINE": "Indéterminé",
}
ZONE_LABELS = {
    Zone.INTRODUCTION: "En-tête",
    Zone.EXPOSE: "Faits et procédure",
    Zone.MOYENS: "Énoncé du moyen",
    Zone.MOTIVATIONS: "Réponse de la Cour",
    Zone.DISPOSITIF: "Dispositif",
    Zone.METADONNEES: "Métadonnées",
}
NOT_ADDRESSED = "L'arrêt ne traite pas cette question."
_CITE = re.compile(r"\[(S-\d{3})\]")
_LOWER_COURT = re.compile(r"\b(cour d'appel|arr[êe]t attaqu[ée]|juges? du fond|tribunal)\b", re.I)
_PARTIES = {"DEMANDEUR", "DEFENDEUR"}


class Pill(BaseModel):
    segment_id: str
    speaker: str
    label: str
    paragraph: int | None
    zone_label: str
    confidence: float
    level: str  # "ok" | "warn" | "unsupported"
    source_text: str
    probabilities: dict[str, float]
    note: str | None = None


class AnswerSentence(BaseModel):
    text: str
    pills: list[Pill]
    supported: float  # Jev probability that the cited segments support this sentence as attributed


class Answer(BaseModel):
    question: str
    sentences: list[AnswerSentence]
    abstained: bool = False

    def render(self) -> str:
        if self.abstained:
            return NOT_ADDRESSED
        out = []
        for s in self.sentences:
            tags = " ".join(_tag(p) for p in s.pills) or "[non sourcé ⚠]"
            out.append(f"{s.text} {tags}")
        return " ".join(out)


def _tag(p: Pill) -> str:
    para = f"§{p.paragraph}" if p.paragraph else p.zone_label
    warn = " ⚠" if p.level != "ok" else ""
    return f"[{p.label} · {para} · {p.confidence:.0%}{warn}]"


def _describe(e: RegistryEntry) -> str:
    para = f"§{e.paragraph}" if e.paragraph else "sans numéro"
    return (f"[{e.id}] locuteur={SPEAKER_LABELS[e.speaker.value]} ({e.speaker.confidence:.0%}) · "
            f"rubrique={ZONE_LABELS[e.zone]} · {para} · statut={e.status.value}\n{e.text}")


async def retrieve(registry: Registry, question: str, client: SystemOneClient) -> list[RegistryEntry]:
    """Jev picks the paragraph(s) answering the question (or none → abstention).

    A paragraph-level `choice` is far more reliable than per-sentence yes/no over the whole decision.
    The Cour's answer to a retrieved moyen is always added so the drafter can say whether it was upheld.
    """
    paragraphs: dict[str, list[RegistryEntry]] = {}
    for e in registry.entries:
        if e.zone not in (Zone.INTRODUCTION, Zone.METADONNEES):
            paragraphs.setdefault(f"P{e.block}", []).append(e)
    state = {
        "question": question,
        "paragraphs": {
            key: {"section": _section(group[0]), "text": " ".join(e.text for e in group)[:PARAGRAPH_CHARS]}
            for key, group in paragraphs.items()
        },
    }
    keys = [*paragraphs, NONE]
    # Two passes with reversed option order counter Jev's first-option bias and run-to-run variance;
    # we abstain only when both passes agree that no paragraph answers.
    passes = await asyncio.gather(*(client.decide(state, {"best": _paragraph_choice(order)}) for order in (keys, keys[::-1])))
    votes = [r.decisions["best"].probabilities for r in passes]
    if all(max(v, key=v.get) == NONE for v in votes):
        return []
    averaged = {k: sum(v.get(k, 0.0) for v in votes) / len(votes) for k in keys if k != NONE}
    ranked = sorted(averaged.items(), key=lambda t: -t[1])
    picked: dict[str, RegistryEntry] = {}
    cumulative = 0.0
    for key, p in ranked[:MAX_PARAGRAPHS]:
        if key == NONE or p < MIN_PARAGRAPH_P or cumulative >= COVER:
            break
        cumulative += p
        for e in paragraphs[key]:
            picked[e.id] = e
    # The operative ruling is short and needed to state what the Cour actually decided.
    for e in registry.entries:
        if e.zone is Zone.DISPOSITIF:
            picked.setdefault(e.id, e)
    for e in list(picked.values()):
        if e.zone is Zone.MOYENS and not _is_annexed_moyen(e):
            for reply in _court_reply(registry, e):
                picked.setdefault(reply.id, reply)
    return sorted(picked.values(), key=lambda e: e.start)


def _paragraph_choice(keys: list[str]) -> Choice:
    criteria = {
        key: "No paragraph of the decision answers the question" if key == NONE
        else f"Paragraph `paragraphs.{key}` answers the question"
        for key in keys
    }
    return Choice(instructions="Which paragraph of the decision best answers `question`?", criteria=criteria)


def _section(e: RegistryEntry) -> str:
    if _is_annexed_moyen(e):
        return "Moyen annexé : texte intégral de l'argument du demandeur (pas la décision)"
    return {
        Zone.MOYENS: "Énoncé du moyen : argument du demandeur (pas la décision)",
        Zone.DISPOSITIF: "Dispositif : décision de la Cour",
        Zone.MOTIVATIONS: "Réponse de la Cour : raisonnement de la Cour",
        Zone.EXPOSE: "Faits et procédure",
    }.get(e.zone, ZONE_LABELS[e.zone])


def _is_annexed_moyen(e: RegistryEntry) -> bool:
    return (e.heading or "").upper().startswith("MOYEN ANNEXE")


def _court_reply(registry: Registry, moyen: RegistryEntry) -> list[RegistryEntry]:
    """Sentences of the « Réponse de la Cour » that follow a moyen, until the next moyen or the dispositif."""
    after = [e for e in registry.entries if e.start > moyen.start]
    reply: list[RegistryEntry] = []
    for e in after:
        if e.zone is Zone.MOTIVATIONS:
            reply.append(e)
        elif reply or e.zone is not Zone.MOYENS:
            break
    return reply


SYSTEM_PROMPT = """Tu es LawHack, assistant juridique qui répond UNIQUEMENT à partir des extraits d'un arrêt de la Cour de cassation.
Chaque extrait porte un identifiant [S-xxx], son locuteur (Cour, Cour d'appel, Demandeur…), sa rubrique et son paragraphe.

Règles impératives :
- Chaque phrase de ta réponse se termine par le ou les identifiants qui la justifient, ex. « … [S-012] ».
- Attribue chaque affirmation à son vrai locuteur : « la Cour décide/juge », « la cour d'appel a retenu », « le demandeur soutient ».
  Ne présente jamais l'argument d'une partie ou le motif de la cour d'appel comme une décision de la Cour.
- Si la Cour approuve la cour d'appel (« à bon droit », « exactement déduit »), dis-le explicitement.
- Si le point n'apparaît que dans le moyen, écris que la Cour ne le tranche pas et que c'est l'argument du demandeur.
- Si les extraits ne permettent pas de répondre, réponds exactement : « L'arrêt ne traite pas cette question. »
- N'utilise aucune connaissance extérieure à ces extraits. Réponse en français, concise (au plus 5 phrases)."""


def draft(question: str, context: list[RegistryEntry], model: str | None = None) -> str:
    from mistralai.client import Mistral
    from mistralai.client.errors import SDKError

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    excerpts = "\n\n".join(_describe(e) for e in sorted(context, key=lambda e: e.id))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Extraits :\n\n{excerpts}\n\nQuestion : {question}"},
    ]
    for attempt in range(5):
        try:
            response = client.chat.complete(
                model=model or os.environ.get("ANSWER_MODEL", "mistral-medium-latest"), temperature=0, messages=messages
            )
            return response.choices[0].message.content.strip()
        except SDKError as error:
            if error.status_code != 429 or attempt == 4:
                raise
            time.sleep(2 ** attempt)


async def verify(draft_text: str, registry: Registry, client: SystemOneClient) -> list[AnswerSentence]:
    spans = [draft_text[s:e].strip() for s, e in split_sentences(draft_text)]
    sentences: list[tuple[str, list[RegistryEntry]]] = []
    for span in spans:
        cited = [registry.by_id(i) for i in dict.fromkeys(_CITE.findall(span))]
        sentences.append((re.sub(r"\s+([.,;:!?])", r"\1", _CITE.sub("", span)).strip(), [c for c in cited if c]))

    # One Jev call per claim: batched questions influence each other and drag correct claims down.
    async def check(i: int, text: str, cited: list[RegistryEntry]) -> tuple[str, object]:
        state = {"claim": text, "cited_sentences": {c.id: {"speaker": c.speaker.value, "text": c.text} for c in cited}}
        question = Noul(
            instructions=(
                "Is `claim` fully supported by `cited_sentences`, AND does it attribute each statement to the same "
                "speaker as the cited sentences (court of cassation vs lower court vs party)?"
            )
        )
        return f"ok:{i}", (await client.decide(state, {"ok": question})).decisions["ok"]

    checks = [check(i, text, cited) for i, (text, cited) in enumerate(sentences) if cited]
    decisions = dict(await asyncio.gather(*checks))

    out: list[AnswerSentence] = []
    for i, (text, cited) in enumerate(sentences):
        if not text:
            continue
        supported = decisions[f"ok:{i}"].probabilities["yes"] if cited else 0.0
        pills = []
        for c in cited:
            confidence = min(c.speaker.confidence, supported)
            level = "ok" if confidence >= ANSWER_ABOVE else "warn" if confidence >= WARN_ABOVE else "unsupported"
            note = None
            if _reports_lower_court(text, c):
                # The party's moyen paraphrases the arrêt attaqué: a real source, but second-hand.
                confidence, level = c.speaker.confidence, "warn"
                who = SPEAKER_LABELS[c.speaker.value].lower()
                note = f"Rapporté par le {who}" + (f" (§{c.paragraph})" if c.paragraph else "") + ", pas par la Cour."
            pills.append(Pill(
                segment_id=c.id, speaker=c.speaker.value, label=SPEAKER_LABELS[c.speaker.value],
                paragraph=c.paragraph, zone_label=ZONE_LABELS[c.zone], confidence=round(confidence, 3),
                level=level, source_text=c.text, probabilities=c.speaker.probabilities, note=note,
            ))
        out.append(AnswerSentence(text=text, pills=pills, supported=round(supported, 3)))
    return out


def _reports_lower_court(claim: str, cited: RegistryEntry) -> bool:
    return cited.zone is Zone.MOYENS and cited.speaker.value in _PARTIES and bool(_LOWER_COURT.search(claim))


async def ask(registry: Registry, question: str, client: SystemOneClient, model: str | None = None) -> Answer:
    context = await retrieve(registry, question, client)
    if not context:
        return Answer(question=question, sentences=[], abstained=True)
    text = await asyncio.to_thread(draft, question, context, model)
    if text.strip().startswith(NOT_ADDRESSED):
        return Answer(question=question, sentences=[], abstained=True)
    return Answer(question=question, sentences=await verify(text, registry, client))
