"""Stage 3 · Arabic normalization for search (FR-ING-08, T-08).

Applied to the text that is embedded and searched, never to the text shown to users.
The basic set below is required by the corpus (Arabic-Indic digits, presentation forms);
extra unification (alef, yaa, taa marbuta) showed no gain in Phase 3 and is not applied.
"""

from __future__ import annotations

import re
import unicodedata

from rag_app.ingestion.cleaning import BIDI_CONTROLS

_TASHKEEL = re.compile("[ً-ٰٟ]")
_TATWEEL = "ـ"
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SPACES = re.compile(r"\s+")


def normalize_arabic(text: str) -> str:
    """NFKC (folds presentation forms), drop bidi controls, tashkeel and tatweel, unify digits."""
    text = unicodedata.normalize("NFKC", text).translate(BIDI_CONTROLS)
    text = _TASHKEEL.sub("", text).replace(_TATWEEL, "")
    text = text.translate(_DIGITS)
    return _SPACES.sub(" ", text).strip()
