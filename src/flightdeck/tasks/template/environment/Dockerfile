# The local runner's environment. Hangar trials use the hangar environment named in task.toml's [flightdeck] instead.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest
WORKDIR /workspace
