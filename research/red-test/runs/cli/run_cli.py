"""Run red-test prompts against Claude models via `claude -p` (no tools, minimal system prompt, empty cwd).

Usage: python3 runs/cli/run_cli.py
Outputs: runs/cli/out/<model>/<prompt>__run<N>.json
"""
import json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(ROOT, "..", "prompts")
OUT = os.path.join(ROOT, "out")
SYSTEM = "Tu es un assistant juridique."

MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-sonnet-5-5",
    "claude-opus-4-5", "claude-opus-4-6", "claude-opus-5", "claude-opus-5-5",
    "claude-fable-5-1",
]
JOBS = [("C2-Q1", 3), ("C2-CHUNK", 1), ("C4-Q3", 1)]

EMPTY_CWD = tempfile.mkdtemp(prefix="redtest-")


def run(model, prompt_id, n):
    path = os.path.join(OUT, model, f"{prompt_id}__run{n}.json")
    if os.path.exists(path):
        return path, "cached"
    prompt = open(os.path.join(PROMPTS, f"{prompt_id}.txt"), encoding="utf-8").read()
    env = dict(os.environ, CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP="1")
    p = subprocess.run(
        ["claude", "-p", "--model", model, "--tools", "", "--system-prompt", SYSTEM,
         "--strict-mcp-config", "--no-session-persistence", "--output-format", "json"],
        input=prompt, capture_output=True, text=True, cwd=EMPTY_CWD, env=env, timeout=600,
    )
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        d = {"is_error": True, "raw": p.stdout[-2000:], "stderr": p.stderr[-2000:]}
    rec = {"model": model, "prompt_id": prompt_id, "run": n,
           "models_used": list((d.get("modelUsage") or {}).keys()),
           "is_error": d.get("is_error"), "answer": d.get("result"), "raw": d.get("raw")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path, "error" if rec["is_error"] else "ok"


if __name__ == "__main__":
    tasks = [(m, pid, n) for m in MODELS for pid, k in JOBS for n in range(1, k + 1)]
    with ThreadPoolExecutor(max_workers=int(sys.argv[1]) if len(sys.argv) > 1 else 6) as ex:
        for path, status in ex.map(lambda t: run(*t), tasks):
            print(status, os.path.relpath(path, ROOT), flush=True)
