'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';
import { videoCodecs } from 'livekit-client';
import { VideoConferenceClientImpl } from './VideoConferenceClientImpl';
import { isVideoCodec } from '@/lib/types';

function CustomRoomPage() {
  const searchParams = useSearchParams();
  const liveKitUrl = searchParams.get('liveKitUrl') ?? undefined;
  const token = searchParams.get('token') ?? undefined;
  const codecParam = searchParams.get('codec') ?? undefined;
  const singlePC = searchParams.get('singlePC') === 'true';

  if (typeof liveKitUrl !== 'string') {
    return <h2>Missing LiveKit URL</h2>;
  }
  if (typeof token !== 'string') {
    return <h2>Missing LiveKit token</h2>;
  }
  if (codecParam !== undefined && !isVideoCodec(codecParam)) {
    return <h2>Invalid codec, if defined it has to be [{videoCodecs.join(', ')}].</h2>;
  }

  return (
    <main data-lk-theme="default" style={{ height: '100%' }}>
      <VideoConferenceClientImpl
        liveKitUrl={liveKitUrl}
        token={token}
        codec={codecParam}
        singlePeerConnection={singlePC}
      />
    </main>
  );
}

export default function CustomRoomConnection() {
  return (
    <React.Suspense>
      <CustomRoomPage />
    </React.Suspense>
  );
}
