"""
    hymie.forms
    ~~~~~~~~~~~

    Generate a WTForm from a Markdown based form.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

from types import SimpleNamespace

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired, FileStorage
from wtforms import RadioField, SelectField, StringField, SubmitField, TextAreaField
from wtforms import validators as v
from wtforms.fields.html5 import DateField
from wtforms.widgets.core import HTMLString, TextInput
from wtforms_components import TimeField, read_only

FORMATTERS = {}


class FileSize(object):
    """Validates that the uploaded file is within a minimum and maximum file size (set in bytes).
    :param min_size: minimum allowed file size (in bytes). Defaults to 0 bytes.
    :param max_size: maximum allowed file size (in bytes).
    :param message: error message
    You can also use the synonym ``file_size``.
    """

    def __init__(self, max_size, min_size=0, message=None):
        self.min_size = min_size
        self.max_size = max_size
        self.message = message

    def __call__(self, form, field):
        if not (isinstance(field.data, FileStorage) and field.data):
            return

        file_size = len(field.data.read())
        field.data.seek(0)  # reset cursor position to beginning of file

        if (file_size < self.min_size) or (file_size > self.max_size):
            # the file is too small or too big => validation failure
            raise v.ValidationError(
                self.message
                or field.gettext(
                    "File must be between {min_size} and {max_size} bytes.".format(
                        min_size=self.min_size, max_size=self.max_size
                    )
                )
            )


def register(func):
    """Register a function to generate a WTForm.Field object from
    a mdform.Field object, matching the suffix in the name

    e.g. generate_XYZ will match field objects with type XYZ.

    Parameters
    ----------
    func : callable
        mdform.Field -> wtforms.Field

    Returns
    -------

    """
    t = func.__name__.split("_", 1)[1]
    FORMATTERS[t] = func
    return func


def generate_field(varname, field):
    """Generate a WTForm.Field object from a mdform.Field object
    trying to match one of the registered parsers.

    Parameters
    ----------
    varname : str
    field : mdform.Field

    Returns
    -------
    WTForm.Field
    """
    field = SimpleNamespace(**field)
    try:
        fmt = FORMATTERS[field.type]
    except KeyError:
        return "# Could not find formatter for %s (%s)" % (varname, field.type)

    try:
        s = fmt(field)
    except Exception as ex:
        print("# Could not format %s (%s)\n%s" % (varname, field.type, ex))
        s = generate_dummy(field)

    return s


def generate_fields(fields):
    """Generate all WTForm.fields from a collection of mdform.Fields

    Parameters
    ----------
    fields : Dict[str, mdform.Field]

    Yields
    ------
    WTForm.Field
    """
    for label, field in fields.items():
        yield generate_field(label, field)


def generate_form_cls(name, fields):
    """Generate a FlaskForm derived class with an attribute for each field.
    It also adds a submit button.

    Parameters
    ----------
    name : str
        name of the class
    fields : Dict[str, mdform.Field]
        fields organized by their labels

    Returns
    -------
    FlaskForm
    """
    cls = type(name, (FlaskForm,), {})
    for label, field in fields.items():
        setattr(cls, label, generate_field(label, field))

    setattr(cls, "submit", SubmitField("Submit"))

    return cls


class ReadOnlyFlaskForm(FlaskForm):

    _read_only_attrs = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._read_only_attrs:
            for attr_name in self._read_only_attrs:
                read_only(getattr(self, attr_name))


def generate_read_only_form_cls(name, fields):
    """Generate a Flask derived class that is read-only.

    For this purpose, it overwrite the type certain fields.

    Parameters
    ----------
    name : str
        name of the class
    fields : Dict[str, mdform.Field]
        fields organized by their labels

    Returns
    -------
    FlaskForm

    """
    cls = type(name, (ReadOnlyFlaskForm,), {})
    for label, field in fields.items():
        if field["type"] == "FileField":
            field = {**field, "type": "LinkField"}
        elif field["type"] == "DateField":
            field = {**field, "type": "StringField"}
        elif field["type"] == "TimeField":
            field = {**field, "type": "StringField"}
        elif field["type"] == "DateTimeField":
            field = {**field, "type": "StringField"}
        setattr(cls, label, generate_field(label, field))

    cls._read_only_attrs = tuple(fields.keys())

    return cls


##############
# Generators
##############


def generate_dummy(field):
    return StringField(field.label)


@register
def generate_StringField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    if field.length:
        validators.append(v.length(max=field.length))
    return StringField(field.label, validators=validators)


@register
def generate_TextAreaField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    if field.length:
        validators.append(v.length(max=field.length))
    return TextAreaField(field.label, validators=validators)


@register
def generate_DateField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    return DateField(field.label, validators=validators)  # format='%d/%m/%y',


@register
def generate_TimeField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    return TimeField(field.label, validators=validators)


@register
def generate_EmailField(field):
    validators = [v.Email()]
    if field.required:
        validators.append(v.DataRequired())
    else:
        validators.append(v.Optional())
    return StringField(field.label, validators=validators)


@register
def generate_SelectField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    # if field.length:
    #     validators.append('v.length(max=%d)' % field.length)
    if field.default is None:
        return SelectField(field.label, choices=field.choices, validators=validators)
    else:
        return SelectField(field.label, choices=field.choices, validators=validators)


@register
def generate_RadioField(field):
    validators = []
    if field.required:
        validators.append(v.DataRequired())
    if field.length:
        validators.append(v.length(max=field.length))
    return RadioField(field.label, choices=field.choices, validators=validators)


@register
def generate_FileField(field):
    # TODO: It would be nice to make this pluggable.
    validators = [FileSize(max_size=5 * 1024 * 1024)]
    if field.required:
        validators.append(FileRequired())
    if field.allowed:
        validators.append(
            FileAllowed(field.allowed, field.description or field.allowed)
        )
    return FileField(field.label, validators=validators)


class MyUrlWidget(TextInput):
    def __init__(self):
        super(MyUrlWidget, self).__init__()

    def __call__(self, field, **kwargs):
        html = "<a href='%s' target='_blank'> %s </a>"
        return HTMLString(html % (field._value(), field._value()))


@register
def generate_LinkField(field):
    return StringField(field.label, widget=MyUrlWidget())
