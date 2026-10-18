.PHONY: up down logs test-botsim test-gateway gateway-state test-ingest central-db

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Tests run in a container so the host Go version does not matter.
test-botsim:
	docker run --rm -v "$(CURDIR)/simulator/botsim":/src -w /src -v botsim-gomod:/go/pkg/mod -v botsim-gocache:/root/.cache/go-build golang:1.23 go test -race -count=1 ./...

test-gateway:
	docker run --rm -v "$(CURDIR)":/repo -w /repo/site/gateway python:3.12-slim \
		sh -c 'pip install -q --root-user-action=ignore -r requirements.txt && pytest -q'

# Latest state of every robot the site gateway knows.
gateway-state:
	docker compose exec site1-gateway python show_state.py

test-ingest:
	docker run --rm -v "$(CURDIR)/central/ingest":/src -w /src python:3.12-slim \
		sh -c 'pip install -q --root-user-action=ignore -r requirements.txt && pytest -q'

# psql into central TimescaleDB.
central-db:
	docker compose exec central-db psql -U olivaw -d fleet
