# The local runner's environment (hangar trials use the hangar environment named in task.toml instead): an empty git
# repository with Python 3 and its standard library, as task.md promises.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/semver
RUN git init -q . && git config user.name agent && git config user.email agent@localhost
