FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /botsim .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /botsim /botsim
# Ask DNS before /etc/hosts so the reverse lookup in serialNamespace returns
# the compose container name instead of the random container ID.
COPY nsswitch.conf /etc/nsswitch.conf
EXPOSE 8080
ENTRYPOINT ["/botsim"]
