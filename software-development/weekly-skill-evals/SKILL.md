---
title: Weekly Skill Evaluations
description: Run weekly regression evaluations on all Hermes custom skills with eval definitions. Discovers skills, validates eval files, runs scoring, and delivers a regression report.
tags: [evals, regression, testing, skills, weekly]
name: weekly-skill-evals
---

# Weekly Skill Evaluations

## Overview

Every week, run automated evaluations across all Hermes skills that have eval definitions (`evals/prompts.yaml` + `evals/rubric.yaml`). This catches regressions — when a skill stops triggering correctly, forgets a security rule, or breaks a fallback pattern.

**When to use:**
- User says "run skill evals", "check for regressions", "weekly eval"
- A cron job fires every Sunday morning
- After updating a skill, to verify nothing broke

**Where it lives:**
- Script: `~/.hermes/skills/software-development/weekly-skill-evals/scripts/run_evals.py`
- Evals are per-skill in `~/.hermes/skills/<category>/<skill-name>/evals/`

## How Eval Discovery Works

The script walks the skills directory looking for pairs of files:

```
evals/prompts.yaml    # Test cases
evals/rubric.yaml     # Scoring weights
```

If both exist, the skill is included in the weekly run.

## Running Evals

### Manual run (all skills)

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py
```

This runs in **dry-run mode** by default — it validates every skill's eval files are well-formed and reports coverage stats. No actual scoring happens unless transcripts exist.

### Manual run (single skill)

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py --skill-path ../github/bernard-git-context
```

### With transcripts (full scoring)

If you've collected transcript files for a skill:

```bash
cd ~/.hermes/skills/.evals
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
  --skill-path ../github/bernard-git-context \
  --transcript-path /mnt/data/skill-transcripts/bernard-git-context/latest.jsonl
```

### Generate markdown report

```bash
python3 ../software-development/weekly-skill-evals/scripts/run_evals.py \
  --report --output /tmp/skill-eval-report-$(date +%Y%m%d).md
```

## Report Format

A weekly report looks like:

```
# Skill Eval Report — 2026-07-24

## Summary
- Skills evaluated: 2
- Skills with transcripts: 0
- Overall pass rate: 100% (dry-run only)

## bernard-git-context
- Prompts: 18 (14 positive triggers, 4 negative triggers)
- Rubric categories: 7
- Dry-run: PASS
- Score: N/A (no transcript)
- Categories: trigger(20), identity(15), gh_path(5), fallback(10), security(20), pitfall(15), verification(5)

## github-repo-management
- Prompts: 32 (29 positive triggers, 3 negative triggers)
- Rubric categories: 12
- Dry-run: PASS
- Score: N/A (no transcript)

## Regressions
None detected.
```

## What Counts as a Regression

A regression is any of:

1. **Trigger failure** — skill fires on a negative trigger or misses a positive trigger
2. **Score drop** — overall score below 70 (PASS threshold) or dropped from previous week
3. **Eval file invalid** — prompts.yaml or rubric.yaml has schema errors
4. **Missing coverage** — a skill category has no prompts

## Cron Schedule

The weekly eval runs every **Sunday at 08:00 CEST**.

To set it up:

```bash
hermes cron create \
  --name "weekly-skill-evals" \
  --schedule "0 8 * * 0" \
  --skill weekly-skill-evals \
  --deliver "telegram:YOUR_DM_CHAT_ID"
```

**Important:** Deliver to Bernard's Telegram DM first for review. Only after manual review should results go to the family group (`vdM Home`).

## Dependencies

- Python 3.9+
- PyYAML (`pip install pyyaml`)
- Existing `skill_eval.py` in `~/.hermes/skills/.evals/`

## Adding Evals to a New Skill

1. Write `evals/prompts.yaml` with positive and negative triggers
2. Write `evals/rubric.yaml` with weighted categories
3. Run `python3 run_evals.py --skill-path <path>` to validate
4. Collect transcripts over time for scoring
5. The skill is automatically included in weekly runs

## References

- Eval runner: `~/.hermes/skills/.evals/skill_eval.py`
- Eval format docs: `~/.hermes/skills/.evals/README.md`
- GitHub repo: `https://github.com/BvdMerwe-agent/hermes-skill-evals`
