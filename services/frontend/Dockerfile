FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_ROUTES_URL=/api
ENV NEXT_PUBLIC_ROUTES_URL=$NEXT_PUBLIC_ROUTES_URL
ARG NEXT_PUBLIC_PACKAGE_ID=""
ARG NEXT_PUBLIC_REGISTRY_OBJECT_ID=""
ARG NEXT_PUBLIC_SUI_NETWORK="devnet"
ENV NEXT_PUBLIC_PACKAGE_ID=$NEXT_PUBLIC_PACKAGE_ID
ENV NEXT_PUBLIC_REGISTRY_OBJECT_ID=$NEXT_PUBLIC_REGISTRY_OBJECT_ID
ENV NEXT_PUBLIC_SUI_NETWORK=$NEXT_PUBLIC_SUI_NETWORK
RUN pnpm build

FROM caddy:2-alpine AS runner
COPY --from=builder /app/out /srv
EXPOSE 3000
CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":3000"]
