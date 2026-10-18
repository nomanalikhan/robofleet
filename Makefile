.PHONY: up down logs test-botsim

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Tests run in a container so the host Go version does not matter.
test-botsim:
	docker run --rm -v "$(CURDIR)/simulator/botsim":/src -w /src -v botsim-gomod:/go/pkg/mod -v botsim-gocache:/root/.cache/go-build golang:1.23 go test -race -count=1 ./...
