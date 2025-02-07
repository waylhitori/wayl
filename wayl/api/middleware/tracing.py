from fastapi import Request, Response
import time
import logging
import uuid
from typing import Optional, Dict, Any
from prometheus_client import Histogram, Counter
import json
from opentelemetry import trace
from opentelemetry.trace.status import Status, StatusCode
import asyncio
from redis import Redis
from sqlalchemy.orm import Session
from ...db.database import get_db

logger = logging.getLogger(__name__)

# Metrics
request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint', 'status_code']
)
request_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)


class TracingMiddleware:
    def __init__(
            self,
            app,
            redis_client: Optional[Redis] = None,
            exclude_paths: Optional[list] = None
    ):
        self.app = app
        self.redis = redis_client
        self.exclude_paths = set(exclude_paths or [])
        self.tracer = trace.get_tracer(__name__)

    async def __call__(
            self,
            request: Request,
            call_next
    ) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        trace_id = self._get_trace_id(request)
        start_time = time.time()

        try:
            with self.tracer.start_as_current_span(
                    f"{request.method} {request.url.path}",
                    kind=trace.SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.trace_id", trace_id)

                # Add request headers to span
                for key, value in request.headers.items():
                    if key.lower() not in {'authorization', 'cookie'}:
                        span.set_attribute(f"http.header.{key}", value)

                # Add custom attributes
                span.set_attribute("custom.trace_id", trace_id)

                response = await self._process_request(request, call_next, trace_id)

                duration = time.time() - start_time
                self._record_metrics(request, response, duration)

                return response

        except Exception as e:
            duration = time.time() - start_time
            self._record_error(request, e, trace_id, duration)
            raise

    async def _process_request(
            self,
            request: Request,
            call_next,
            trace_id: str
    ) -> Response:
        context = {
            "trace_id": trace_id,
            "start_time": time.time(),
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.query_params),
            "client_ip": request.client.host,
            "user_agent": request.headers.get("user-agent")
        }

        try:
            response = await call_next(request)

            context.update({
                "status_code": response.status_code,
                "duration": time.time() - context["start_time"]
            })

            if response.status_code >= 400:
                logger.warning(f"Request failed: {json.dumps(context)}")

            await self._store_trace(trace_id, context)
            return response

        except Exception as e:
            context.update({
                "error": str(e),
                "duration": time.time() - context["start_time"]
            })
            logger.error(f"Request error: {json.dumps(context)}")
            await self._store_trace(trace_id, context)
            raise

    def _get_trace_id(self, request: Request) -> str:
        return request.headers.get("X-Trace-ID") or str(uuid.uuid4())

    def _record_metrics(
            self,
            request: Request,
            response: Response,
            duration: float
    ):
        labels = {
            "method": request.method,
            "endpoint": request.url.path,
            "status_code": response.status_code
        }

        request_duration.labels(**labels).observe(duration)
        request_total.labels(**labels).inc()

    def _record_error(
            self,
            request: Request,
            error: Exception,
            trace_id: str,
            duration: float
    ):
        context = {
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "error": str(error),
            "duration": duration
        }
        logger.error(f"Request failed: {json.dumps(context)}")

    async def _store_trace(self, trace_id: str, context: Dict[str, Any]):
        try:
            if self.redis:
                await self.redis.setex(
                    f"trace:{trace_id}",
                    86400,  # 24 hours retention
                    json.dumps(context)
                )
        except Exception as e:
            logger.error(f"Failed to store trace: {str(e)}")

    async def get_trace(self, trace_id: str) -> Optional[Dict]:
        try:
            if self.redis:
                trace_data = await self.redis.get(f"trace:{trace_id}")
                if trace_data:
                    return json.loads(trace_data)
        except Exception as e:
            logger.error(f"Failed to get trace: {str(e)}")
        return None