.PHONY: up down logs test test-botsim test-gateway test-ingest test-api gateway-state central-db

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

test: test-botsim test-gateway test-ingest test-api

# Go tests run in a container so the host Go version does not matter.
test-botsim:
	docker run --rm -v "$(CURDIR)/simulator/botsim":/src -w /src -v botsim-gomod:/go/pkg/mod -v botsim-gocache:/root/.cache/go-build golang:1.23 go test -race -count=1 ./...

# Python tests run in each service's own image with the source mounted over it.
test-gateway:
	docker compose run --rm --no-deps --build -v ./site/gateway:/app site1-gateway pytest -q

test-ingest:
	docker compose run --rm --no-deps --build -v ./central/ingest:/app central-ingest pytest -q

# Needs central-db running, the tests use a throwaway database on it.
test-api:
	docker compose run --rm --no-deps --build -v ./central:/central -w /central/api \
		-e TEST_ADMIN_URL=postgresql://olivaw:olivaw@central-db:5432/postgres central-api pytest -q

# What the site gateway still has to send, and every robot it knows.
gateway-state:
	docker compose exec site1-gateway python show_state.py

# psql into central TimescaleDB.
central-db:
	docker compose exec central-db psql -U olivaw -d fleet
