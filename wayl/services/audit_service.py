from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import Depends
from ..db.database import get_db
import json
import logging
from redis import Redis
import uuid
from ..db.models import User
from prometheus_client import Counter

logger = logging.getLogger(__name__)

# Metrics
audit_events = Counter('audit_events_total', 'Total number of audit events', ['event_type'])


class AuditService:
    def __init__(
            self,
            redis_client: Optional[Redis] = None,
            db: Session = Depends(get_db)
    ):
        self.redis = redis_client
        self.db = db
        self.retention_days = 90
        self.sensitive_fields = {'password', 'token', 'secret', 'key', 'credential'}

    async def log_event(
            self,
            event_type: str,
            user_id: Optional[str],
            resource_type: str,
            resource_id: Optional[str],
            action: str,
            status: str,
            details: Dict[str, Any],
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
    ):
        try:
            event_id = str(uuid.uuid4())
            timestamp = datetime.utcnow()

            # Sanitize sensitive information
            sanitized_details = self._sanitize_sensitive_data(details)

            audit_data = {
                'event_id': event_id,
                'timestamp': timestamp.isoformat(),
                'event_type': event_type,
                'user_id': user_id,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'action': action,
                'status': status,
                'details': sanitized_details,
                'ip_address': ip_address,
                'user_agent': user_agent
            }

            # Store in Redis for quick access
            if self.redis:
                await self.redis.setex(
                    f'audit:{event_id}',
                    self.retention_days * 24 * 3600,
                    json.dumps(audit_data)
                )

                # Maintain time-based index
                await self.redis.zadd(
                    'audit_events',
                    {event_id: timestamp.timestamp()}
                )

            # Store in database for permanent retention
            await self._store_in_db(audit_data)

            # Update metrics
            audit_events.labels(event_type=event_type).inc()

            logger.info(f"Audit event logged: {event_id}")

        except Exception as e:
            logger.error(f"Failed to log audit event: {str(e)}")
            raise

    async def get_events(
            self,
            start_time: Optional[datetime] = None,
            end_time: Optional[datetime] = None,
            event_type: Optional[str] = None,
            user_id: Optional[str] = None,
            resource_type: Optional[str] = None,
            limit: int = 100,
            offset: int = 0
    ) -> List[Dict]:
        try:
            if self.redis:
                return await self._get_events_from_redis(
                    start_time, end_time, event_type,
                    user_id, resource_type, limit, offset
                )
            else:
                return await self._get_events_from_db(
                    start_time, end_time, event_type,
                    user_id, resource_type, limit, offset
                )
        except Exception as e:
            logger.error(f"Failed to retrieve audit events: {str(e)}")
            raise

    async def get_event_by_id(self, event_id: str) -> Optional[Dict]:
        try:
            if self.redis:
                event_data = await self.redis.get(f'audit:{event_id}')
                if event_data:
                    return json.loads(event_data)

            return await self._get_event_from_db(event_id)
        except Exception as e:
            logger.error(f"Failed to retrieve audit event: {str(e)}")
            raise

    async def get_user_activity(
            self,
            user_id: str,
            days: int = 30
    ) -> List[Dict]:
        start_time = datetime.utcnow() - timedelta(days=days)
        return await self.get_events(
            start_time=start_time,
            user_id=user_id,
            limit=1000
        )

    def _sanitize_sensitive_data(self, data: Dict) -> Dict:
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_sensitive_data(value)
            elif any(sensitive in key.lower() for sensitive in self.sensitive_fields):
                sanitized[key] = "********"
            else:
                sanitized[key] = value
        return sanitized

    async def _store_in_db(self, audit_data: Dict):
        from ..db.models import AuditLog
        audit_log = AuditLog(**audit_data)
        self.db.add(audit_log)
        await self.db.commit()
        await self.db.refresh(audit_log)

    async def _get_events_from_redis(
            self,
            start_time: Optional[datetime],
            end_time: Optional[datetime],
            event_type: Optional[str],
            user_id: Optional[str],
            resource_type: Optional[str],
            limit: int,
            offset: int
    ) -> List[Dict]:
        min_score = start_time.timestamp() if start_time else '-inf'
        max_score = end_time.timestamp() if end_time else '+inf'

        event_ids = await self.redis.zrangebyscore(
            'audit_events',
            min_score,
            max_score,
            start=offset,
            num=limit
        )

        events = []
        for event_id in event_ids:
            event_data = await self.redis.get(f'audit:{event_id}')
            if event_data:
                event = json.loads(event_data)
                if self._matches_filters(event, event_type, user_id, resource_type):
                    events.append(event)

        return events

    async def _get_events_from_db(
            self,
            start_time: Optional[datetime],
            end_time: Optional[datetime],
            event_type: Optional[str],
            user_id: Optional[str],
            resource_type: Optional[str],
            limit: int,
            offset: int
    ) -> List[Dict]:
        from ..db.models import AuditLog
        query = self.db.query(AuditLog)

        if start_time:
            query = query.filter(AuditLog.timestamp >= start_time)
        if end_time:
            query = query.filter(AuditLog.timestamp <= end_time)
        if event_type:
            query = query.filter(AuditLog.event_type == event_type)
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)

        return query.order_by(AuditLog.timestamp.desc()) \
            .offset(offset) \
            .limit(limit) \
            .all()

    def _matches_filters(
            self,
            event: Dict,
            event_type: Optional[str],
            user_id: Optional[str],
            resource_type: Optional[str]
    ) -> bool:
        if event_type and event['event_type'] != event_type:
            return False
        if user_id and event['user_id'] != user_id:
            return False
        if resource_type and event['resource_type'] != resource_type:
            return False
        return True