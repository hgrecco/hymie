import logging

from datastruct.exceptions import MultipleError

from hymie.common import logger

try:
    from app import app
except MultipleError as mex:
    for ex in mex.exceptions:
        print(
            "%s %s %s"
            % (type(ex).__name__, ex.key, ".".join(ex.path).replace(".[", "["))
        )
    raise


handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(name)-12s %(levelname)-8s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


app.run(debug=True)
