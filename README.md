# autonomous-maritime-risk-engine

## Docker

Build the image:

```
docker build -t maritime-risk-engine:latest .
```

Run the container:

```
docker run -d --name maritime-risk-engine -p 8000:8000 maritime-risk-engine:latest
```

Verify:

```
curl http://127.0.0.1:8000/health
```

Run the CLI replay script inside the running container:

```
docker exec maritime-risk-engine python replay_cli.py fixtures/03_conflicting_signals.json
```

Stop and remove:

```
docker stop maritime-risk-engine
docker rm maritime-risk-engine
```

Note: SQLite storage is inside the container's filesystem and is not
persisted across container removal (no volume is mounted). This is
consistent with the PRD's local/in-memory storage constraint; mount a
volume at `/app/data` if you need the database to survive a restart.