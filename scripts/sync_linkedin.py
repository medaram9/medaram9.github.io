#!/usr/bin/env python3
"""
LinkedIn → Portfolio sync script.
Reads current index.html and LinkedIn changes from env vars,
calls Claude API to generate a targeted diff, applies it, and
writes a PR description to /tmp/pr_description.md.
"""
import os
import json
import sys
import anthropic


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop ```json or ``` opening line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    linkedin_changes = os.environ.get("LINKEDIN_CHANGES", "")

    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY secret is not set.", file=sys.stderr)
        sys.exit(1)

    if not linkedin_changes.strip():
        print("ERROR: No LinkedIn changes provided.", file=sys.stderr)
        sys.exit(1)

    with open("index.html", "r", encoding="utf-8") as f:
        current_html = f.read()

    client = anthropic.Anthropic(api_key=api_key)

    print("Calling Claude API to analyse changes...")
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        system=(
            "You are a portfolio website sync assistant. "
            "Given the current index.html and LinkedIn profile updates, "
            "return ONLY a JSON array of surgical find-and-replace changes. "
            "No markdown fences, no preamble — just the raw JSON array."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Current index.html:\n```html\n{current_html}\n```\n\n"
                    f"LinkedIn profile updates to apply:\n{linkedin_changes}\n\n"
                    "Return a JSON array where each element is an object with:\n"
                    '- "old": exact string to find (must appear exactly once in the HTML)\n'
                    '- "new": replacement string\n'
                    '- "description": one-line summary of the change\n\n'
                    "Only include changes that are directly supported by the LinkedIn "
                    "updates provided above. Do not invent changes. "
                    "Return ONLY the JSON array, nothing else."
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

    print(f"Claude proposed {len(changes)} change(s). Applying...")

    updated_html = current_html
    applied: list[str] = []
    skipped: list[str] = []

    for change in changes:
        old = change.get("old", "")
        new = change.get("new", "")
        desc = change.get("description", "")

        if not old:
            skipped.append(f"Empty 'old' field — skipped: {desc}")
            continue

        count = updated_html.count(old)
        if count == 1:
            updated_html = updated_html.replace(old, new, 1)
            applied.append(desc)
            print(f"  ✓  {desc}")
        elif count == 0:
            skipped.append(f"Not found in HTML: {old[:70]}…")
            print(f"  ✗  Not found: {old[:70]}…")
        else:
            # Ambiguous match — apply only first occurrence and warn
            updated_html = updated_html.replace(old, new, 1)
            applied.append(f"{desc}  *(first of {count} occurrences)*")
            print(f"  ⚠  Ambiguous ({count} matches), applied first: {desc}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(updated_html)

    # Build PR description
    applied_md = "\n".join(f"- {d}" for d in applied) or "_None_"
    skipped_section = ""
    if skipped:
        skipped_md = "\n".join(f"- {s}" for s in skipped)
        skipped_section = f"\n### ⚠️ Skipped ({len(skipped)})\n{skipped_md}\n"

    pr_body = f"""## 🔄 LinkedIn → Portfolio Sync

Claude analysed your LinkedIn updates and proposed the following changes to `index.html`:

### ✅ Applied ({len(applied)})
{applied_md}
{skipped_section}
---
**Review the diff in the Files Changed tab before merging.**
Changes go live on GitHub Pages automatically once you merge.
Close this PR (without merging) to reject the changes.
"""

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(pr_body)

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
