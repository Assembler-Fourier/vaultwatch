FROM rust:1-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates wget && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/engine-rust ./engine-rust
ENV PORT=8081
ENV AUDIT_LOG_PATH=/app/data/audit.log
RUN mkdir -p /app/data
EXPOSE 8081
CMD ["./engine-rust"]
