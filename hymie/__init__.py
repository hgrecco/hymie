"""
    hymie
    ~~~~~

    An app to deal with information workflow using web forms and e-mail.

    You can use it to make approval or adminstrative workflows with multiple steps.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""


from .app import create_app
from .common import logger

__all__ = ["create_app", "logger"]
