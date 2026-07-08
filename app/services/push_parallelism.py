"""Shared parallel worker calculation for push execution paths."""


def effective_parallel_workers(requested_workers: int, db_type: str) -> tuple[int, str]:
    workers = max(1, int(requested_workers or 1))
    if str(db_type or "").lower() == "sqlite":
        capped = min(workers, 4)
        if capped != workers:
            return capped, "sqlite mode: workers capped to 4 to reduce database lock contention"
    return workers, ""
