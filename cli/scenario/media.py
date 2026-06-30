from __future__ import annotations

import asyncio
import math
import struct
import threading
from typing import Any


def _generate_audio_frame(sample_rate: int = 48000, num_channels: int = 1, duration_ms: int = 20) -> Any:
    from livekit.rtc import AudioFrame
    num_samples = sample_rate * duration_ms // 1000
    samples = [int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
               for i in range(num_samples)]
    data = struct.pack(f"<{num_samples}h", *samples)
    return AudioFrame(data=data, sample_rate=sample_rate,
                      num_channels=num_channels, samples_per_channel=num_samples)


def _generate_video_frame(width: int = 640, height: int = 480) -> Any:
    from livekit.rtc import VideoFrame
    pixel = struct.pack("BBBB", 0, 180, 0, 255)
    return VideoFrame(width, height, 0, pixel * (width * height))


class _AsyncBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def shutdown(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
