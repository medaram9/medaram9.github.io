#!/usr/bin/env python3
import os
import re
import json
import sys
from openai import OpenAI


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def slim_html(html: str) -> str:
    """Remove style/script blocks to reduce token count. Keep all visible text."""
    html = re.sub(r"<style[^>]*>.*?</style>", "<style>/* stripped */</style>", html, flags=re.DOTALL)
    html = re.sub(r"<script[^>]*>.*?</script>", "<script>/* stripped */</script>", html, flags=re.DOTALL)
    # Collapse runs of blank lines
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists("linkedin-profile.md"):
        print("ERROR: linkedin-profile.md not found.", file=sys.stderr)
        sys.exit(1)

    with open("linkedin-profile.md", "r", encoding="utf-8") as f:
        linkedin_content = f.read()
    with open("index.html", "r", encoding="utf-8") as f:
        current_html = f.read()

    slimmed = slim_html(current_html)
    print(f"linkedin-profile.md loaded.")
    print(f"index.html loaded ({len(current_html)} chars → {len(slimmed)} chars after stripping style/script).")
    print("\nCalling GitHub Models (gpt-4o)...")

    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a portfolio website sync assistant. "
                    "Make index.html consistent with the LinkedIn profile source-of-truth. "
                    "Return ONLY a raw JSON array of find-and-replace changes. "
                    "No markdown fences, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "## LinkedIn profile (source of truth)\n\n"
                    f"{linkedin_content}\n\n"
                    "## Current index.html (style/script blocks stripped to save tokens — "
                    "your 'old' strings must still be exact matches from the FULL file)\n\n"
                    f"```html\n{slimmed}\n```\n\n"
                    'Return a JSON array: [{"old": "exact string in full html", "new": "replacement", "description": "summary"}]\n\n'
                    "Rules:\n"
                    "- Only include changes where LinkedIn explicitly states a different value.\n"
                    "- Do not invent changes.\n"
                    "- Each 'old' must appear exactly once in the full index.html.\n"
                    "- Return ONLY the JSON array."
                ),
            },
        ],
    )

    raw = strip_code_fences(response.choices[0].message.content)

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Model returned invalid JSON — {exc}", file=sys.stderr)
        print("Raw response:\n", raw[:800], file=sys.stderr)
        sys.exit(1)

    print(f"\nModel proposed {len(changes)} change(s). Applying...\n")

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
            print(f"  OK  {desc}")
        elif count == 0:
            skipped.append(f"Not found: {old[:70]}")
            print(f"  --  Not found: {old[:70]}")
        else:
            updated_html = updated_html.replace(old, new, 1)
            applied.append(f"{desc} (first of {count})")
            print(f"  !!  Ambiguous ({count} matches), applied first: {desc}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(updated_html)

    applied_md = "\n".join(f"- {d}" for d in applied) or "_None_"
    skipped_section = ""
    if skipped:
        skipped_md = "\n".join(f"- {s}" for s in skipped)
        skipped_section = f"\n### Skipped ({len(skipped)})\n{skipped_md}\n"

    pr_body = (
        "## LinkedIn Portfolio Sync\n\n"
        "AI compared `linkedin-profile.md` against `index.html`:\n\n"
        f"### Applied ({len(applied)})\n{applied_md}\n"
        f"{skipped_section}"
        "\n---\n"
        "Review the diff in Files Changed. Merge to publish, close to reject.\n"
    )

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(pr_body)

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
