"""
    hymie.schema
    ~~~~~~~~~~~~

    Schema for the hymie.yaml file

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""


from typing import Dict, List, Optional

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
    first_endpoint: str
    friendly_user_id: Optional[str] = ""


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


class Storage(DataStruct):
    path: str
    salt: str


class Config(DataStruct):
    email: Email
    secret: Secret
    storage: Storage


class ActionEmailForm(DataStruct):
    destination: SpecialEmail
    cc: Optional[SpecialEmail] = None
    bcc: Optional[SpecialEmail] = None


class ActionEmail(ActionEmailForm):
    template: str


class Actions(KeyDefinedValue):
    content = {
        "email_form": ActionEmailForm,
        "email": ActionEmail,
    }


class Link(DataStruct):
    text: str
    endpoint: str
    type: validators.value_in("accept", "reject", "info") = "info"
    tooltip: str = ""


class Endpoint(DataStruct):
    description: str
    form_action: validators.value_in(None, "store", "show") = None
    form_prefill: Optional[Dict] = None
    actions: List[Actions] = []
    next_state: Optional[str] = None
    admin_links: List[Link] = []


class Root(DataStruct):
    metadata: Metadata
    config: Config
    endpoints: Dict[str, Endpoint]
