'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';

import { PageClientImpl } from './[roomName]/PageClientImpl';
import { isVideoCodec } from '@/lib/types';

function RoomPage() {
  const searchParams = useSearchParams();
  const roomName = searchParams.get('roomName') ?? '';
  const codecParam = searchParams.get('codec') ?? undefined;
  const codec = typeof codecParam === 'string' && isVideoCodec(codecParam) ? codecParam : 'vp9';
  const hq = searchParams.get('hq') === 'true';
  const singlePC = searchParams.get('singlePC') !== 'false';

  return (
    <PageClientImpl
      roomName={roomName}
      region={searchParams.get('region') ?? undefined}
      rentalId={searchParams.get('rentalId') ?? undefined}
      hq={hq}
      codec={codec}
      singlePeerConnection={singlePC}
    />
  );
}

export default function Page() {
  return (
    <React.Suspense>
      <RoomPage />
    </React.Suspense>
  );
}
