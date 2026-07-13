#!/usr/bin/env python3
"""
LinkedIn → Portfolio sync script.

Reads LinkedIn changes from LINKEDIN_CHANGES_FILE (written by the GH Action),
calls Claude API to generate a targeted list of HTML edits, applies them to
index.html, and writes a PR description to /tmp/pr_description.md.

Handles two payload shapes:
  - Make.com JSON payload  (repository_dispatch)
  - Plain text             (workflow_dispatch manual input)
"""
import os
import json
import sys
import anthropic


def load_linkedin_changes(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    # Make.com sends a JSON payload — pretty-print it into readable text
    # so Claude can parse the field names and values easily.
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            lines = ["LinkedIn profile fields updated via Make.com:\n"]
            for key, value in data.items():
                if value and key not in ("triggered_by",):
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)
    except (json.JSONDecodeError, ValueError):
        pass  # Not JSON — treat as plain text (manual input)

    return raw


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
    changes_file = os.environ.get("LINKEDIN_CHANGES_FILE", "/tmp/linkedin_changes.txt")

    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY secret is not set.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(changes_file):
        print(f"ERROR: Changes file not found: {changes_file}", file=sys.stderr)
        sys.exit(1)

    linkedin_changes = load_linkedin_changes(changes_file)

    if not linkedin_changes.strip():
        print("ERROR: LinkedIn changes are empty.", file=sys.stderr)
        sys.exit(1)

    print("LinkedIn changes received:")
    print(linkedin_changes[:500])
    print("---")

    with open("index.html", "r", encoding="utf-8") as f:
        current_html = f.read()

    client = anthropic.Anthropic(api_key=api_key)

    print("\nCalling Claude API…")
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
                    f"LinkedIn profile updates to sync:\n{linkedin_changes}\n\n"
                    "Return a JSON array where each element is:\n"
                    '{\n'
                    '  "old": "exact string to find (must appear exactly once in the HTML)",\n'
                    '  "new": "replacement string",\n'
                    '  "description": "one-line summary"\n'
                    '}\n\n'
                    "Rules:\n"
                    "- Only include changes directly supported by the LinkedIn updates above.\n"
                    "- Do not invent or guess changes.\n"
                    "- Each 'old' string must be unique in the HTML file.\n"
                    "- Return ONLY the JSON array, nothing else."
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
            skipped.append(f"Empty 'old' field — {desc}")
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
    applied_md  = "\n".join(f"- {d}" for d in applied) or "_None_"
    skipped_section = ""
    if skipped:
        skipped_md = "\n".join(f"- {s}" for s in skipped)
        skipped_section = f"\n### ⚠️ Skipped ({len(skipped)})\n{skipped_md}\n"

    pr_body = f"""## 🔄 LinkedIn → Portfolio Sync

Claude analysed the LinkedIn updates and proposed the following changes to `index.html`:

### ✅ Applied ({len(applied)})
{applied_md}
{skipped_section}
---
**Review the diff in the Files Changed tab.**
Merge to publish · Close to reject — nothing goes live until you merge.
"""

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(pr_body)

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
