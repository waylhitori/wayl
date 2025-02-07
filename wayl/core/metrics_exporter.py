from typing import Dict, Any, Optional, List
import prometheus_client
from prometheus_client import Counter, Gauge, Histogram, Summary
import time
import psutil
import torch
import logging
from dataclasses import dataclass
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class MetricDefinition:
    name: str
    type: str
    description: str
    labels: List[str] = None
    buckets: List[float] = None


class MetricsExporter:
    def __init__(self, app_name: str):
        self.app_name = app_name
        self._setup_metrics()
        self._collection_task: Optional[asyncio.Task] = None

    def _setup_metrics(self):
        # System metrics
        self.system_metrics = {
            "cpu_usage": Gauge(
                "system_cpu_usage_percent",
                "CPU usage percentage",
                ["cpu"]
            ),
            "memory_usage": Gauge(
                "system_memory_usage_bytes",
                "Memory usage in bytes",
                ["type"]
            ),
            "disk_usage": Gauge(
                "system_disk_usage_bytes",
                "Disk usage in bytes",
                ["device"]
            ),
            "network_io": Counter(
                "system_network_bytes_total",
                "Network I/O bytes",
                ["interface", "direction"]
            )
        }

        # Application metrics
        self.app_metrics = {
            "requests_total": Counter(
                "app_requests_total",
                "Total HTTP requests",
                ["method", "endpoint", "status"]
            ),
            "request_duration_seconds": Histogram(
                "app_request_duration_seconds",
                "HTTP request duration in seconds",
                ["endpoint"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
            ),
            "active_users": Gauge(
                "app_active_users",
                "Number of active users"
            )
        }

        # Model metrics
        self.model_metrics = {
            "model_inference_time": Histogram(
                "model_inference_duration_seconds",
                "Model inference duration in seconds",
                ["model_id"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
            ),
            "model_memory_usage": Gauge(
                "model_memory_usage_bytes",
                "Model memory usage in bytes",
                ["model_id"]
            ),
            "inference_requests": Counter(
                "model_inference_requests_total",
                "Total number of inference requests",
                ["model_id", "status"]
            )
        }

        # Business metrics
        self.business_metrics = {
            "token_transactions": Counter(
                "business_token_transactions_total",
                "Total token transactions",
                ["type", "status"]
            ),
            "active_agents": Gauge(
                "business_active_agents",
                "Number of active agents",
                ["level"]
            ),
            "revenue": Counter(
                "business_revenue_total",
                "Total revenue in tokens",
                ["type"]
            )
        }

    async def start_collecting(self, interval: int = 15):
        if not self._collection_task:
            self._collection_task = asyncio.create_task(
                self._collect_metrics_loop(interval)
            )

    async def stop_collecting(self):
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
            self._collection_task = None

    async def _collect_metrics_loop(self, interval: int):
        while True:
            try:
                await self._collect_system_metrics()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Metrics collection error: {str(e)}")
                await asyncio.sleep(5)

    async def _collect_system_metrics(self):
        # CPU metrics
        for cpu_num, cpu_percent in enumerate(psutil.cpu_percent(percpu=True)):
            self.system_metrics["cpu_usage"].labels(cpu=f"cpu{cpu_num}").set(cpu_percent)

        # Memory metrics
        memory = psutil.virtual_memory()
        self.system_metrics["memory_usage"].labels(type="used").set(memory.used)
        self.system_metrics["memory_usage"].labels(type="available").set(memory.available)

        # Disk metrics
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                self.system_metrics["disk_usage"].labels(
                    device=partition.device
                ).set(usage.used)
            except:
                continue

        # Network metrics
        network = psutil.net_io_counters(pernic=True)
        for interface, stats in network.items():
            self.system_metrics["network_io"].labels(
                interface=interface, direction="bytes_sent"
            ).inc(stats.bytes_sent)
            self.system_metrics["network_io"].labels(
                interface=interface, direction="bytes_recv"
            ).inc(stats.bytes_recv)

    def track_request(
            self,
            method: str,
            endpoint: str,
            status: int,
            duration: float
    ):
        self.app_metrics["requests_total"].labels(
            method=method,
            endpoint=endpoint,
            status=status
        ).inc()

        self.app_metrics["request_duration_seconds"].labels(
            endpoint=endpoint
        ).observe(duration)

    def track_model_inference(
            self,
            model_id: str,
            duration: float,
            status: str = "success"
    ):
        self.model_metrics["model_inference_time"].labels(
            model_id=model_id
        ).observe(duration)

        self.model_metrics["inference_requests"].labels(
            model_id=model_id,
            status=status
        ).inc()

        if torch.cuda.is_available():
            memory_allocated = torch.cuda.memory_allocated()
            self.model_metrics["model_memory_usage"].labels(
                model_id=model_id
            ).set(memory_allocated)

    def track_token_transaction(
            self,
            transaction_type: str,
            amount: float,
            status: str = "success"
    ):
        self.business_metrics["token_transactions"].labels(
            type=transaction_type,
            status=status
        ).inc()

        if status == "success":
            self.business_metrics["revenue"].labels(
                type=transaction_type
            ).inc(amount)

    def update_active_agents(self, level: str, count: int):
        self.business_metrics["active_agents"].labels(level=level).set(count)

    def update_active_users(self, count: int):
        self.app_metrics["active_users"].set(count)