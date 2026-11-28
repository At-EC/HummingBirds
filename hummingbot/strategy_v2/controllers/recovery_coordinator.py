from hummingbot.strategy_v2.controllers.executor_recovery import ExecutorRecoveryStore


class RecoveryCoordinator:
    def __init__(self, store: ExecutorRecoveryStore, adapter_factory, restorer):
        self.store = store
        self.adapter_factory = adapter_factory
        self.restorer = restorer
        self.state = "PENDING"
        self.recovered = None
        self._diagnostics = {}

    @staticmethod
    def _order_ids(record: dict) -> list[str]:
        order_ids = []
        for field in ("open_order", "take_profit_order", "close_order"):
            order = record.get(field)
            if order is not None:
                order_ids.append(order["client_order_id"])
        order_ids.extend(
            order["client_order_id"] for order in record.get("loss_exit_orders", [])
        )
        return list(dict.fromkeys(order_ids))

    async def load_snapshots(self) -> dict | None:
        self.state = "RECONCILING"
        payload = self.store.load()
        if payload is None:
            self.state = "READY"
            self.recovered = None
            return None
        adapter = self.adapter_factory()
        snapshots_by_executor = {}
        for record in payload["executors"]:
            snapshots = {}
            for order_id in self._order_ids(record):
                snapshots[order_id] = await adapter.fetch_order_snapshot(order_id)
            snapshots_by_executor[record["executor_id"]] = snapshots
        if hasattr(adapter, "fetch_open_order_ids"):
            expected_order_ids = {
                order_id
                for record in payload["executors"]
                for order_id in self._order_ids(record)
            }
            exchange_order_ids = await adapter.fetch_open_order_ids()
            unexpected = set(exchange_order_ids) - expected_order_ids
            if unexpected:
                raise ValueError(f"Untracked exchange orders: {sorted(unexpected)}")
        self.recovered = {
            "payload": payload,
            "snapshots": snapshots_by_executor,
        }
        return self.recovered

    async def reconcile(self, executors: list) -> None:
        try:
            recovered = await self.load_snapshots()
            if recovered is None:
                return
            executors_by_id = {
                executor.config.id: executor for executor in executors
            }
            for record in recovered["payload"]["executors"]:
                executor_id = record["executor_id"]
                if executor_id not in executors_by_id:
                    raise ValueError(f"Executor is not available for recovery: {executor_id}")
                self.restorer.restore(
                    executors_by_id[executor_id],
                    record,
                    recovered["snapshots"][executor_id],
                )
            self.state = "READY"
        except Exception as error:
            self.state = "BLOCKED"
            self._diagnostics = {"error": str(error)}

    def diagnostics(self) -> dict:
        return {
            "state": self.state,
            **self._diagnostics,
        }
