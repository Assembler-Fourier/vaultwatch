FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# In docker-compose (full mode) the dashboard talks to the real services
# over the network, so it never needs an Anthropic key of its own to build.
ENV NEXT_PUBLIC_MODE=full
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./

ENV PORT=3000
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-p", "3000"]
