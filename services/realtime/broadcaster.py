import asyncio
from typing import List

class LiveEventBroadcaster:
    def __init__(self):
        self.subscribers: List[asyncio.Queue] = []

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def broadcast(self, event: dict):
        for q in self.subscribers:
            await q.put(event)

live_broadcaster = LiveEventBroadcaster()
