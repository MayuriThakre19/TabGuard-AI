"""
hazard_classifier.py
---------------------
TabGuard AI — Semantic Buffer Interceptor.

A lightweight, fully local keyword/regex classifier that scores an active
window title for privacy risk. No network calls, no external APIs — this
is the "brain" that decides whether a screen-share frame needs to be
intercepted.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class HazardMatch:
    matched: bool
    score: int                 # 0-100 severity of the worst trigger
    triggers: List[str] = field(default_factory=list)


class HazardClassifier:
    """
    Maps keywords/regex fragments -> severity score (0-100).
    classify() returns the highest severity match found in a window title.
    """

    DEFAULT_KEYWORDS: Dict[str, int] = {
        # Messaging / personal
        "whatsapp": 90,
        "telegram": 85,
        "signal": 85,
        "messenger": 75,
        "instagram dm": 70,
        # Browsing / privacy mode
        "incognito": 70,
        "private browsing": 70,
        # Finance / sensitive docs
        "salary": 95,
        "payroll": 95,
        "bank": 90,
        "invoice": 60,
        "tax": 80,
        "confidential": 90,
        "password": 95,
        "ssn": 95,
        "aadhaar": 95,
        "otp": 85,
        "credit card": 95,
        # Generic hazard folder/file naming
        "untitled folder": 40,
        "personal": 55,
        # Workplace chat
        "slack": 55,
        "gmail": 50,
        "outlook": 45,
    }

    def __init__(self, custom_keywords: Optional[Dict[str, int]] = None):
        self.keywords: Dict[str, int] = dict(self.DEFAULT_KEYWORDS)
        if custom_keywords:
            self.keywords.update(custom_keywords)
        self._patterns: Dict[str, "re.Pattern"] = {}
        self._compile()

    def _compile(self) -> None:
        self._patterns = {
            kw: re.compile(re.escape(kw), re.IGNORECASE) for kw in self.keywords
        }

    def add_keyword(self, keyword: str, score: int = 75) -> None:
        keyword = keyword.strip().lower()
        if not keyword:
            return
        score = max(0, min(100, score))
        self.keywords[keyword] = score
        self._patterns[keyword] = re.compile(re.escape(keyword), re.IGNORECASE)

    def remove_keyword(self, keyword: str) -> None:
        keyword = keyword.strip().lower()
        self.keywords.pop(keyword, None)
        self._patterns.pop(keyword, None)

    def classify(self, window_title: str) -> HazardMatch:
        if not window_title:
            return HazardMatch(matched=False, score=0, triggers=[])

        triggers: List[str] = []
        max_score = 0
        for kw, pattern in self._patterns.items():
            if pattern.search(window_title):
                triggers.append(kw)
                max_score = max(max_score, self.keywords[kw])

        return HazardMatch(matched=bool(triggers), score=max_score, triggers=triggers)
