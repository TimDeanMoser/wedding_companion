SERVER ?= root@wedding_companion
APP_DIR = /srv/wedding

.PHONY: deploy push-env logs backup ssh

# Push local commits, pull on server, sync deps if needed, restart
deploy:
	git push
	ssh $(SERVER) "cd $(APP_DIR) \
		&& git pull \
		&& ~/.local/bin/uv sync \
		&& systemctl restart wedding \
		&& systemctl status wedding --no-pager -l"

# Upload local .env to server and restart
push-env:
	scp .env $(SERVER):$(APP_DIR)/.env
	ssh $(SERVER) "systemctl restart wedding"

# Stream live logs from the server
logs:
	ssh $(SERVER) "journalctl -u wedding -f --no-pager"

# Pull DB and photos from server to ./backup/
backup:
	mkdir -p backup
	rsync -avz --progress $(SERVER):$(APP_DIR)/data/    ./backup/data/
	rsync -avz --progress $(SERVER):$(APP_DIR)/public/pictures/ ./backup/pictures/

# Open an SSH shell on the server
ssh:
	ssh $(SERVER)
