# Build stage for Go dispatcher
FROM golang:1.26-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o dispatcher ./cmd/dispatcher

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /root/
COPY --from=builder /app/dispatcher .

EXPOSE 8080

CMD ["./dispatcher"]
