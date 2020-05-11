"""
    hymie.common
    ~~~~~~~~~~~~

    Common functions and classes.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import functools
import logging
import re

from flask import flash
from flask_wtf import FlaskForm
from jinja2 import BaseLoader, Environment
from wtforms import StringField, SubmitField
from wtforms import validators as v

logger = logging.getLogger("hymie")

# A jinja environment detached from the app.
# Used to convert string to templates.
BASE_JINJA_ENV = Environment(loader=BaseLoader())

JINJA2_VAR_MATCHER = re.compile(r"{{([ \ta-zA-Z_][ \ta-zA-Z0-9_.|]*)}}")


def extract_jinja2_variables(html):
    """Extrat jinja2 variables (such as {{ name }}) from an html.

    Might include modifiers. e.g. '{{ name | upper }}' -> 'name | upper'

    Parameters
    ----------
    html : str

    Returns
    -------
    tuple
        Content of the
    """
    return tuple(s.split("|", 1)[0].strip() for s in JINJA2_VAR_MATCHER.findall(html))


def flash_errors(form):
    """Flashes form errors
    """
    for field, errors in form.errors.items():
        for error in errors:
            flash(
                "Error in the %s field - %s" % (getattr(form, field).label.text, error),
                "danger",
            )


class RegisterForm(FlaskForm):
    """Register form.
    """

    e_mail = StringField("e-mail", validators=[v.Email(), v.DataRequired()])

    submit = SubmitField("Submit")


class SmartLoader:
    """"Render a template that depends on stored data without loading each
    multiple times

    Usage:
    >>> sl = SmartLoader(storage, "{{ form1.last_name | upper }}, {{ form1.first_name }}")
    >>> sl(uid)

    where uid is the unique identifier of a user.

    Parameters
    ----------
    storage : Storage
    html : str
        An html template
    """

    def __init__(self, storage, html):
        self.storage = storage
        self.variables = extract_jinja2_variables(html)
        self.forms = set(var.split(".")[0] for var in self.variables)
        self.tmpl = BASE_JINJA_ENV.from_string(html)

    @functools.lru_cache
    def __call__(self, uid):
        kwargs = {k: self.storage.user_retrieve(uid, k) for k in self.forms}
        return self.tmpl.render(**kwargs)


# TODO: internationalization
MSG_ALREADY_REGISTERED = "Esa dirección de e-mail ya esta registrada en el sistema. <a href='%s'>Recuperar link de acceso</a>"
MSG_ERROR_REGISTERING = "Hubo un problema al generar un nuevo usuario."
MSG_ERROR_SENDING = "Hubo un problema al enviar el e-mail."
MSG_EMAIL_SENT = "Se envió un e-mail a %s. Por favor revisá su casilla."
MSG_INVALID_UID = "El link de acceso es inválido."
MSG_INVALID_UID_HEP = "El link de acceso es inválido para el estado del sistema."