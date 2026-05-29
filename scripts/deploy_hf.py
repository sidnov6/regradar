"""Deploy RegRadar to a Hugging Face Docker Space.

    HF_TOKEN=hf_xxx python scripts/deploy_hf.py [--space-name regradar] [--source eurlex|fixture]

Creates (or updates) the Space, sets the LLM keys as Space secrets (fallback only —
the cached extractions mean the demo runs instantly without spending quota), uploads
the repo + the LLM response cache, and triggers a Docker build. Never uploads .env.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

from dotenv import load_dotenv
from huggingface_hub import HfApi

load_dotenv()

SPACE_README = """---
title: RegRadar · KOMPASS
emoji: 🛰️
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: true
short_description: Agentic EU reg-compliance engine · verified citations
---

# RegRadar · KOMPASS

Agentic EU regulatory-impact engine. Watches EU financial regulation (DORA, …),
extracts the concrete obligations, **programmatically verifies every citation**
against the source, maps them to a bank's controls (surfacing gaps), prioritizes by
deadline/risk, and drafts the gap-assessment memo (EN/DE) — all behind a dark
"command center" console. Source: https://github.com/sidnov6/regradar
"""

IGNORE = [
    ".git*", ".venv/*", "**/__pycache__/*", "*.pyc", ".env", ".env.*",
    "**/bronze/store/*", "**/silver/store/*", "**/gold/store/*",
    "**/seen_celex.json", "README.md",  # README replaced by the Space front-matter one
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space-name", default="regradar")
    ap.add_argument("--source", default="eurlex", choices=["eurlex", "fixture"])
    ap.add_argument("--max-articles", default="0")
    args = ap.parse_args()

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("ERROR: set HF_TOKEN (a write token from huggingface.co/settings/tokens)")
        return 1

    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{args.space_name}"
    print(f"deploying to Space: {repo_id}")

    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker", exist_ok=True)

    # Secrets (fallback for cache misses) + runtime config. Secrets are not visible
    # to Space visitors; only the container sees them.
    for key in ("GROQ_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "CEREBRAS_API_KEY"):
        val = os.getenv(key)
        if val:
            api.add_space_secret(repo_id=repo_id, key=key, value=val)
            print(f"  set secret {key}")
    api.add_space_variable(repo_id=repo_id, key="REGRADAR_SOURCE", value=args.source)
    api.add_space_variable(repo_id=repo_id, key="REGRADAR_MAX_ARTICLES", value=args.max_articles)
    # Pin the port so the container and HF's app_port (7860) cannot mismatch.
    api.add_space_variable(repo_id=repo_id, key="PORT", value="7860")

    # Space-specific README (with the required HF front matter).
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(SPACE_README)
        readme_path = f.name
    api.upload_file(path_or_fileobj=readme_path, path_in_repo="README.md",
                    repo_id=repo_id, repo_type="space")

    # Upload the project + the LLM cache (so extractions are cache-served instantly).
    api.upload_folder(folder_path=".", repo_id=repo_id, repo_type="space",
                      ignore_patterns=IGNORE,
                      commit_message="Deploy RegRadar console (Docker Space)")

    url = f"https://huggingface.co/spaces/{repo_id}"
    print(f"\n✅ deployed. building now → {url}")
    print(f"   live app (after build): https://{user}-{args.space_name}.hf.space")
    return 0


if __name__ == "__main__":
    sys.exit(main())
