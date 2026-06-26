"""Virtual client bot: simulates human participants joining LiveKit rooms."""
from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import urllib.error
import urllib.request


ROUTES_URL = os.environ.get("ROUTES_URL", "http://localhost")
ROOM_NAME = os.environ.get("ROOM_NAME", "bot-room")
BOT_COUNT = int(os.environ.get("BOT_COUNT", "1"))
SESSION_DURATION = int(os.environ.get("SESSION_DURATION", "30"))


def _make_audio_frame(sample_rate: int = 48000, num_channels: int = 1, duration_ms: int = 20):
    from livekit.rtc import AudioFrame
    num_samples = sample_rate * duration_ms // 1000
    samples = [int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
               for i in range(num_samples)]
    data = struct.pack(f"<{num_samples}h", *samples)
    return AudioFrame(data=data, sample_rate=sample_rate,
                      num_channels=num_channels, samples_per_channel=num_samples)


def _make_video_frame(width: int = 640, height: int = 480):
    from livekit.rtc import VideoFrame
    pixel = struct.pack("BBBB", 0, 180, 0, 255)
    return VideoFrame(width, height, 0, pixel * (width * height))


async def run_bot(bot_id: int) -> None:
    from livekit.rtc import (
        AudioSource, LocalAudioTrack, LocalVideoTrack,
        Room, RoomOptions, TrackPublishOptions, VideoSource,
    )

    participant_name = f"vclient-{bot_id}"
    print(f"[bot-{bot_id}] starting", flush=True)

    while True:
        try:
            url = (f"{ROUTES_URL}/api/connection-details"
                   f"?roomName={ROOM_NAME}&participantName={participant_name}")
            resp = urllib.request.urlopen(url, timeout=10)
            details = json.loads(resp.read())

            room = Room()
            await room.connect(
                details["serverUrl"],
                details["participantToken"],
                options=RoomOptions(auto_subscribe=True),
            )
            print(f"[bot-{bot_id}] joined {ROOM_NAME}", flush=True)

            audio_source = AudioSource(sample_rate=48000, num_channels=1)
            video_source = VideoSource(640, 480)
            audio_track = LocalAudioTrack.create_audio_track("bot-audio", audio_source)
            video_track = LocalVideoTrack.create_video_track("bot-video", video_source)

            lp = room.local_participant
            await lp.publish_track(audio_track, TrackPublishOptions())
            await lp.publish_track(video_track, TrackPublishOptions())

            audio_frame = _make_audio_frame()
            video_frame = _make_video_frame()
            elapsed = 0.0
            while elapsed < SESSION_DURATION:
                video_source.capture_frame(video_frame)
                await audio_source.capture_frame(audio_frame)
                await asyncio.sleep(0.02)
                elapsed += 0.02

            await room.disconnect()
            print(f"[bot-{bot_id}] left {ROOM_NAME}", flush=True)

        except urllib.error.URLError as exc:
            print(f"[bot-{bot_id}] routes unreachable: {exc} — retrying in 5s", flush=True)
            await asyncio.sleep(5)
        except Exception as exc:
            print(f"[bot-{bot_id}] error: {exc} — retrying in 5s", flush=True)
            await asyncio.sleep(5)


async def main() -> None:
    print(f"vclient starting: {BOT_COUNT} bot(s) → {ROUTES_URL}  room={ROOM_NAME}  session={SESSION_DURATION}s",
          flush=True)
    await asyncio.gather(*[run_bot(i) for i in range(BOT_COUNT)])


if __name__ == "__main__":
    asyncio.run(main())
