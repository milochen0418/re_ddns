#!/usr/bin/env python3
"""Downloads the ACE-Step weights of one size into the engine's ``checkpoints`` folder.

    python download_weights.py small|standard <checkpoints dir>

Run with the engine's own Python (it has huggingface_hub). Only the parts the size needs come
down; a part already here whole is skipped, and an interrupted download goes on where it stopped.
The weights are MIT-licensed by ACE-Step (https://huggingface.co/ACE-Step/Ace-Step1.5).
"""

import sys
from pathlib import Path

from huggingface_hub import snapshot_download

UNIFIED = ("ACE-Step/Ace-Step1.5", "19671f406d603126926c1b7e2adc169acbcade22")
SMALL_LM = ("ACE-Step/acestep-5Hz-lm-0.6B", None)
SHARED = ["acestep-v15-turbo", "vae", "Qwen3-Embedding-0.6B"]
PLANS = {
    "standard": [(UNIFIED, SHARED + ["acestep-5Hz-lm-1.7B"], "")],
    "small": [(UNIFIED, SHARED, ""), (SMALL_LM, None, "acestep-5Hz-lm-0.6B")],
}


def whole(root: Path, part: str) -> bool:
    folder = root / part
    if not folder.is_dir() or not any(folder.glob("*.json")) or not any(f.is_file() and f.stat().st_size > 100_000_000 for f in folder.rglob("*")):
        return False
    pending = root / ".cache" / "huggingface" / "download" / part
    return not (pending.is_dir() and any(pending.rglob("*.incomplete")))


def main() -> None:
    tier, root = sys.argv[1], Path(sys.argv[2])
    root.mkdir(parents=True, exist_ok=True)
    for (repo, revision), parts, into in PLANS[tier]:
        if parts is not None:
            parts = [p for p in parts if not whole(root, p)]
            if not parts:
                continue
            print(f"[weights] {repo}: {', '.join(parts)}", flush=True)
            snapshot_download(repo_id=repo, revision=revision, local_dir=str(root), allow_patterns=[f"{p}/*" for p in parts], max_workers=8)
        else:
            if whole(root, into):
                continue
            print(f"[weights] {repo} -> {into}", flush=True)
            snapshot_download(repo_id=repo, revision=revision, local_dir=str(root / into), max_workers=8)
    print("[weights] done", flush=True)


if __name__ == "__main__":
    main()
