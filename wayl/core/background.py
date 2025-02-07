from typing import Any, Callable, Dict, Optional
import asyncio
import logging
from datetime import datetime
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

background_tasks = Counter('background_tasks_total', 'Total background tasks', ['status'])
task_duration = Histogram('background_task_duration_seconds', 'Background task duration')


class BackgroundTaskManager:
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._errors: Dict[str, Exception] = {}
        self._callbacks: Dict[str, Callable] = {}

    async def add_task(
            self,
            task_id: str,
            coroutine: Callable,
            *args,
            callback: Optional[Callable] = None,
            **kwargs
    ) -> str:
        async def wrapped_task():
            try:
                with task_duration.time():
                    start_time = datetime.utcnow()
                    result = await coroutine(*args, **kwargs)
                    self._results[task_id] = result
                    background_tasks.labels(status='success').inc()

                    if callback:
                        await callback(result)

                    duration = (datetime.utcnow() - start_time).total_seconds()
                    logger.info(f"Task {task_id} completed in {duration:.2f}s")

            except Exception as e:
                background_tasks.labels(status='error').inc()
                self._errors[task_id] = e
                logger.error(f"Task {task_id} failed: {str(e)}")
            finally:
                self._tasks.pop(task_id, None)

        self._tasks[task_id] = asyncio.create_task(wrapped_task())
        return task_id

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        task = self._tasks.get(task_id)
        if not task:
            if task_id in self._results:
                return {
                    "status": "completed",
                    "result": self._results[task_id]
                }
            elif task_id in self._errors:
                return {
                    "status": "failed",
                    "error": str(self._errors[task_id])
                }
            return {"status": "not_found"}

        return {
            "status": "running",
            "done": task.done(),
            "cancelled": task.cancelled()
        }

    async def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            background_tasks.labels(status='cancelled').inc()
            return True
        return False

    async def cleanup_old_tasks(self, age_hours: int = 24):
        current_time = datetime.utcnow()
        for task_id in list(self._results.keys()):
            if (current_time - self._results[task_id].get('timestamp',
                                                          current_time)).total_seconds() > age_hours * 3600:
                del self._results[task_id]

        for task_id in list(self._errors.keys()):
            if (current_time - self._errors[task_id].get('timestamp', current_time)).total_seconds() > age_hours * 3600:
                del self._errors[task_id]