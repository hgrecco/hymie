"""
    hymie.schema
    ~~~~~~~~~~~~

    Schema for the hymie.yaml file

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""


from typing import Dict, List

from datastruct import DataStruct, validators
from datastruct.ds import KeyDefinedValue


class SpecialEmail(validators.Email):
    @classmethod
    def validate(cls, instance):
        if instance in ("self", "user"):
            return True
        return super().validate(instance)


class Metadata(DataStruct):
    name: str
    description: str
    maintainer: str
    maintainer_email: validators.Email
    first_state: str
    friendly_user_id: str = ""


class Email(DataStruct):
    address: str
    host: str
    port: int
    use_tls: bool
    use_ssl: bool
    user: str
    password: str
    timeout: int
    subject: str
    debug: bool = False


class Secret(DataStruct):
    key: str
    admin_password: str


class Storage(DataStruct):
    path: str
    salt: str


class Config(DataStruct):
    email: Email
    secret: Secret
    storage: Storage
    logfile: str = None


class Action(DataStruct):
    condition: str = "True"


class ActionBaseEmail(Action):
    destination: SpecialEmail
    cc: SpecialEmail = None
    bcc: SpecialEmail = None


class ActionEmailForm(ActionBaseEmail):
    pass


class ActionEmail(ActionBaseEmail):
    template: str


class AnyAction(KeyDefinedValue):
    content = {
        "email_form": ActionEmailForm,
        "email": ActionEmail,
    }


class Link(DataStruct):
    text: str
    endpoint: str
    type: validators.value_in("accept", "reject", "info") = "info"
    tooltip: str = ""


class ConditionalNextState(DataStruct):
    condition: str
    next_state: str


class FormInState(DataStruct):
    form: str
    button_text: str = ""
    button_tooltip: str = ""
    button_type: str = ""
    next_state: str
    conditional_next_state: List[ConditionalNextState] = []


class State(DataStruct):
    description: str
    forms: List[FormInState] = []
    admin_forms: List[FormInState] = []
    page_template: str = ""
    page_render_kw: Dict[str, str] = {}


class Form(DataStruct):
    description: str
    template: str = ""
    template_render_kw: Dict[str, str] = {}
    on_submit: List[AnyAction] = []
    after_template: str
    after_render_kw: Dict[str, str] = {}


class Root(DataStruct):
    metadata: Metadata
    config: Config
    states: Dict[str, State]
    forms: Dict[str, Form]
