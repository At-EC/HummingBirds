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

    def unfinished_records(self, executor_records: list[dict]) -> list[dict]:
        """Remove only legacy records proven terminal by the main recovery snapshot."""
        executors_by_id = {
            executor.get("executor_id"): executor for executor in executor_records
        }
        unresolved = []
        if not self.path.parent.exists():
            return unresolved
        for path in sorted(self.path.parent.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("record must be an object")
            except (OSError, json.JSONDecodeError, ValueError):
                unresolved.append({"path": str(path), "error": "unreadable recovery record"})
                continue
            executor = executors_by_id.get(record.get("executor_id"))
            loss_exit = (executor or {}).get("loss_exit", {})
            active_statuses = {"OPEN", "PARTIALLY_FILLED"}
            exit_orders = [
                (executor or {}).get("take_profit_order"),
                *(executor or {}).get("loss_exit_orders", []),
            ]
            has_open_exit = any(
                order is not None and order.get("status") in active_statuses
                for order in exit_orders
            )
            resolved = (
                executor is not None
                and record.get("active_order_id") is None
                and not record.get("reconciliation_required", False)
                and loss_exit.get("state") in {"COMPLETED", "TERMINATED"}
                and not loss_exit.get("lock_held", False)
                and not loss_exit.get("reconciliation_required", False)
                and not has_open_exit
            )
            if resolved:
                path.unlink(missing_ok=True)
            else:
                unresolved.append(record)
        return unresolved

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
