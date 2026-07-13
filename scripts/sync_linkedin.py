#!/usr/bin/env python3
"""
LinkedIn -> Portfolio sync via GitHub Models (gpt-4o-mini).
Sends only a compact site snapshot (~2k tokens) instead of full HTML.
Model returns old/new pairs that are exact HTML strings — no search mismatches.
"""
import os
import re
import json
import sys
from openai import OpenAI

CERT_BADGE_TPL = '          <span class="cert-badge"><span class="cert-dot"></span>{name}</span>'


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def extract_snapshot(html: str) -> str:
    """
    Pull exact strings from known HTML elements into a compact block.
    Every string returned here appears verbatim in the HTML file,
    so the model can safely use them as 'old' values.
    """
    lines = ["## Current site — exact strings from index.html\n"]

    # Headline
    m = re.search(r'<div class="hero-eyebrow">(.*?)</div>', html)
    if m:
        lines.append(f"HEADLINE: {m.group(1)}")

    # Hero chips
    chips = re.findall(r'<span class="hero-chip[^"]*">(.*?)</span>', html)
    for c in chips:
        lines.append(f"CHIP: {c}")

    # About paragraphs (first 3 — exact HTML content)
    about_m = re.search(r'<section id="about"[^>]*>(.*?)</section>', html, re.DOTALL)
    if about_m:
        paras = re.findall(r'<p[^>]*class="about-text[^"]*"[^>]*>(.*?)</p>',
                           about_m.group(1), re.DOTALL)
        for i, p in enumerate(paras[:3]):
            lines.append(f"ABOUT_P{i+1}: {p.strip()}")

    # Experience section highlights
    exp_m = re.search(r'<section id="experience"[^>]*>(.*?)</section>', html, re.DOTALL)
    if exp_m:
        bullets = re.findall(r'<li>(.*?)</li>', exp_m.group(1), re.DOTALL)
        for b in bullets[:4]:
            lines.append(f"EXP_BULLET: {b.strip()}")

    # Cert badges (exact text from each badge)
    cert_badges = re.findall(
        r'<span class="cert-badge[^"]*"><span class="cert-dot"></span>(.*?)</span>', html)
    for c in cert_badges:
        lines.append(f"CERT: {c}")

    # Project titles
    titles = re.findall(r'<h3 class="project-title">(.*?)</h3>', html)
    for t in titles:
        lines.append(f"PROJECT_TITLE: {t}")

    # Metric values + labels
    metrics = re.findall(
        r'<span class="metric-value"[^>]*>(.*?)</span>\s*<span class="metric-label">(.*?)</span>',
        html, re.DOTALL)
    for val, label in metrics:
        lines.append(f"METRIC: {val.strip()} — {label.strip()}")

    # Footer mission
    footer_m = re.search(r'<p class="footer-mission">(.*?)</p>', html)
    if footer_m:
        lines.append(f"FOOTER: {footer_m.group(1)}")

    return "\n".join(lines)


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists("linkedin-profile.md"):
        print("ERROR: linkedin-profile.md not found.", file=sys.stderr)
        sys.exit(1)

    with open("linkedin-profile.md", "r", encoding="utf-8") as f:
        linkedin = f.read()
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    snapshot = extract_snapshot(html)
    print(f"Snapshot: {len(snapshot)} chars (vs {len(html)} full HTML).")
    print("Calling GitHub Models (gpt-4o-mini)...")

    client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=2048,
        messages=[
            {
                "role": "system",
                "content": (
                    "You sync a portfolio website with a LinkedIn profile. "
                    "The site snapshot contains EXACT strings from the HTML file — "
                    "use them verbatim as 'old' values. "
                    "Return ONLY a raw JSON array, no markdown, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## LinkedIn profile (source of truth)\n\n{linkedin}\n\n"
                    f"{snapshot}\n\n"
                    "Compare. Return JSON array of changes needed:\n"
                    '[{"old": "exact string from snapshot", "new": "corrected value", '
                    '"description": "what changed"}]\n\n'
                    "Rules:\n"
                    "- 'old' must be copied EXACTLY as it appears after the label "
                    "(e.g. after 'CERT: ', 'CHIP: ', 'HEADLINE: ' etc).\n"
                    "- Only include changes explicitly supported by LinkedIn data.\n"
                    "- To ADD a new cert, use old='' and new='cert name to add|Group Label' "
                    "(Group Label: 'Cloud &amp; AI', 'Automation &amp; IaC', "
                    "'Security', or 'Networking').\n"
                    "- Return ONLY the JSON array."
                ),
            },
        ],
    )

    raw = strip_code_fences(response.choices[0].message.content)
    print(f"\nModel raw response ({len(raw)} chars):\n{raw[:400]}\n")

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON — {exc}", file=sys.stderr)
        print("Full response:\n", raw, file=sys.stderr)
        sys.exit(1)

    if not isinstance(changes, list):
        print("ERROR: Expected a JSON array.", file=sys.stderr)
        sys.exit(1)

    print(f"Model proposed {len(changes)} change(s). Applying...\n")

    updated = html
    applied: list[str] = []
    skipped: list[str] = []

    for change in changes:
        old  = change.get("old", "")
        new  = change.get("new", "")
        desc = change.get("description", "")

        # ADD CERT special case: old is empty, new is "cert name|Group Label"
        # Strip snapshot label prefixes the model sometimes includes
        for prefix in ("CERT: ", "CHIP: ", "HEADLINE: ", "PROJECT_TITLE: ",
                       "METRIC: ", "FOOTER: ", "ABOUT_P1: ", "ABOUT_P2: ",
                       "ABOUT_P3: ", "EXP_BULLET: "):
            if old.startswith(prefix):
                old = old[len(prefix):]
                break

        if not old and "|" in new:
            cert_name, group_label = [x.strip() for x in new.split("|", 1)]
            pattern = (
                rf'(<div class="cert-group-label">{re.escape(group_label)}</div>\s*'
                rf'<div class="cert-badges">)(.*?)(</div>\s*</div>)'
            )
            m = re.search(pattern, updated, re.DOTALL)
            if m:
                badge = "\n" + CERT_BADGE_TPL.format(name=cert_name)
                updated = updated[:m.end(2)] + badge + updated[m.end(2):]
                applied.append(f"Added cert: {cert_name}")
                print(f"  OK  Added cert: {cert_name} → {group_label}")
            else:
                skipped.append(f"Cert group not found: {group_label}")
                print(f"  --  Cert group not found: {group_label}")
            continue

        if not old:
            skipped.append(f"Empty 'old' — {desc}")
            continue

        count = updated.count(old)
        if count == 1:
            updated = updated.replace(old, new, 1)
            applied.append(desc)
            print(f"  OK  {desc}")
        elif count == 0:
            skipped.append(f"Not found: {old[:60]}")
            print(f"  --  Not found: {old[:60]}")
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
            f"### Applied ({len(applied)})\n{applied_md}\n"
            f"{skipped_section}"
            "\n---\nReview diff → merge to publish, close to reject.\n"
        )

    print(f"\nDone — {len(applied)} applied, {len(skipped)} skipped.")


if __name__ == "__main__":
    main()
