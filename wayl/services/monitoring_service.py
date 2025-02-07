from typing import Dict, List, Optional
import psutil
import torch
import logging
from prometheus_client import Gauge, Counter, Histogram
import asyncio
from datetime import datetime
import json
from redis import Redis
from sqlalchemy.orm import Session
from fastapi import Depends
from ..db.database import get_db

logger = logging.getLogger(__name__)

# System Metrics
cpu_usage = Gauge('system_cpu_usage_percent', 'CPU Usage Percentage')
memory_usage = Gauge('system_memory_usage_bytes', 'Memory Usage in Bytes')
gpu_memory_usage = Gauge('gpu_memory_usage_bytes', 'GPU Memory Usage in Bytes')
disk_usage = Gauge('system_disk_usage_bytes', 'Disk Usage in Bytes')
model_load_time = Histogram('model_load_duration_seconds', 'Time taken to load models')
active_users = Gauge('system_active_users', 'Number of Active Users')
request_latency = Histogram('request_latency_seconds', 'Request Latency')

class MonitoringService:
    def __init__(
        self,
        redis_client: Optional[Redis] = None,
        db: Session = Depends(get_db),
        metrics_interval: int = 60
    ):
        self.redis = redis_client
        self.db = db
        self.metrics_interval = metrics_interval
        self._monitoring_task: Optional[asyncio.Task] = None
        self._alert_thresholds = {
            'cpu_usage': 80.0,
            'memory_usage': 85.0,
            'gpu_memory': 90.0,
            'disk_usage': 85.0,
            'request_latency': 2.0
        }
        self._last_alert_time: Dict[str, datetime] = {}

    async def start_monitoring(self):
        if self._monitoring_task is None:
            self._monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("System monitoring started")

    async def stop_monitoring(self):
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            logger.info("System monitoring stopped")

    async def _monitoring_loop(self):
        while True:
            try:
                await self._collect_metrics()
                await self._check_alerts()
                await asyncio.sleep(self.metrics_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(5)

    async def _collect_metrics(self):
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        cpu_usage.set(cpu_percent)
        memory_usage.set(memory.used)
        disk_usage.set(disk.used)

        # GPU metrics if available
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                memory_allocated = torch.cuda.memory_allocated(i)
                gpu_memory_usage.labels(device=i).set(memory_allocated)

        # Cache metrics in Redis
        if self.redis:
            metrics_data = {
                'timestamp': datetime.utcnow().isoformat(),
                'cpu_usage': cpu_percent,
                'memory_usage': memory.percent,
                'disk_usage': disk.percent,
                'gpu_memory': gpu_memory_usage._value.get() if torch.cuda.is_available() else 0
            }
            await self.redis.setex(
                f'metrics:{datetime.utcnow().isoformat()}',
                3600,  # 1 hour retention
                json.dumps(metrics_data)
            )

    async def _check_alerts(self):
        current_time = datetime.utcnow()
        alert_cooldown = 300  # 5 minutes

        for metric, threshold in self._alert_thresholds.items():
            last_alert = self._last_alert_time.get(metric)
            if last_alert and (current_time - last_alert).total_seconds() < alert_cooldown:
                continue

            value = None
            if metric == 'cpu_usage':
                value = psutil.cpu_percent()
            elif metric == 'memory_usage':
                value = psutil.virtual_memory().percent
            elif metric == 'gpu_memory' and torch.cuda.is_available():
                value = (torch.cuda.memory_allocated() / torch.cuda.get_device_properties(0).total_memory) * 100
            elif metric == 'disk_usage':
                value = psutil.disk_usage('/').percent

            if value and value > threshold:
                await self._send_alert(metric, value, threshold)
                self._last_alert_time[metric] = current_time

    async def _send_alert(self, metric: str, value: float, threshold: float):
        alert_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'metric': metric,
            'value': value,
            'threshold': threshold,
            'severity': 'high' if value > threshold + 10 else 'medium'
        }

        logger.warning(f"System alert: {json.dumps(alert_data)}")

        if self.redis:
            await self.redis.lpush('system:alerts', json.dumps(alert_data))
            await self.redis.ltrim('system:alerts', 0, 999)  # Keep last 1000 alerts

    async def get_system_metrics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict]:
        if not self.redis:
            return []

        keys = await self.redis.keys('metrics:*')
        metrics = []

        for key in sorted(keys):
            data = json.loads(await self.redis.get(key))
            timestamp = datetime.fromisoformat(data['timestamp'])

            if start_time and timestamp < start_time:
                continue
            if end_time and timestamp > end_time:
                continue

            metrics.append(data)

        return metrics

    async def get_alerts(
        self,
        limit: int = 100,
        severity: Optional[str] = None
    ) -> List[Dict]:
        if not self.redis:
            return []

        alerts = []
        raw_alerts = await self.redis.lrange('system:alerts', 0, limit - 1)

        for alert in raw_alerts:
            alert_data = json.loads(alert)
            if severity and alert_data['severity'] != severity:
                continue
            alerts.append(alert_data)

        return alerts

    def update_alert_threshold(self, metric: str, threshold: float):
        if metric not in self._alert_thresholds:
            raise ValueError(f"Invalid metric: {metric}")
        self._alert_thresholds[metric] = threshold

    async def get_active_users_count(self) -> int:
        if not self.redis:
            return 0
        return len(await self.redis.keys('session:*'))