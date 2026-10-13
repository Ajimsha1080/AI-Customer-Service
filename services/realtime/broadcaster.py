import json
import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any
from jose import jwt, JWTError

from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.realtime")

class EventRingBuffer:
    """Bounded circular buffer storing recent events for Last-Event-ID replay."""
    def __init__(self, capacity: int = 200):
        self.capacity = capacity
        self.buffer: List[Dict[str, Any]] = []

    def append(self, event: Dict[str, Any]):
        if len(self.buffer) >= self.capacity:
            self.buffer.pop(0)
        self.buffer.append(event)

    def get_events_after(self, last_event_id: str) -> List[Dict[str, Any]]:
        found = False
        replay = []
        for event in self.buffer:
            if found:
                replay.append(event)
            elif str(event.get("id")) == str(last_event_id):
                found = True
        return replay


class MultiTenantRealtimeHub:
    """Enterprise multi-tenant realtime broadcaster supporting:
    - Cross-replica Redis Pub/Sub subscriber task fanning out to local queues
    - Redis Streams (xadd/xrange) for distributed Last-Event-ID replay across replicas
    - Strict organization & property scoping
    - Sequential Event IDs & Last-Event-ID replay
    - Bounded subscriber queues (max 100 items per subscriber with slow consumer disconnect)
    """

    def __init__(self):
        # channel_name -> Set[asyncio.Queue]
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        # channel_name -> EventRingBuffer
        self._buffers: Dict[str, EventRingBuffer] = {}
        # queue -> Set[channel_name]
        self._queue_channels: Dict[asyncio.Queue, Set[str]] = {}
        self._seq = 0
        self._lock = asyncio.Lock()
        self.replica_id = str(uuid.uuid4())
        self._redis_client = None
        self._redis_pubsub = None
        self._redis_task: Optional[asyncio.Task] = None
        self._is_running = False

    def _get_buffer(self, channel: str) -> EventRingBuffer:
        if channel not in self._buffers:
            self._buffers[channel] = EventRingBuffer(capacity=200)
        return self._buffers[channel]

    async def _get_redis(self):
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=1.0,
                    decode_responses=True
                )
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                self._redis_client = None
        return self._redis_client

    async def start_redis_subscriber(self):
        """Starts background Redis PubSub subscriber task for cross-replica event fanout."""
        if self._is_running:
            return
        self._is_running = True
        self._redis_task = asyncio.create_task(self._redis_subscriber_loop())
        logger.info(f"Redis subscriber task started on replica {self.replica_id}")

    async def stop_redis_subscriber(self):
        """Stops background Redis PubSub subscriber task and cleans up connections."""
        self._is_running = False
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
            self._redis_task = None
        if self._redis_pubsub:
            try:
                if hasattr(self._redis_pubsub, "aclose"):
                    await self._redis_pubsub.aclose()
                else:
                    await self._redis_pubsub.close()
            except Exception:
                pass
            self._redis_pubsub = None
        if self._redis_client:
            try:
                if hasattr(self._redis_client, "aclose"):
                    await self._redis_client.aclose()
                else:
                    await self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None
        logger.info(f"Redis subscriber stopped on replica {self.replica_id}")

    async def _redis_subscriber_loop(self):
        """Background loop reading from Redis PubSub pattern and dispatching to local subscribers."""
        while self._is_running:
            try:
                redis_cli = await self._get_redis()
                if not redis_cli:
                    await asyncio.sleep(2.0)
                    continue

                self._redis_pubsub = redis_cli.pubsub()
                await self._redis_pubsub.psubscribe("org:*", "platform", "general")

                async for message in self._redis_pubsub.listen():
                    if not self._is_running:
                        break
                    if message.get("type") in ["pmessage", "message"]:
                        channel = message.get("channel")
                        raw_data = message.get("data")
                        if not raw_data:
                            continue
                        try:
                            envelope = json.loads(raw_data)
                            # Ignore self-published events already delivered to local queues
                            if envelope.get("replica_id") == self.replica_id:
                                continue

                            # Deliver to local in-memory queues on this replica
                            self._deliver_to_local_subscribers(channel, envelope)
                        except Exception as parse_err:
                            logger.error(f"Error parsing redis message on replica {self.replica_id}: {parse_err}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Redis subscriber connection lost on replica {self.replica_id}: {e}. Retrying in 2s...")
                await asyncio.sleep(2.0)

    def _deliver_to_local_subscribers(self, channel: str, envelope: Dict[str, Any]):
        """Dispatches event to local subscribers and updates local replay ring buffer."""
        buf = self._get_buffer(channel)
        buf.append(envelope)

        if channel in self._subscribers:
            subscribers_to_drop = []
            for q in list(self._subscribers[channel]):
                try:
                    if q.qsize() < 100:
                        q.put_nowait(envelope)
                    else:
                        logger.warning(f"Slow consumer detected on replica {self.replica_id}, disconnecting subscriber.")
                        subscribers_to_drop.append(q)
                except Exception:
                    subscribers_to_drop.append(q)
            for slow_q in subscribers_to_drop:
                self.unsubscribe(slow_q)

    async def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        organization_id: Optional[str] = None,
        property_id: Optional[str] = None,
        is_platform: bool = False
    ) -> str:
        """Publishes an event to tenant-scoped channels and platform superadmin stream."""
        async with self._lock:
            self._seq += 1
            event_id = f"evt_{int(time.time()*1000)}_{self._seq}"

        envelope = {
            "id": event_id,
            "type": event_type,
            "replica_id": self.replica_id,
            "organization_id": organization_id,
            "property_id": property_id,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        target_channels = []
        if is_platform:
            target_channels.append("platform")

        if organization_id:
            target_channels.append(f"org:{organization_id}")
            if property_id:
                target_channels.append(f"org:{organization_id}:prop:{property_id}")
            target_channels.append("platform")

        if not target_channels:
            target_channels.append("general")

        for ch in target_channels:
            self._deliver_to_local_subscribers(ch, envelope)

        # Publish to Redis and Redis Streams for replica broadcast and replay
        await self._publish_to_redis(target_channels, envelope)
        return event_id

    async def subscribe(
        self,
        channels: List[str],
        last_event_id: Optional[str] = None
    ) -> Tuple[asyncio.Queue, List[Dict[str, Any]]]:
        """Subscribes to channels, returning (queue, missed_events_to_replay)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queue_channels[q] = set(channels)

        missed_events = []

        # 1. Attempt distributed replay via Redis Streams if last_event_id provided
        redis_replayed = False
        if last_event_id:
            redis_cli = await self._get_redis()
            if redis_cli:
                try:
                    for ch in channels:
                        stream_key = f"stream:{ch}"
                        # Read last 200 stream entries
                        entries = await redis_cli.xrange(stream_key, min="-", max="+", count=200)
                        found = False
                        for entry_id, fields in entries:
                            event_json = fields.get("event")
                            if event_json:
                                evt = json.loads(event_json)
                                if found:
                                    missed_events.append(evt)
                                elif str(evt.get("id")) == str(last_event_id):
                                    found = True
                    if missed_events:
                        redis_replayed = True
                except Exception as e:
                    logger.debug(f"Redis stream replay fallback to memory: {e}")

        for ch in channels:
            if ch not in self._subscribers:
                self._subscribers[ch] = set()
            self._subscribers[ch].add(q)

            # 2. In-memory ring buffer replay fallback
            if last_event_id and not redis_replayed:
                buf = self._get_buffer(ch)
                replay = buf.get_events_after(last_event_id)
                missed_events.extend(replay)

        # De-duplicate replayed events by id
        seen_ids = set()
        deduped_missed = []
        for evt in missed_events:
            if evt["id"] not in seen_ids:
                seen_ids.add(evt["id"])
                deduped_missed.append(evt)

        return q, deduped_missed

    def unsubscribe(self, q: asyncio.Queue):
        """Removes a subscriber queue from all its channels."""
        channels = self._queue_channels.pop(q, set())
        for ch in channels:
            if ch in self._subscribers and q in self._subscribers[ch]:
                self._subscribers[ch].remove(q)

    async def _publish_to_redis(self, channels: List[str], envelope: Dict[str, Any]):
        redis_cli = await self._get_redis()
        if not redis_cli:
            return
        payload_str = json.dumps(envelope)
        for ch in channels:
            try:
                # PubSub to other replicas
                await redis_cli.publish(ch, payload_str)
                # Redis Stream for replay across replicas
                await redis_cli.xadd(f"stream:{ch}", {"event": payload_str}, maxlen=200)
            except Exception:
                pass

    # Backward compatibility with legacy tests
    async def broadcast(self, event: dict):
        org_id = event.get("organization_id")
        prop_id = event.get("property_id")
        await self.publish(
            event_type=event.get("type", "BROADCAST"),
            data=event,
            organization_id=org_id,
            property_id=prop_id,
            is_platform=True
        )


realtime_hub = MultiTenantRealtimeHub()
live_broadcaster = realtime_hub


# --- 60-SECOND REAL-TIME ONE-TIME TICKET AUTHENTICATION ---
TICKET_ACTION = "realtime_stream_auth"

def generate_realtime_ticket(user_id: str, organization_id: str, role: str) -> str:
    """Generates a 60-second HMAC-signed single-use ticket for EventSource / WebSocket auth."""
    payload = {
        "sub": user_id,
        "org_id": organization_id,
        "role": role,
        "action": TICKET_ACTION,
        "jti": str(uuid.uuid4()),
        "exp": int(time.time()) + 60
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

def verify_realtime_ticket(ticket: str) -> Optional[Dict[str, Any]]:
    """Validates 60-second realtime ticket signature and expiry."""
    if not ticket:
        return None
    try:
        payload = jwt.decode(ticket, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("action") != TICKET_ACTION:
            return None
        return payload
    except JWTError:
        return None
