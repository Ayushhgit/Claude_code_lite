import json
import asyncio
from typing import Callable, Dict, List

class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    def emit(self, event_type: str, **kwargs):
        for callback in self._listeners.get(event_type, []):
            try:
                callback(**kwargs)
            except Exception as e:
                print(f"Error in event listener for {event_type}: {e}")
        
        # Also broadcast to websockets if applicable
        try:
            from server.broadcaster import broadcaster
            if broadcaster.active_connections:
                payload = json.dumps({"type": event_type, "data": kwargs})
                loop = asyncio.new_event_loop()
                loop.run_until_complete(broadcaster.broadcast(payload))
                loop.close()
        except Exception:
            pass

bus = EventBus()
