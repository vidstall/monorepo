from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Optional

from cli.scenario.media import _generate_audio_frame, _generate_video_frame
from cli.scenario.models import UserEntity

if TYPE_CHECKING:
    from cli.scenario.context import ScenarioContext


class _UsersMixin:

    def add_user(self: ScenarioContext, entity_id: str, room_name: str) -> UserEntity:
        user = UserEntity(entity_id=entity_id, room_name=room_name)
        self.report.users[entity_id] = user
        self.log(f"add user: {entity_id} room={room_name}")
        return user

    def join_room(self: ScenarioContext, entity_id: str, routes_url: str = "", rental_id: Optional[int] = None,
                  video_file: Optional[str] = None) -> None:
        user = self.report.users[entity_id]
        effective_url = routes_url or (self._deployment.routes_url if self._deployment else "")

        def _do() -> None:
            url = f"{effective_url}/api/connection-details?roomName={user.room_name}&participantName={entity_id}"
            if rental_id is not None:
                url += f"&rentalId={rental_id}"
            try:
                resp = urllib.request.urlopen(url, timeout=10)
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    user.rejected = True
                    return
                raise
            details = json.loads(resp.read())

            from livekit.rtc import (
                AudioSource, LocalAudioTrack, LocalVideoTrack,
                Room, RoomOptions, TrackPublishOptions, VideoSource,
            )

            vw, vh, vfps = 640, 480, 30.0
            if video_file:
                import cv2 as _cv2
                _cap = _cv2.VideoCapture(video_file)
                raw_w = int(_cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
                raw_h = int(_cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
                vfps = _cap.get(_cv2.CAP_PROP_FPS) or 30.0
                _cap.release()
                if raw_w > 1280:
                    scale = 1280.0 / raw_w
                    vw, vh = 1280, int(raw_h * scale)
                else:
                    vw, vh = raw_w, raw_h

            room = Room()

            async def _connect() -> None:
                await room.connect(
                    details["serverUrl"],
                    details["participantToken"],
                    options=RoomOptions(auto_subscribe=True),
                )

            self._async_bridge.run(_connect())
            self._rooms[entity_id] = room

            audio_source = AudioSource(sample_rate=48000, num_channels=1)
            audio_track = LocalAudioTrack.create_audio_track("mock-audio", audio_source)
            video_source = VideoSource(vw, vh)
            video_track = LocalVideoTrack.create_video_track(
                "file-video" if video_file else "mock-video", video_source
            )

            async def _publish() -> None:
                lp = room.local_participant
                await lp.publish_track(audio_track, TrackPublishOptions())
                await lp.publish_track(video_track, TrackPublishOptions())

            self._async_bridge.run(_publish())

            stop_event = threading.Event()
            self._track_stops[entity_id] = stop_event

            def _push_frames() -> None:
                audio_frame = _generate_audio_frame()
                if video_file:
                    import cv2 as _cv2
                    from livekit.rtc import VideoFrame
                    cap = _cv2.VideoCapture(video_file)
                    frame_interval = 1.0 / vfps
                    while not stop_event.is_set():
                        ret, bgr = cap.read()
                        if not ret:
                            cap.set(_cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        if bgr.shape[1] != vw or bgr.shape[0] != vh:
                            bgr = _cv2.resize(bgr, (vw, vh))
                        rgba = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2RGBA)
                        vf = VideoFrame(vw, vh, 0, rgba.tobytes())
                        try:
                            video_source.capture_frame(vf)
                            asyncio.run_coroutine_threadsafe(
                                audio_source.capture_frame(audio_frame),
                                self._async_bridge._loop,
                            ).result(timeout=1)
                        except Exception:
                            break
                        stop_event.wait(frame_interval)
                    cap.release()
                else:
                    video_frame = _generate_video_frame()
                    while not stop_event.is_set():
                        try:
                            video_source.capture_frame(video_frame)
                            asyncio.run_coroutine_threadsafe(
                                audio_source.capture_frame(audio_frame),
                                self._async_bridge._loop,
                            ).result(timeout=1)
                        except Exception:
                            break
                        stop_event.wait(0.02)

            thread = threading.Thread(target=_push_frames, daemon=True)
            thread.start()
            self._track_threads[entity_id] = thread

        self.benchmark("join_room", _do, entity_id=entity_id, room_name=user.room_name)
        if not user.rejected:
            user.joined_at = time.time()

    def leave_room(self: ScenarioContext, entity_id: str) -> None:
        user = self.report.users[entity_id]

        def _do() -> None:
            stop_event = self._track_stops.pop(entity_id, None)
            if stop_event:
                stop_event.set()
            thread = self._track_threads.pop(entity_id, None)
            if thread:
                thread.join(timeout=2)

            room = self._rooms.pop(entity_id, None)
            if room:
                async def _disconnect() -> None:
                    await room.disconnect()
                self._async_bridge.run(_disconnect())

        self.benchmark("leave_room", _do, entity_id=entity_id)
        user.left_at = time.time()
        if user.joined_at:
            user.session_duration_ms = (user.left_at - user.joined_at) * 1000
        self.log(f"user left: {entity_id} session={user.session_duration_ms:.0f}ms" if user.session_duration_ms else f"user left: {entity_id}")
