#!/usr/bin/env python3
"""
LinkedIn → Portfolio sync script.

Reads linkedin-profile.md (source of truth) and index.html,
asks Claude to produce a JSON diff, applies it, and writes
a PR description to /tmp/pr_description.md.
"""
import os
import json
import sys
import anthropic


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY secret is not set.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists("linkedin-profile.md"):
        print("ERROR: linkedin-profile.md not found in repo root.", file=sys.stderr)
        sys.exit(1)

    with open("linkedin-profile.md", "r", encoding="utf-8") as f:
        linkedin_content = f.read()

    with open("index.html", "r", encoding="utf-8") as f:
        current_html = f.read()

    print("linkedin-profile.md loaded.")
    print("index.html loaded.")
    print("\nCalling Claude API…")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        system=(
            "You are a portfolio website sync assistant. "
            "Your job is to make index.html consistent with the LinkedIn profile "
            "source-of-truth document. Return ONLY a JSON array of surgical "
            "find-and-replace changes. No markdown fences, no explanation."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "## LinkedIn profile (source of truth)\n\n"
                    f"{linkedin_content}\n\n"
                    "## Current index.html\n\n"
                    f"```html\n{current_html}\n```\n\n"
                    "Compare the two. Return a JSON array where each element is:\n"
                    "{\n"
                    '  "old": "exact string to find in index.html (unique match only)",\n'
                    '  "new": "replacement string",\n'
                    '  "description": "one-line summary of the change"\n'
                    "}\n\n"
                    "Rules:\n"
                    "- Only include changes where the LinkedIn profile explicitly states "
                    "a different value than what is currently in index.html.\n"
                    "- Do not invent or guess changes.\n"
                    "- Each 'old' value must appear exactly once in index.html.\n"
                    "- Return ONLY the JSON array."
                ),
            }
        ],
    )

    raw = strip_code_fences(response.content[0].text)

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Claude returned invalid JSON — {exc}", file=sys.stderr)
        print("Raw response:\n", raw[:800], file=sys.stderr)
        sys.exit(1)

    print(f"\nClaude proposed {len(changes)} change(s). Applying…\n")

    updated_html = current_html
    applied: list[str] = []
    skipped: list[str] = []

    for change in changes:
        old  = change.get("old", "")
        new  = change.get("new", "")
        desc = change.get("description", "")

        if not old:
            skipped.append(f"Empty 'old' — {desc}")
            continue

        count = updated_html.count(old)
        if count == 1:
            updated_html = updated_html.replace(old, new, 1)
            applied.append(desc)
            print(f"  ✓  {desc}")
        elif count == 0:
            skipped.append(f"Not found: {old[:70]}…")
            print(f"  ✗  Not found: {old[:70]}…")
        else:
            updated_html = updated_html.replace(old, new, 1)
            applied.append(f"{desc}  *(first of {count} occurrences)*")
            print(f"  ⚠  Ambiguous ({count} matches), applied first: {desc}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(updated_html)

    # PR description
    applied_md = "\n".join(f"- {d}" for d in applied) or "_None_"
    skipped_section = ""
    if skipped:
        skipped_md = "\n".join(f"- {s}" for s in skipped)
        skipped_section = f"\n### ⚠️ Skipped ({len(skipped)})\n{skipped_md}\n"

    pr_body = (
        "## 🔄 LinkedIn → Portfolio Sync\n\n"
        "Claude compared `linkedin-profile.md` against `index.html` "
        "and proposed the following changes:\n\n"
        f"### ✅ Applied ({len(applied)})\n{applied_md}\n"
        f"{skipped_section}"
        "\n---\n"
        "**Review the diff in the Files Changed tab.**\n"
        "Merge to publish · Close to reject — nothing goes live until you merge.\n"
    )

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(pr_body)

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
