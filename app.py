import os
import sys

from hymie import create_app

try:
    path = os.environ["HYMIE_APP_PATH"]
except KeyError:
    sys.exit("HYMIE_APP_PATH environmental variable not set")

# noqa: F401
app = create_app(path)
