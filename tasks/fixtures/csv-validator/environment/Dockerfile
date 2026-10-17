# The csv-validator fixture from ai-dlc's evaluation suite (evaluations/fixtures/csv-validator at f5be4f4): Python 3.12
# on ai-dlc's digest-pinned base, plus git for the controller's anchor commit. workspace/ is the project the agent gets.
FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY workspace/ /workspace/csv-validator/
WORKDIR /workspace/csv-validator
