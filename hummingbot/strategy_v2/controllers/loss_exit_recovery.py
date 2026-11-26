import json
from pathlib import Path
from typing import Optional
from uuid import uuid4


class LossExitRecoveryStore:
    def __init__(self, controller_id: str, root: Path = Path("data/pmm_mister_loss_exit"),
                 run_id: Optional[str] = None):
        self.run_id = run_id or uuid4().hex
        self.path = root / controller_id / f"{self.run_id}.json"

    def has_records(self) -> bool:
        return self.path.parent.exists() and any(self.path.parent.glob("*.json"))

    def load(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Loss exit recovery record must be a JSON object: {self.path}")
        return payload

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
