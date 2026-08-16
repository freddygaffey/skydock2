# Regular package on purpose: an installed distribution that ships a top-level
# `tests` package (e.g. sphinxcontrib_youtube 100.2.1) would otherwise shadow
# this directory and break `from tests.support import ...` during collection.
