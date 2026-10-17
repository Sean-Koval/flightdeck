"""Shared pytest settings."""

# Vendored tasks under fixtures/ carry their own hidden tests (Harbor runs them in a container), not flightdeck's.
collect_ignore = ["fixtures"]
