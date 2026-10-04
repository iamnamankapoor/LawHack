"""Thin clients for Vercel AI Gateway: Jev (typed evaluation) and chat LLMs."""
import json, os, time, urllib.error, urllib.request

BASE = "https://ai-gateway.vercel.sh"


def _load_env():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


_load_env()


def _post(path, body, retries=3):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + os.environ["AI_GATEWAY_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=180))
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == retries - 1:
                raise RuntimeError(f"{path} {e.code}: {e.read().decode()[:500]}") from None
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2 * (attempt + 1))


def jev(state, questions, fallback_model=None, confidence_below=0.6):
    """Evaluate typed questions against state. Returns the `answers` dict.

    With fallback_model, the gateway re-runs uncertain choice questions on that LLM.
    """
    body = {"model": "typesafe-ai/jev", "state": state, "questions": questions}
    if fallback_model:
        body["providerOptions"] = {"gateway": {"models": [
            {"model": fallback_model, "when": {"question": q, "confidenceBelow": confidence_below}}
            for q, spec in questions.items() if spec["type"] == "choice"]}}
    return _post("/typesafe/v1/systemone", body)["answers"]


def chat(model, system, user, temperature=None):
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if temperature is not None:
        body["temperature"] = temperature
    return _post("/v1/chat/completions", body)["choices"][0]["message"]["content"]
