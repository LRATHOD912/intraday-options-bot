from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalysisResult:
    engine: str
    direction: str
    score: float
    max_score: float
    confidence: float
    signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "engine": self.engine,
            "direction": self.direction,
            "score": round(self.score, 2),
            "max_score": self.max_score,
            "confidence": round(self.confidence, 2),
            "signals": self.signals,
            "warnings": self.warnings,
            "data": self.data,
        }
