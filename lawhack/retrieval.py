"""Small dependency-free BM25 over registry segments."""

import math
import re
import unicodedata
from collections import Counter

_STOPWORDS = set(
    "a au aux avec ce ces cet cette d dans de des du elle en est et il ils l la le les leur lui m mais me "
    "n ne ni nos notre on ou par pas pour qu que qui s sa se ses si son sur t ta te tes ton un une vos votre "
    "y à été être a-t-il ont sont était quel quelle quels quelles est-ce".split()
)


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text) if t not in _STOPWORDS and len(t) > 1]


def _stem(token: str) -> str:
    """Very light French stemming: rejette / rejeté / rejetés → rejet."""
    if token.isdigit() or len(token) <= 4:
        return token
    token = re.sub(r"(.)\1", r"\1", token)
    return re.sub(r"(ent|es|e|s)$", "", token) or token


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(tokens(d)) for d in documents]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in q:
                f = doc.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            out.append(s)
        return out

    def top(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        ranked = sorted(enumerate(self.scores(query)), key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in ranked[:k] if s > 0]


def coverage(query: str, text: str) -> float:
    """Share of the query's content words that appear in `text`."""
    q = set(tokens(query))
    return len(q & set(tokens(text))) / len(q) if q else 0.0
