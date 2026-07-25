#!/usr/bin/env python3
"""
Live LLM Eval Runner — run evals against an actual Ollama model.

Supports both local Ollama (http://host:11434) and Ollama Cloud (https://ollama.com/v1).

Usage:
    # Local Ollama
    python3 live_eval.py --skill-path ../github/bernard-git-context --model llama3.2 --ollama-url http://localhost:11434

    # Ollama Cloud (reads OLLAMA_API_KEY from env)
    python3 live_eval.py --skill-path ../github/bernard-git-context --model qwen2.5 --ollama-url https://ollama.com/v1

    # With explicit API key and output transcript
    python3 live_eval.py --skill-path ../github/bernard-git-context --model qwen2.5 --ollama-url https://ollama.com/v1 --api-key $OLLAMA_API_KEY --output-transcript /tmp/results.jsonl
"""

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.request
from typing import Any

import yaml

# Import shared functions from skill_eval.py
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from skill_eval import (
    load_prompts,
    load_rubric,
    score_prompt,
    compute_category_scores,
    compute_overall_score,
    print_report,
)


def load_skill_markdown(skill_path: pathlib.Path) -> str:
    """Load the SKILL.md content for a skill."""
    skill_file = skill_path / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text(encoding="utf-8")
    for md in skill_path.glob("*.md"):
        return md.read_text(encoding="utf-8")
    return ""


def build_system_prompt(skill_md: str) -> str:
    """Build the system prompt that includes the skill context."""
    return f"""You are an AI assistant agent. You have been loaded with the following skill:

--- SKILL START ---
{skill_md[:8000]}
--- SKILL END ---

When a user asks you something, you must decide whether to use the skill above.

Respond in this exact format:

REASONING: <your step-by-step reasoning about what the user wants and what you would do>

COMMANDS:
- <command 1>
- <command 2>

If no commands are needed, write "COMMANDS:" followed by nothing.
If the skill should NOT trigger for this prompt, write "SKILL_NOT_TRIGGERED" as your entire response.
"""


def is_cloud_ollama(ollama_url: str) -> bool:
    """Detect if URL points to Ollama Cloud (OpenAI-compatible) vs local Ollama."""
    return "/v1" in ollama_url or "ollama.com" in ollama_url or "api.openai" in ollama_url


def query_local_ollama(prompt: str, model: str, ollama_url: str, system: str = "") -> dict[str, Any]:
    """Send a prompt to local Ollama /api/generate endpoint."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2048},
    }
    if system:
        payload["system"] = system

    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "raw": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"error": str(e), "raw": ""}

    return {"text": data.get("response", ""), "raw": data}


def query_cloud_ollama(prompt: str, model: str, ollama_url: str, api_key: str) -> dict[str, Any]:
    """Send a prompt to Ollama Cloud via OpenAI-compatible /v1/chat/completions."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Follow the user's instructions exactly."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "raw": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"error": str(e), "raw": ""}

    msg = data.get("choices", [{}])[0].get("message", {})
    return {"text": msg.get("content", ""), "raw": data}


def query_ollama(prompt: str, model: str, ollama_url: str, api_key: str = "", system: str = "") -> dict[str, Any]:
    """Route to local or cloud Ollama based on URL."""
    if is_cloud_ollama(ollama_url):
        # For cloud, prepend system prompt to the user message
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        return query_cloud_ollama(full_prompt, model, ollama_url, api_key)
    else:
        return query_local_ollama(prompt, model, ollama_url, system)


def parse_ollama_response(text: str) -> dict[str, Any]:
    """Parse reasoning and commands from the model response."""
    text = text.strip()

    if "SKILL_NOT_TRIGGERED" in text:
        return {"reasoning": "Skill correctly did not trigger.", "commands": [], "triggered": False}

    reasoning_match = re.search(r"REASONING:\s*(.*?)(?:\n\nCOMMANDS:|$)", text, re.DOTALL)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else text

    commands = []
    cmd_match = re.search(r"COMMANDS:\s*(.*?)$", text, re.DOTALL)
    if cmd_match:
        cmd_text = cmd_match.group(1).strip()
        for line in cmd_text.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                commands.append(line[1:].strip())
            elif line:
                commands.append(line)

    return {"reasoning": reasoning, "commands": commands, "triggered": True}


def run_live_eval(skill_path: pathlib.Path, model: str, ollama_url: str, api_key: str) -> list[dict]:
    """Run eval against live LLM and return results."""
    prompts = load_prompts(skill_path)
    skill_md = load_skill_markdown(skill_path)
    system = build_system_prompt(skill_md)

    results = []
    total = len(prompts)
    print(f"Running {total} prompts against model '{model}' via {ollama_url}...")
    print()

    for i, prompt_def in enumerate(prompts, 1):
        prompt_text = prompt_def["prompt"]
        print(f"  [{i}/{total}] {prompt_def['id']} ... ", end="", flush=True)

        user_prompt = f'The user asks: "{prompt_text}"'
        resp = query_ollama(user_prompt, model, ollama_url, api_key, system)

        if "error" in resp:
            print(f"ERROR: {resp['error']}")
            results.append({
                "prompt": prompt_text,
                "id": prompt_def["id"],
                "category": prompt_def.get("category", ""),
                "error": resp["error"],
                "reasoning": "",
                "commands": [],
            })
            continue

        parsed = parse_ollama_response(resp["text"])
        turn = {
            "prompt": prompt_text,
            "reasoning": parsed["reasoning"],
            "commands": parsed["commands"],
        }

        try:
            result = score_prompt(prompt_def, turn if parsed["triggered"] else None)
        except Exception as e:
            print(f"[ERROR] Scoring failed: {e}")
            result = {"passed": False, "checks": {}, "errors": [str(e)], "id": prompt_def["id"], "prompt": prompt_text, "category": prompt_def.get("category", ""), "should_trigger": prompt_def.get("should_trigger", True)}

        # Add reasoning/commands to result for transcript/reporting
        result["reasoning"] = parsed["reasoning"]
        result["commands"] = parsed["commands"]
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"
        errors = result.get("errors", [])
        err_str = f" — {errors[0]}" if errors else ""
        print(f"{status}{err_str}")

    return results


def generate_transcript(results: list[dict], output_path: pathlib.Path) -> None:
    """Write a JSONL transcript from live eval results."""
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            if "error" in r:
                continue
            line = json.dumps({
                "prompt": r["prompt"],
                "reasoning": r.get("reasoning", ""),
                "commands": r.get("commands", []),
            })
            f.write(line + "\n")
    print(f"\nTranscript written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Live LLM skill evaluation runner")
    parser.add_argument("--skill-path", type=pathlib.Path, required=True,
                        help="Path to the skill directory to evaluate")
    parser.add_argument("--model", type=str, required=True,
                        help="Ollama model name (e.g. llama3.2, qwen2.5, mistral, kimi-k2.6)")
    parser.add_argument("--ollama-url", type=str, default="http://localhost:11434",
                        help="Ollama API base URL (default: http://localhost:11434; for cloud: https://ollama.com/v1)")
    parser.add_argument("--api-key", type=str, default=os.environ.get("OLLAMA_API_KEY", ""),
                        help="API key for Ollama Cloud (default: OLLAMA_API_KEY env var)")
    parser.add_argument("--output-transcript", type=pathlib.Path,
                        help="Write captured turns to a JSONL transcript file")
    parser.add_argument("--temperature", type=float, default=0.1,
                        help="Sampling temperature (default: 0.1)")
    args = parser.parse_args()

    rubric = load_rubric(args.skill_path)

    results = run_live_eval(args.skill_path, args.model, args.ollama_url, args.api_key)

    category_scores = compute_category_scores(results, rubric)
    overall = compute_overall_score(category_scores, rubric)

    print()
    print_report(results, category_scores, overall, rubric)

    if args.output_transcript:
        generate_transcript(results, args.output_transcript)


if __name__ == "__main__":
    main()
