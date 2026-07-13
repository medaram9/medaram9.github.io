#!/usr/bin/env python3
"""
LinkedIn → Portfolio sync via git diff.
Only looks at what changed in linkedin-profile.md and applies the same changes to index.html.
Small diff = tiny token count, no more 8k limit issues.
"""
import os
import re
import json
import sys
import subprocess
from openai import OpenAI


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def get_diff() -> str:
    """Get what changed in linkedin-profile.md in the most recent commit."""
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD", "--", "linkedin-profile.md"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def extract_cert_section(html: str) -> str:
    """Pull just the certifications section from the HTML for context."""
    m = re.search(
        r'<!-- ={5} Certifications ={5} -->.*?</section>',
        html, re.DOTALL
    )
    return m.group(0) if m else ""


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    diff = get_diff()
    if not diff:
        print("No changes detected in linkedin-profile.md — nothing to do.")
        # Write empty PR description so later steps don't fail
        with open("/tmp/pr_description.md", "w") as f:
            f.write("No changes detected.\n")
        sys.exit(0)

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    cert_section = extract_cert_section(html)
    print(f"Diff size: {len(diff)} chars. Calling GitHub Models...")

    client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=2048,
        messages=[
            {
                "role": "system",
                "content": (
                    "You sync a portfolio website with LinkedIn profile changes. "
                    "You receive a git diff of what changed in linkedin-profile.md "
                    "and the relevant HTML section(s). "
                    "Return ONLY a raw JSON array of surgical find-and-replace edits "
                    "to apply to index.html. No markdown, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "## What changed in linkedin-profile.md (git diff)\n\n"
                    f"```diff\n{diff}\n```\n\n"
                    "## Relevant HTML section(s) from index.html\n\n"
                    f"```html\n{cert_section}\n```\n\n"
                    "Return a JSON array of changes to apply to index.html:\n"
                    '[{"old": "exact string in index.html", "new": "replacement", "description": "what"}]\n\n'
                    "Rules:\n"
                    "- Only make changes that directly correspond to the diff above.\n"
                    "- 'old' must appear verbatim in the HTML shown above.\n"
                    "- For a new cert: insert a new badge line adjacent to an existing one "
                    "in the same group.\n"
                    "- Return ONLY the JSON array."
                ),
            },
        ],
    )

    raw = strip_code_fences(response.choices[0].message.content)

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON from model — {exc}", file=sys.stderr)
        print("Response was:\n", raw[:600], file=sys.stderr)
        sys.exit(1)

    if not isinstance(changes, list):
        print("ERROR: Expected a JSON array.", file=sys.stderr)
        sys.exit(1)

    print(f"Model proposed {len(changes)} change(s). Applying...\n")

    updated = html
    applied, skipped = [], []

    for change in changes:
        old  = change.get("old", "")
        new  = change.get("new", "")
        desc = change.get("description", "")

        if not old:
            skipped.append(f"Empty 'old' — {desc}")
            continue

        count = updated.count(old)
        if count == 1:
            updated = updated.replace(old, new, 1)
            applied.append(desc)
            print(f"  OK  {desc}")
        elif count == 0:
            skipped.append(f"Not found: {old[:70]}")
            print(f"  --  Not found: {old[:70]}")
        else:
            updated = updated.replace(old, new, 1)
            applied.append(f"{desc} (first of {count})")
            print(f"  !!  Ambiguous ({count}), applied first: {desc}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(updated)

    applied_md = "\n".join(f"- {d}" for d in applied) or "_None_"
    skipped_section = ""
    if skipped:
        skipped_section = "\n### Skipped\n" + "\n".join(f"- {s}" for s in skipped) + "\n"

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(
            "## LinkedIn Portfolio Sync\n\n"
            "Changes detected in `linkedin-profile.md` and applied to `index.html`:\n\n"
            f"### Applied ({len(applied)})\n{applied_md}\n"
            f"{skipped_section}"
            "\n---\nReview diff → merge to publish, close to reject.\n"
        )

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
