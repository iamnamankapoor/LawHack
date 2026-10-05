"""Get a Cour de cassation decision by pourvoi number.

Judilibre API (PISTE) when JUDILIBRE_KEY_ID is set in .env; otherwise the saved Légifrance copies in cases/raw/.
"""
import glob, json, os, urllib.parse, urllib.request

from . import gateway  # noqa: F401  (loads .env)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JUDILIBRE = {"sandbox": "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0",
             "production": "https://api.piste.gouv.fr/cassation/judilibre/v1.0"}


def _judilibre(path, params):
    base = JUDILIBRE[os.environ.get("JUDILIBRE_ENV", "sandbox")]
    req = urllib.request.Request(f"{base}{path}?{urllib.parse.urlencode(params)}",
                                 headers={"KeyId": os.environ["JUDILIBRE_KEY_ID"], "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def fetch(pourvoi):
    """Return {'pourvoi', 'text', 'zones' (or None), 'source'}. Local copies in cases/raw/ win over the API."""
    digits = pourvoi.replace(".", "").replace("-", "")
    for path in glob.glob(os.path.join(ROOT, "cases", "raw", "*.txt")):
        if digits in os.path.basename(path).replace("-", ""):
            return {"pourvoi": pourvoi, "text": open(path, encoding="utf-8").read(), "zones": None, "source": path}
    if not os.environ.get("JUDILIBRE_KEY_ID"):
        raise LookupError(f"{pourvoi} not in cases/raw/ and JUDILIBRE_KEY_ID is not set")
    hits = _judilibre("/search", {"query": pourvoi, "field": "number", "resolve_references": "false"})["results"]
    if not hits:
        raise LookupError(f"No Judilibre decision for pourvoi {pourvoi}")
    d = _judilibre("/decision", {"id": hits[0]["id"]})
    return {"pourvoi": pourvoi, "text": d["text"], "zones": d.get("zones"), "source": "judilibre"}
