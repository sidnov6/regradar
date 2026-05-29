"""Bronze layer — raw regulatory docs, immutable, pinned by version hash (Part 6).

Bronze is never mutated. A record is addressed by (CELEX, manifestation, language,
content_hash). Re-ingesting identical bytes is a no-op (idempotency, Part 11.7),
which is what makes any past memo bit-for-bit re-derivable (Part 10).

The MVP store is the local filesystem; the interface is deliberately small so it
can be swapped for Supabase Storage / Cloudflare R2 later with no caller changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from regradar import config
from regradar.agents.state import Language, Manifestation, RawRegDoc


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class BronzeStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or config.BRONZE_STORE
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, celex: str, manifestation: Manifestation, language: Language, chash: str):
        stem = f"{celex}__{manifestation.value}__{language}__{chash[:12]}"
        safe = stem.replace("/", "_")
        return self.root / f"{safe}.bin", self.root / f"{safe}.meta.json"

    def put(
        self,
        *,
        celex: str,
        manifestation: Manifestation,
        language: Language,
        source_uri: str,
        raw: bytes,
        version_label: Optional[str] = None,
    ) -> RawRegDoc:
        """Pin raw bytes. Idempotent: identical bytes for the same key are a no-op
        and return the existing record."""
        chash = content_hash(raw)
        blob, meta = self._paths(celex, manifestation, language, chash)
        if meta.exists():  # already pinned -> no-op
            return RawRegDoc.model_validate_json(meta.read_text())

        blob.write_bytes(raw)
        rec = RawRegDoc(
            celex=celex,
            manifestation=manifestation,
            language=language,
            source_uri=source_uri,
            content_hash=chash,
            content_path=str(blob),
            version_label=version_label,
        )
        meta.write_text(rec.model_dump_json(indent=2))
        return rec

    def get_bytes(self, rec: RawRegDoc) -> bytes:
        return Path(rec.content_path).read_bytes()

    def exists(self, celex: str, manifestation: Manifestation, language: Language, chash: str) -> bool:
        _, meta = self._paths(celex, manifestation, language, chash)
        return meta.exists()

    def list_records(self) -> list[RawRegDoc]:
        out: list[RawRegDoc] = []
        for meta in sorted(self.root.glob("*.meta.json")):
            out.append(RawRegDoc.model_validate_json(meta.read_text()))
        return out
