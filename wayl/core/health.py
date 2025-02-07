from typing import Dict, List, Optional
import psutil
import torch
import logging
import asyncio
from datetime import datetime
from enum import Enum
from prometheus_client import Gauge, Counter

logger = logging.getLogger(__name__)

# Metrics
system_health = Gauge('system_health_status', 'System health status', ['component'])
component_uptime = Gauge('component_uptime_seconds', 'Component uptime', ['component'])
health_check_errors = Counter('health_check_errors_total', 'Health check errors', ['component'])


class HealthStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SystemHealth:
    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self._status_history: List[Dict] = []
        self._components_status: Dict = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._thresholds = {
            'cpu_percent': {'warning': 70, 'critical': 90},
            'memory_percent': {'warning': 80, 'critical': 95},
            'disk_percent': {'warning': 85, 'critical': 95},
            'gpu_memory_percent': {'warning': 85, 'critical': 95}
        }

    async def start_monitoring(self):
        if not self._monitoring_task:
            self._monitoring_task = asyncio.create_task(self._monitor_loop())
            logger.info("Health monitoring started")

    async def stop_monitoring(self):
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            logger.info("Health monitoring stopped")

    async def get_health_status(self) -> Dict:
        return {
            'status': self._get_overall_status(),
            'components': self._components_status,
            'timestamp': datetime.utcnow().isoformat(),
            'details': await self._collect_detailed_metrics()
        }

    async def _monitor_loop(self):
        while True:
            try:
                status = await self._check_all_components()
                self._update_status_history(status)
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Health monitoring error: {str(e)}")
                await asyncio.sleep(5)

    async def _check_all_components(self) -> Dict:
        checks = {
            'system': self._check_system_resources(),
            'database': self._check_database(),
            'redis': self._check_redis(),
            'model_service': self._check_model_service(),
            'blockchain': self._check_blockchain_service()
        }

        results = {}
        for name, check in checks.items():
            try:
                status = await check
                results[name] = status
                self._components_status[name] = status
                system_health.labels(component=name).set(
                    1 if status['status'] == HealthStatus.OK else 0
                )
            except Exception as e:
                logger.error(f"Health check failed for {name}: {str(e)}")
                health_check_errors.labels(component=name).inc()
                results[name] = {
                    'status': HealthStatus.ERROR,
                    'error': str(e)
                }

        return results

    async def _check_system_resources(self) -> Dict:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        status = HealthStatus.OK
        warnings = []

        if cpu_percent > self._thresholds['cpu_percent']['critical']:
            status = HealthStatus.CRITICAL
            warnings.append(f"CPU usage critical: {cpu_percent}%")
        elif cpu_percent > self._thresholds['cpu_percent']['warning']:
            status = HealthStatus.WARNING
            warnings.append(f"CPU usage high: {cpu_percent}%")

        if memory.percent > self._thresholds['memory_percent']['critical']:
            status = HealthStatus.CRITICAL
            warnings.append(f"Memory usage critical: {memory.percent}%")
        elif memory.percent > self._thresholds['memory_percent']['warning']:
            status = HealthStatus.WARNING
            warnings.append(f"Memory usage high: {memory.percent}%")

        return {
            'status': status,
            'metrics': {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'disk_percent': disk.percent
            },
            'warnings': warnings
        }

    def _get_overall_status(self) -> HealthStatus:
        statuses = [status['status'] for status in self._components_status.values()]
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        if HealthStatus.ERROR in statuses:
            return HealthStatus.ERROR
        if HealthStatus.WARNING in statuses:
            return HealthStatus.WARNING
        return HealthStatus.OK

    async def _collect_detailed_metrics(self) -> Dict:
        return {
            'system_load': await self._get_system_load(),
            'memory_details': await self._get_memory_details(),
            'disk_usage': await self._get_disk_usage(),
            'network_stats': await self._get_network_stats(),
            'process_stats': await self._get_process_stats()
        }

    def _update_status_history(self, status: Dict):
        self._status_history.append({
            'timestamp': datetime.utcnow(),
            'status': status
        })
        if len(self._status_history) > 1000:
            self._status_history.pop(0)