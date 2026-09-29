"""Isolate every test from the developer's real config/, database and auth tokens."""
import os
import tempfile

# Must run before any application module imports utils.constants.
os.environ["AUDIBLE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="audible-test-config-")
