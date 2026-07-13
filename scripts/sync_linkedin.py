#!/usr/bin/env python3
"""
LinkedIn → Portfolio sync (repaired).

Strategy:
  1. Cert changes → deterministic: parse linkedin-profile.md and inject/remove
     cert badges directly. No LLM, no label artifacts, always reliable.
  2. Other changes → LLM: send the raw git diff + the relevant HTML snippet.
     Strip any label artifacts from model output before writing.
"""
import os
import re
import json
import sys
import subprocess
import html as html_lib
from openai import OpenAI

# linkedin-profile.md cert section heading → HTML cert-group-label (HTML-encoded)
CERT_GROUP_MAP = {
    "AI & Cloud Leadership": "Cloud &amp; AI",
    "Automation & IaC":      "Automation &amp; IaC",
    "Security":               "Security",
    "Networking":             "Networking",
}

# Prefixes the LLM sometimes echoes back — strip from both old and new
LABEL_PREFIXES = (
    "HEADLINE: ", "CHIP: ", "CERT: ", "PROJECT_TITLE: ",
    "METRIC: ", "FOOTER: ", "ABOUT_P1: ", "ABOUT_P2: ", "ABOUT_P3: ",
    "EXP_BULLET: ",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def strip_label(s: str) -> str:
    for prefix in LABEL_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def is_safe_new_value(new: str) -> bool:
    """Reject values that look like raw JSON/label artifacts."""
    if any(new.startswith(p) for p in LABEL_PREFIXES):
        return False
    if "old=''" in new or 'old=""' in new:
        return False
    if new.startswith("old="):
        return False
    return True


def get_diff() -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD", "--", "linkedin-profile.md"],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


# ── Phase 1: Deterministic cert sync ──────────────────────────────────────────

def normalize_cert_name(raw: str) -> str:
    """Strip '(Provider · Year)' and convert '— ACRONYM' → '(ACRONYM)'."""
    name = re.sub(r"\s*\([^)]*·[^)]*\)", "", raw).strip()
    name = re.sub(r"\s*—\s*([A-Z0-9-]+)$", r" (\1)", name).strip()
    return name


def parse_md_certs(md: str) -> dict[str, list[str]]:
    """Return {md_group_heading: [normalized_cert_name, ...]}."""
    m = re.search(r"^## Certifications\s*\n(.*?)(?=^## |\Z)", md, re.MULTILINE | re.DOTALL)
    if not m:
        return {}
    cert_block = m.group(1)
    groups: dict[str, list[str]] = {}
    current = None
    for line in cert_block.splitlines():
        h = re.match(r"^###\s+(.+)", line)
        if h:
            current = h.group(1).strip()
            groups[current] = []
            continue
        item = re.match(r"^-\s+(.+)", line)
        if item and current is not None:
            groups[current].append(normalize_cert_name(item.group(1).strip()))
    return groups


def get_html_certs_in_group(html: str, html_group_label: str) -> list[str]:
    pattern = (
        rf'<div class="cert-group-label">{re.escape(html_group_label)}</div>'
        rf'\s*<div class="cert-badges">(.*?)</div>'
    )
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return []
    return re.findall(r'<span class="cert-dot"></span>(.*?)</span>', m.group(1))


def cert_in_html(html_certs: list[str], cert_name: str) -> bool:
    words = cert_name.lower().split()[:4]
    key = " ".join(words)
    return any(key in c.lower() for c in html_certs)


def inject_cert(html: str, html_group_label: str, cert_name: str) -> tuple[str, bool]:
    pattern = (
        rf'(<div class="cert-group-label">{re.escape(html_group_label)}</div>'
        rf'\s*<div class="cert-badges">)(.*?)(</div>)'
    )
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return html, False
    new_badge = f'\n          <span class="cert-badge"><span class="cert-dot"></span>{cert_name}</span>'
    updated = html[: m.end(2)] + new_badge + html[m.end(2) :]
    return updated, True


def sync_certs(html: str, md: str) -> tuple[str, list[str]]:
    md_groups = parse_md_certs(md)
    applied = []
    for md_group, certs in md_groups.items():
        html_label = CERT_GROUP_MAP.get(md_group)
        if not html_label:
            continue
        html_certs = get_html_certs_in_group(html, html_label)
        for cert in certs:
            if cert_in_html(html_certs, cert):
                print(f"  =   Already present: {cert}")
            else:
                html, ok = inject_cert(html, html_label, cert)
                if ok:
                    applied.append(f"Added cert: {cert}")
                    print(f"  OK  Added cert: {cert}")
                else:
                    print(f"  --  Cert group not found in HTML: {html_label}")
    return html, applied


# ── Phase 2: LLM for non-cert changes ─────────────────────────────────────────

def diff_has_non_cert_changes(diff: str) -> bool:
    in_cert = False
    for line in diff.splitlines():
        if re.match(r"^[+-]{3}", line):
            continue
        stripped = line.lstrip("+-@ ")
        if stripped.startswith("## Certifications"):
            in_cert = True
        elif stripped.startswith("## "):
            in_cert = False
        if line.startswith(("+", "-")) and not in_cert:
            return True
    return False


def relevant_html_snippet(html: str, diff: str) -> str:
    """Return the HTML sections most relevant to the non-cert diff changes."""
    sections = []
    if any(kw in diff for kw in ("Headline", "hero-eyebrow", "Current Role")):
        m = re.search(r'<section id="hero".*?</section>', html, re.DOTALL)
        if m:
            sections.append(("hero", m.group(0)[:3000]))
    if "## About" in diff:
        m = re.search(r'<section id="about".*?</section>', html, re.DOTALL)
        if m:
            sections.append(("about", m.group(0)[:3000]))
    if "## Featured Projects" in diff:
        m = re.search(r'<section id="projects".*?</section>', html, re.DOTALL)
        if m:
            sections.append(("projects", m.group(0)[:3000]))
    if not sections:
        # Generic: send first 4000 chars of body as fallback
        sections.append(("general", html[:4000]))
    return "\n\n".join(f"<!-- {name} section -->\n{content}" for name, content in sections)


def llm_sync(html: str, diff: str, token: str) -> tuple[str, list[str], list[str]]:
    snippet = relevant_html_snippet(html, diff)
    client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1024,
        messages=[
            {
                "role": "system",
                "content": (
                    "You sync a portfolio website with LinkedIn profile changes. "
                    "Return ONLY a raw JSON array of find-and-replace edits. "
                    "No markdown fences, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    "## What changed in linkedin-profile.md\n\n"
                    f"```diff\n{diff}\n```\n\n"
                    "## Relevant HTML from index.html\n\n"
                    f"```html\n{snippet}\n```\n\n"
                    'Return JSON: [{"old": "exact HTML string", "new": "replacement", "description": "what"}]\n\n'
                    "Rules:\n"
                    "- 'old' must appear verbatim in the HTML above.\n"
                    "- Only change what the diff explicitly updates.\n"
                    "- 'new' must be plain HTML — no labels, no JSON, no pipe separators.\n"
                    "- Return ONLY the JSON array."
                ),
            },
        ],
    )

    raw = strip_code_fences(response.choices[0].message.content)
    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"  ERROR: LLM returned invalid JSON — {exc}", file=sys.stderr)
        return html, [], [f"JSON parse error: {exc}"]

    applied, skipped = [], []
    for change in changes:
        old  = strip_label(change.get("old", "")).strip()
        new  = strip_label(change.get("new", "")).strip()
        desc = change.get("description", "")

        if not old:
            skipped.append(f"Empty 'old' — {desc}")
            continue
        if not is_safe_new_value(new):
            skipped.append(f"Unsafe 'new' value rejected: {new[:60]}")
            print(f"  !!  REJECTED unsafe new value: {new[:60]}")
            continue

        count = html.count(old)
        if count == 1:
            html = html.replace(old, new, 1)
            applied.append(desc)
            print(f"  OK  {desc}")
        elif count == 0:
            skipped.append(f"Not found: {old[:60]}")
            print(f"  --  Not found: {old[:60]}")
        else:
            html = html.replace(old, new, 1)
            applied.append(f"{desc} (first of {count})")
            print(f"  !!  Ambiguous ({count}), applied first: {desc}")

    return html, applied, skipped


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    diff = get_diff()
    if not diff:
        print("No changes in linkedin-profile.md — nothing to do.")
        with open("/tmp/pr_description.md", "w") as f:
            f.write("No changes detected.\n")
        sys.exit(0)

    with open("linkedin-profile.md", "r", encoding="utf-8") as f:
        md = f.read()
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    all_applied: list[str] = []
    all_skipped: list[str] = []

    # Phase 1: certs (deterministic)
    if "## Certifications" in diff:
        print("Phase 1: syncing certifications (deterministic)...")
        html, cert_applied = sync_certs(html, md)
        all_applied.extend(cert_applied)

    # Phase 2: other changes (LLM)
    if diff_has_non_cert_changes(diff):
        print("\nPhase 2: syncing other changes via LLM...")
        html, llm_applied, llm_skipped = llm_sync(html, diff, token)
        all_applied.extend(llm_applied)
        all_skipped.extend(llm_skipped)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    applied_md = "\n".join(f"- {d}" for d in all_applied) or "_None_"
    skipped_section = ""
    if all_skipped:
        skipped_section = "\n### Skipped\n" + "\n".join(f"- {s}" for s in all_skipped) + "\n"

    with open("/tmp/pr_description.md", "w", encoding="utf-8") as f:
        f.write(
            "## LinkedIn Portfolio Sync\n\n"
            f"### Applied ({len(all_applied)})\n{applied_md}\n"
            f"{skipped_section}"
            "\n---\nReview diff → merge to publish, close to reject.\n"
        )

    print(f"\nDone — {len(all_applied)} applied, {len(all_skipped)} skipped.")


if __name__ == "__main__":
    main()
