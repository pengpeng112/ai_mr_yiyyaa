"""
线程安全的任务进度管理器 —— 替代全局字典，解决并发安全问题
"""
import threading
import time
from typing import Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class TaskProgress:
    """任务进度数据类"""
    task_id: str
    status: str  # running | completed | failed | not_found | cancelled
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total": self.total,
            "processed": self.processed,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "cancelled": self.cancelled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskProgressManager:
    """
    线程安全的任务进度管理器

    使用锁机制确保多线程环境下的数据一致性，
    替代原来 push.py 中的全局字典 _task_progress
    """

    def __init__(self, max_tasks: int = 100):
        """
        初始化任务进度管理器

        Args:
            max_tasks: 最大任务数量，超过后清理最旧的任务
        """
        self._progress: Dict[str, TaskProgress] = {}
        self._lock = threading.RLock()  # 可重入锁
        self._max_tasks = max_tasks

        # 启动清理线程
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_old_tasks,
            daemon=True
        )
        self._cleanup_thread.start()

    def create_task(self, task_id: str) -> TaskProgress:
        """
        创建新任务

        Args:
            task_id: 任务ID

        Returns:
            任务进度对象
        """
        with self._lock:
            if task_id in self._progress:
                logger.warning(f"任务ID {task_id} 已存在，将覆盖")

            progress = TaskProgress(
                task_id=task_id,
                status="running"
            )
            self._progress[task_id] = progress

            # 检查任务数量，必要时清理旧任务
            if len(self._progress) > self._max_tasks:
                self._cleanup_old_tasks_locked()

            return progress

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        processed: Optional[int] = None,
        success: Optional[int] = None,
        failed: Optional[int] = None,
        skipped: Optional[int] = None,
        total: Optional[int] = None
    ) -> bool:
        """
        更新任务进度

        Args:
            task_id: 任务ID
            status: 状态更新
            processed: 已处理数量
            success: 成功数量
            failed: 失败数量
            total: 总数量

        Returns:
            是否更新成功
        """
        with self._lock:
            progress = self._progress.get(task_id)
            if not progress:
                return False

            if status is not None:
                progress.status = status
            if total is not None:
                progress.total = total
            if processed is not None:
                progress.processed = processed
            if success is not None:
                progress.success = success
            if failed is not None:
                progress.failed = failed
            if skipped is not None:
                progress.skipped = skipped

            progress.updated_at = time.time()
            return True

    def increment_processed(
        self,
        task_id: str,
        result_status: str = "failed"
    ) -> bool:
        """
        增加已处理计数

        Args:
            task_id: 任务ID
            success: 是否成功

        Returns:
            是否更新成功
        """
        with self._lock:
            progress = self._progress.get(task_id)
            if not progress:
                return False

            progress.processed += 1
            if result_status == "success":
                progress.success += 1
            elif result_status == "skipped":
                progress.skipped += 1
            else:
                progress.failed += 1

            progress.updated_at = time.time()
            return True

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        """
        获取任务进度

        Args:
            task_id: 任务ID

        Returns:
            任务进度对象，不存在返回None
        """
        with self._lock:
            progress = self._progress.get(task_id)
            if progress:
                # 返回副本，避免外部修改影响内部数据
                return TaskProgress(
                    task_id=progress.task_id,
                    status=progress.status,
                    total=progress.total,
                    processed=progress.processed,
                    success=progress.success,
                    failed=progress.failed,
                    skipped=progress.skipped,
                    cancelled=progress.cancelled,
                    created_at=progress.created_at,
                    updated_at=progress.updated_at,
                )
            return None

    def remove_task(self, task_id: str) -> bool:
        """
        移除任务

        Args:
            task_id: 任务ID

        Returns:
            是否移除成功
        """
        with self._lock:
            if task_id in self._progress:
                del self._progress[task_id]
                return True
            return False

    def list_tasks(self, status_filter: Optional[str] = None) -> list[TaskProgress]:
        """
        列出所有任务

        Args:
            status_filter: 可选的状态过滤器

        Returns:
            任务进度列表
        """
        with self._lock:
            tasks = list(self._progress.values())

            if status_filter:
                tasks = [t for t in tasks if t.status == status_filter]

            # 返回副本列表
            return [
                TaskProgress(
                    task_id=t.task_id,
                    status=t.status,
                    total=t.total,
                    processed=t.processed,
                    success=t.success,
                    failed=t.failed,
                    skipped=t.skipped,
                    cancelled=t.cancelled,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                )
                for t in tasks
            ]

    def get_latest_task(self, status_filter: Optional[str] = None) -> Optional[TaskProgress]:
        """获取最近更新的任务，用于页面重新登录后恢复进度显示。"""
        tasks = self.list_tasks(status_filter=status_filter)
        if not tasks:
            return None
        return max(tasks, key=lambda item: item.updated_at)

    def get_statistics(self) -> Dict[str, any]:
        """
        获取任务统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            total_tasks = len(self._progress)
            status_counts = defaultdict(int)

            for progress in self._progress.values():
                status_counts[progress.status] += 1

            return {
                "total_tasks": total_tasks,
                "status_counts": dict(status_counts),
                "max_tasks": self._max_tasks,
            }

    def _cleanup_old_tasks(self):
        """后台清理线程 - 清理超过1小时的已完成任务"""
        while True:
            try:
                time.sleep(300)  # 每5分钟检查一次
                with self._lock:
                    self._cleanup_old_tasks_locked()
            except Exception as e:
                logger.error(f"任务清理线程异常: {e}")

    def _cleanup_old_tasks_locked(self):
        """清理旧任务（必须在持有锁的情况下调用）"""
        current_time = time.time()
        one_hour_ago = current_time - 3600  # 1小时前

        tasks_to_remove = [
            task_id
            for task_id, progress in self._progress.items()
            if (
                progress.status in ["completed", "failed", "not_found", "cancelled"]
                and progress.updated_at < one_hour_ago
            )
        ]

        for task_id in tasks_to_remove:
            del self._progress[task_id]

        if tasks_to_remove:
            logger.info(f"清理了 {len(tasks_to_remove)} 个旧任务")


    def cancel_task(self, task_id: str) -> bool:
        """
        取消正在运行的任务（设置 cancelled 标志和 status='cancelled'）

        Args:
            task_id: 任务ID

        Returns:
            是否成功标记取消
        """
        with self._lock:
            progress = self._progress.get(task_id)
            if not progress:
                return False
            if progress.status != "running":
                return False
            progress.cancelled = True
            progress.status = "cancelled"
            progress.updated_at = time.time()
            logger.info(f"任务 {task_id} 已标记为取消")
            return True

    def is_cancelled(self, task_id: str) -> bool:
        """
        检查任务是否被取消

        Args:
            task_id: 任务ID

        Returns:
            是否已取消
        """
        with self._lock:
            progress = self._progress.get(task_id)
            if not progress:
                return False
            return bool(progress.cancelled)


# 全局单例
_task_manager = TaskProgressManager()


def get_task_manager() -> TaskProgressManager:
    """获取全局任务进度管理器单例"""
    return _task_manager
