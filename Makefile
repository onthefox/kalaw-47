.PHONY: up down backend frontend migrate clean

up:
	docker-compose up --build

down:
	docker-compose down -v

backend:
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd ui/mind_palace && python -m http.server 3000

migrate:
	cd backend && python -c "from backend.db import init_db; init_db()"

clean:
	docker-compose down -v --rmi local
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name node_modules -exec rm -rf {} +
