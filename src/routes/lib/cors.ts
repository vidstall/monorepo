const ALLOWED_HEADERS = 'Content-Type, Authorization';
const ALLOWED_METHODS = 'GET, POST, OPTIONS';

export function getCorsHeaders(origin: string | null) {
  const allowOrigin = origin ?? '*';
  return {
    'Access-Control-Allow-Origin': allowOrigin,
    'Access-Control-Allow-Credentials': 'true',
    'Access-Control-Allow-Headers': ALLOWED_HEADERS,
    'Access-Control-Allow-Methods': ALLOWED_METHODS,
    Vary: 'Origin',
  };
}
