---
title: Weekly Skill Evaluations
description: Run weekly regression evaluations on all Hermes custom skills with eval definitions. Discovers skills, validates eval files, runs live LLM scoring, and delivers a regression report.
tags: [evals, regression, testing, skills, weekly, llm, ollama]
name: weekly-skill-evals
---

# Weekly Skill Evaluations

## Overview

This skill provides the tooling and methodology for systematically evaluating Hermes custom skills. The framework supports three modes:

1. **Dry-run validation** — check eval files are well-formed (fast, no LLM calls)
2. **Live LLM eval** — send prompts to a real model and score responses (for fine-tuning)
3. **Transcript replay** — score a previously captured JSONL transcript (fast replay)

**When to use:**
- User says "run skill evals", "check for regressions", "weekly eval", "test skill"
- After editing a skill's `SKILL.md`, to verify the change improved model behavior
- Comparing model performance before/after fine-tuning a skill
- Regression testing: ensuring skill updates didn't break existing behavior

**Where it lives:**
- Script: `~/.hermes/skills/software-development/weekly-skill-evals/scripts/run_evals.py`
- Live runner: `~/.hermes/skills/.evals/live_eval.py`
- Scoring engine: `~/.hermes/skills/.evals/skill_eval.py`
- Evals are per-skill in `~/.hermes/skills/<category>/<skill-name>/evals/`

## Important: Static Transcripts Are Not Enough

Running evals against pre-recorded (static) transcripts only validates file format. It tells you **nothing** about whether the skill actually works with a live model. The primary purpose of this framework is **skill fine-tuning**: editing `SKILL.md`, re-running against a live LLM, and comparing scores.

**Always use `--live` mode when evaluating skill changes.** The user will remind you if you try to run transcript-only evals for fine-tuning purposes.

Transcripts are useful only for:
- Fast replay after a model run (save with `--output-transcript`)
- Sharing results between environments
- Archiving a snapshot for later comparison

## How Eval Discovery Works

The script walks the skills directory looking for pairs of files:

```
evals/prompts.yaml    # Test cases
evals/rubric.yaml     # Scoring weights
```

If both exist, the skill is included in the weekly run.

## Running Evals

### Dry-run (validation only)

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py
```

This validates every skill's eval files are well-formed and reports coverage stats. No actual scoring happens.

### Dry-run single skill

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py --skill-path ../github/bernard-git-context
```

### Live LLM Eval

Send prompts to a real Ollama model and score responses. This is the mode for fine-tuning.

```bash
# Local Ollama
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
    --skill-path ../github/bernard-git-context \
    --live \
    --model llama3.2 \
    --ollama-url http://localhost:11434

# Ollama Cloud
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
    --skill-path ../github/bernard-git-context \
    --live \
    --model qwen2.5 \
    --ollama-url https://ollama.com/v1 \
    --api-key $OLLAMA_API_KEY
```

The `--live` flag sends each prompt to the model with the skill's `SKILL.md` prepended as a system prompt. The model's response is parsed for REASONING and COMMANDS, then scored against the rubric.

**Always use `--output-transcript`** to save results for later comparison:
```bash
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
    --skill-path ../github/bernard-git-context \
    --live --model qwen2.5 \
    --ollama-url https://ollama.com/v1 \
    --api-key $OLLAMA_API_KEY \
    --output-transcript /tmp/bernard-git-context-$(date +%Y%m%d).jsonl
```

### Score existing transcript

```bash
cd ~/.hermes/skills/.evals
python3 skill_eval.py --skill-path ../github/bernard-git-context --transcript /tmp/bernard-git-context-qwen25.jsonl
```

## Eval Results

- **PASS** ≥ 70: Skill is working correctly
- **EXCELLENT** ≥ 90: Skill is working very well
- **FAIL** < 70: Something regressed — check the per-category breakdown

## Fine-Tuning Workflow (The Primary Use Case)

The live eval is designed for iterative skill improvement. The core insight: **static transcripts don't tell you if a skill edit improved model behavior** — only a live model can. Fine-tuning is a tight loop:

1. **Baseline**: Run `--live` against your current skill to get a baseline score  
   ```bash
   python3 live_eval.py --skill-path ../github/bernard-git-context --model qwen2.5 \
     --ollama-url https://ollama.com/v1 --output-transcript /tmp/baseline.jsonl
   ```

2. **Edit**: Modify the skill's `SKILL.md` (add instructions, fix pitfalls, clarify edge cases)

3. **Re-eval**: Run `--live` again with the **same model**  
   ```bash
   python3 live_eval.py --skill-path ../github/bernard-git-context --model qwen2.5 \
     --ollama-url https://ollama.com/v1 --output-transcript /tmp/after-edit.jsonl
   ```

4. **Compare**: Did the score go up? Which categories improved? Which regressed?

5. **Iterate**: Repeat until score is stable and above PASS threshold

**Key rule**: Compare before/after on the same model. Scores vary wildly between models — a Qwen 2.5 score tells you nothing about Llama 3.2 performance.

**When transcripts ARE useful**: Save `--output-transcript` from step 1 so you can re-run `skill_eval.py` later without re-calling the LLM. This is for archival/comparison, not for the actual fine-tuning loop.

See `references/eval-format.md` for the complete eval file format specification, including field definitions, weight guidelines, and the writing workflow for new skills.

## Report Generation

Add `--report` to get a markdown report:

```bash
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
    --skill-path ../github/bernard-git-context \
    --live --model qwen2.5 --report
```

Or write to file:

```bash
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
    --report --output /tmp/skill-eval-report-$(date +%Y%m%d).md
```

## Regression Detection

The script flags regressions when:
- A skill's eval files fail validation (bad YAML, missing fields)
- A live eval score drops below the PASS threshold
- A previously PASSing skill now FAILs

## Pitfalls

- **Live evals cost tokens**: Each prompt is a separate LLM call. A 20-prompt skill × 18 prompts = 18 API calls.
- **Use a consistent model**: Compare before/after on the same model. Scores vary wildly between models.
- **Temperature matters**: Live eval uses temp=0.1 for determinism. Don't use high temps for eval.
- **Ollama Cloud requires API key**: Set `OLLAMA_API_KEY` in your environment, or pass `--api-key`.
