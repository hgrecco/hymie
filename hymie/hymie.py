"""
    hymie.hymie
    ~~~~~~~~~~~

    Internal operation.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import functools
import pathlib
from datetime import datetime

from flask import Flask, url_for
from flask_emails import Message
from flask_uploads import configure_uploads
from markdown import Markdown
from mdform import FormExtension

from . import schema
from .common import BASE_JINJA_ENV, SmartLoader, extract_jinja2_variables, logger
from .forms import generate_form_cls, generate_read_only_form_cls
from .storage import Storage


class FakeMessage(Message):
    """A drop-in replacement for e-mail Message that prints the mail
    to the terminal.
    """

    class Return:
        status_code = 250

    def send(self, smtp=None, **kw):
        print("from: %s" % str(self.mail_from))
        print("to: %s" % kw["to"])
        print("subject: %s" % self.subject)
        print(self.html_body)
        print("-------------------------")
        return self.Return


class Hymie:
    """Hymie

    Parameters
    ----------
    path : str or pathlib.Path
        folder for the Hymie app.
    """

    def __init__(self, path, production=False):
        logger.info(f"Starting Hymie app in {path}")
        self.path = pathlib.Path(path)

        hymie_yaml = self.path.joinpath("hymie.yaml")
        secrets_yaml = self.path.joinpath("secrets.yaml")
        if production:
            extra_yaml = self.path.joinpath("production.yaml")
        else:
            extra_yaml = self.path.joinpath("testing.yaml")

        files = [str(f) for f in (extra_yaml, secrets_yaml, hymie_yaml) if f.exists()]
        mtime = max(
            [
                f.stat().st_mtime
                for f in (extra_yaml, secrets_yaml, hymie_yaml)
                if f.exists()
            ]
        )

        logger.info(f"Loaded app definition from {files}")

        content: schema.Root = schema.Root.from_filenames(files)

        logger.info(f"Loaded app")

        #: Describes
        self.metadata = content.metadata
        self.config = cfg = content.config
        self.endpoints = content.endpoints

        # This dictionary is injected when rendering every template.
        self.template_vars = dict(
            name=content.metadata.name,
            description=content.metadata.description,
            maintainer=content.metadata.maintainer,
            maintainer_email=content.metadata.maintainer_email,
            yaml_timestamp=datetime.fromtimestamp(mtime).strftime("%Y-%m-%d-%H:%M"),
        )

        self.storage = Storage(cfg.storage.path, cfg.storage.salt)
        self.subject_prefix = cfg.email.subject.strip() + " "

        if self.config.email.debug:
            logger.info("Email is in debug mode. Messages will be printed to screen.")
            self.Message = FakeMessage
        else:
            self.Message = Message

        self.friendly_user_id_getter = SmartLoader(
            self.storage, self.metadata.friendly_user_id
        )

    def set_config(self, app):
        cfg = self.config
        app.config["EMAIL_HOST"] = cfg.email.host
        app.config["EMAIL_PORT"] = cfg.email.port
        app.config["EMAIL_USE_TLS"] = cfg.email.use_tls
        app.config["EMAIL_USE_SSL"] = cfg.email.use_ssl
        app.config["EMAIL_TIMEOUT"] = cfg.email.timeout
        app.config["EMAIL_HOST_USER"] = cfg.email.user
        app.config["EMAIL_HOST_PASSWORD"] = cfg.email.password

        app.config["SECRET_KEY"] = cfg.secret.key

    def connect_to_app(self, app):
        self.set_config(app)

        app.config["UPLOADED_FILES_DEST"] = str(self.storage.upload_path)

        configure_uploads(app, self.storage.upload_set)

        app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
        # patch_request_class(
        #     app, 5 * 1024 * 1024
        # )  # set maximum file size, default is 5MB

    def yield_users_state(self):
        if self.metadata.friendly_user_id:
            for uid in self.storage.yield_uids():
                try:
                    try:
                        nuid = self.friendly_user_id_getter(uid)
                    except Exception:
                        nuid = self.storage.user_retrieve_email(uid)
                    yield (
                        uid,
                        nuid,
                        self.storage.user_retrieve_email(uid),
                        *self.storage.user_retrieve_state_timestamp(uid),
                    )
                except Exception as e:
                    logger.log(f"While yield_users_state: {e}")
        else:
            for uid in self.storage.yield_uids():
                try:
                    yield (
                        uid,
                        uid,
                        self.storage.user_retrieve_email(uid),
                        *self.storage.user_retrieve_state_timestamp(uid),
                    )
                except Exception as e:
                    logger.log(f"While yield_users_state: {e}")

    def yield_user_index_for(self, uid):
        # Timestamp, endpoint
        yield from self.storage.user_retrieve_index(uid)

    @functools.lru_cache(maxsize=64)
    def get_email(self, name):
        """Get e-mail template from template name

        Parameters
        ----------
        name : str
            Name of the e-mail template

        Returns
        -------
        dict, jinja2.Template, dict
            attributes of the template, e-mail as jinja2 template, variables (with modifiers) in the template
        """

        mdfile = self.path.joinpath("emails", name)

        with mdfile.open(mode="r", encoding="utf-8") as fi:
            md = Markdown(extensions=["meta"])
            html = md.convert(fi.read())

        variables = extract_jinja2_variables(html)

        return md.Meta, BASE_JINJA_ENV.from_string(html), variables

    @functools.lru_cache(maxsize=64)
    def get_form(self, name, app, read_only=False, extends="form.html"):
        """Get form template from template name.

        Parameters
        ----------
        name : str
            name of form template
        app : flask.Flask
            flask app to use for building the template (important for inheritance).
        read_only : bool (default: Falde)
            If True,
        extends : str
            Base template from which extend. In combination with `app` it can be used for
            template inheritance.

        Returns
        -------
        dict, jinja2.Template, WTForm
            form attributes, form as jinja2 template, form object
        """

        mdfile = self.path.joinpath("forms", name).with_suffix(".md")

        with mdfile.open(mode="r", encoding="utf-8") as fi:
            md = Markdown(extensions=["meta", FormExtension(wtf=True)])
            html = md.convert(fi.read())

        if read_only:
            wtform = generate_read_only_form_cls(name, md.Form)
        else:
            wtform = generate_form_cls(name, md.Form)

        tmpl = ""
        if extends:
            tmpl += '{%- extends "' + extends + '" %}'

        tmpl += "{% block innerform %}"
        tmpl += html
        tmpl += "{% endblock %})"
        if app:
            return md.Meta, app.jinja_env.from_string(tmpl), wtform

        return md.Meta, BASE_JINJA_ENV.from_string(tmpl), wtform

    @functools.lru_cache(maxsize=64)
    def get_page(self, name, app, extends="simple.html"):
        """Get page template from template name.

        Parameters
        ----------
        name : str
            name of form template
        app : flask.Flask
            flask app to use for building the template (important for inheritance).
        extends : str
            Base template from which extend. In combination with `app` it can be used for
            template inheritance.

        Returns
        -------
        dict, jinja2.Template
            form attributes, form as jinja2 template
        """
        mdfile = self.path.joinpath("pages", name).with_suffix(".md")

        with mdfile.open(mode="r", encoding="utf-8") as fi:
            md = Markdown(extensions=["meta"])
            html = md.convert(fi.read())

        tmpl = ""
        if tmpl:
            tmpl += '{%- extends "' + extends + '" %}'

        tmpl += (
            """
        {%- extends "simple.html" %}
        {% block inner_simple %}{{ super() }}
        """
            + html
            + "{% endblock %}"
        )

        if app:
            return md.Meta, app.jinja_env.from_string(tmpl)

        return md.Meta, BASE_JINJA_ENV.from_string(tmpl)

    def convert_email(self, email, uid):
        """Convert e-mail field to e-mail address.

        Certain special values are accepted in the configuration file:
        - "self" -> the e-mail address of the System.
        - "user" -> the mail address registered for the workflow.

        Parameters
        ----------
        email: str
        uid: str

        Returns
        -------
        str
        """
        if email is None:
            return

        _email = email.strip().lower()
        if _email == "self":
            return self.config.email.address
        elif _email == "user":
            return self.storage.user_retrieve_email(uid)

        return email

    def send(self, destination, subject, html, cc=None, bcc=None):
        """Send and e-mail.

        Parameters
        ----------
        destination
        subject
        html
        cc
        bcc

        Returns
        -------

        """

        message = self.Message(
            html=html,
            subject=self.subject_prefix + (subject or ""),
            mail_from=self.config.email.address,
            cc=cc,
            bcc=bcc,
        )

        r = message.send(to=destination)

        if r.status_code not in [
            250,
        ]:
            raise Exception("Message not sent (code %s). Please retry" % r.status_code)

    ##########
    # Actions
    ##########

    # Everything after the first underscored is matched to the key in the actions list.
    # All actions have the same parameters:
    #
    # Parameters
    # ----------
    # app : flask.Flask
    #   the current flask application
    # uid : str
    #   user id of the workflow.
    # endpoint : str
    #   current endpoint to which this action belongs.
    # json_form
    #   submitted form data.
    # action : schema.Action
    #   configuration for this action.
    # render_kwargs
    #   extra values for rendering.

    def action_email_form(
        self,
        app: Flask,
        uid: str,
        endpoint: str,
        json_form: dict,
        action: schema.ActionEmailForm,
        **render_kwargs,
    ):
        """Send a form by e-mail.
        """

        # action_options None

        html = app.jinja_env.get_template("plain_form.html").render(
            form=json_form,
            user_email=self.storage.user_retrieve_email(uid),
            **render_kwargs,
        )

        destination = self.convert_email(action.destination, uid)
        cc = self.convert_email(action.cc, uid)
        bcc = self.convert_email(action.bcc, uid)

        self.send(destination, endpoint, html, cc, bcc)

    def action_email(
        self,
        app: Flask,
        uid: str,
        endpoint: str,
        json_form: dict,
        action: schema.ActionEmail,
        **render_kwargs,
    ):
        """Send an e-mail.
        """

        meta, tmpl, _ = self.get_email(action.template)

        destination = self.convert_email(action.destination, uid)
        cc = self.convert_email(action.cc, uid)
        bcc = self.convert_email(action.bcc, uid)

        kwargs = render_kwargs

        kwargs["form"] = json_form
        kwargs["endpoint"] = endpoint
        kwargs["uid"] = uid
        kwargs["previous"] = self.storage.user_retrieve_all_current(
            uid, skip=[endpoint]
        )
        kwargs["link"] = url_for("view", uid=uid, _external=True)

        # build links
        for k, v in meta.items():
            if not k.startswith("link"):
                continue
            endpoint_name = v[0].strip()
            kwargs[k] = url_for(
                "view",
                uid=uid,
                hcsf=kwargs["hcsf"],
                endpoint_name=endpoint_name,
                _external=True,
            )

        html = tmpl.render(**kwargs)

        subject_tmpl = BASE_JINJA_ENV.from_string(meta.get("subject", [""])[0])
        subject = subject_tmpl.render(**kwargs)

        return self.send(destination, subject, html, cc, bcc)

    ###################
    # Integrity checks
    ###################

    # These functions are used to test the hymie app for posible logic errors
    # before it is served.

    def check_prefixed_variable(self, app, name, variable, known_links):
        if variable.startswith("form."):
            return self.check_variable(app, name + "." + variable[len("form.") :])
        elif variable.startswith("previous."):
            return self.check_variable(app, variable[len("previous.") :])
        elif variable not in known_links:
            return self.check_variable(app, variable)
        else:
            return True

    def integrity_action_base(self, name, app, action):
        errs = []
        for variable in extract_jinja2_variables(action.condition):
            msg = self.check_prefixed_variable(app, name, variable, ())

            if msg is not True:
                errs.append(f"In {name}, the condition {action.condition} {msg}")

        return errs

    def integrity_email_form(self, name, app, action):
        return self.integrity_action_base(name, app, action)

    def integrity_email(self, name, app, action):
        errs = self.integrity_action_base(name, app, action)
        template = action.template
        try:
            email_meta, email_tmpl, email_variables = self.get_email(template)
        except FileNotFoundError:
            errs.append(f"In {name}, e-mail template file not found {template}")
            return errs
        except Exception as e:
            errs.append(f"In {name}, could not get e-mail template {template}: {e}")
            return errs

        # Check subject
        errs.extend(
            f"In {name}, the template {template} " + s
            for s in self.check_str_template(
                app, email_meta.get("subject", "")[0], name
            )
        )

        known_links = set()
        # Check that all the links in the header exists
        for k, v in email_meta.items():
            if not k.startswith("link"):
                continue
            v = v[0].strip()
            known_links.add(k.strip())
            if v not in self.endpoints:
                errs.append(
                    f"In {name}, the template {template} contains a link ({k}) to an unknown endpoint: {v}"
                )

        # Check that all the form and previous fields exist.
        for variable in tuple(email_variables):

            msg = self.check_prefixed_variable(app, name, variable, known_links)

            if msg is not True:
                errs.append(f"In {name}, the template {template} {msg}")

        return errs

    def check_str_template(self, app, html, form_name=None):
        out = []
        for variable in extract_jinja2_variables(html):
            if form_name and variable.startswith("form."):
                msg = self.check_variable(
                    app, form_name + "." + variable[len("form.") :]
                )
            else:
                msg = self.check_variable(app, variable)

            if msg is not True:
                out.append(msg)

        return out

    def check_variable(self, app, form_variable):

        if form_variable in ("link", "form", "previous", "user_email"):
            return True

        if form_variable in self.template_vars:
            return True

        if form_variable in self.endpoints:
            return True

        try:
            form_name, attr_name = form_variable.split(".")
        except Exception:
            raise Exception(f"Could not split {form_variable}")

        try:
            _, _, pwtform = self.get_form(form_name, app)
        except FileNotFoundError:
            return f"refers to an unavailable form: {form_name}"
        except Exception as e:
            return f"could not be loaded. {form_name}: {e}"

        if not hasattr(pwtform, attr_name):
            return f"contains an unknown variable: {form_variable}"

        return True

    def integrity_check(self, app):

        errs = []
        warns = []

        first = self.metadata.first_endpoint
        if first in self.endpoints:
            logger.debug(f"first_endpoint is {first}")
        else:
            logger.error(f"first_endpoint not found: {first}")

        if self.metadata.friendly_user_id:
            errs.extend(
                "In friendly_user_id, " + err
                for err in self.check_str_template(app, self.metadata.friendly_user_id)
            )

        for name, ep in self.endpoints.items():

            if name.startswith("_"):
                errs.append(
                    f"In {name}, endpoint names cannot start with an underscore."
                )

            if ep.form_action:
                try:
                    self.get_form(name, app)
                except FileNotFoundError:
                    errs.append(f"In {name}, form file not found")
                except Exception as e:
                    errs.append(f"In {name}, could not get form: {e}")

                if ep.form_prefill:
                    for k, v in ep.form_prefill:
                        # k is a variable in the form, v is a variable in the previous
                        msg = self.check_variable("form." + k, app)
                        if msg is not True:
                            errs.append(f"In {name}, form_prefill key {msg}")
                        msg = self.check_variable("previous." + v, app)
                        if msg is not True:
                            errs.append(f"In {name}, form_prefill value {msg}")

            for action in ep.actions:
                if isinstance(action, schema.ActionEmailForm):
                    errs.extend(self.integrity_email_form(name, app, action))
                elif isinstance(action, schema.ActionEmail):
                    errs.extend(self.integrity_email(name, app, action))
                else:
                    errs.append(
                        f"In {name}, no integrity check defined for {action.__class__.__name__}"
                    )

            try:
                self.get_page(name, app)
            except FileNotFoundError:
                errs.append(f"In {name}, page file not found")
            except Exception as e:
                warns.append(f"In {name}, could not get page: {e}")

            for cne in ep.conditional_next_state:
                errs.extend(self.check_str_template(app, cne.condition, name))
                if cne.next_state not in self.endpoints:
                    errs.append(
                        f"In {name}, conditional next_state points to an unknown endpoint: {cne.next_state}"
                    )
            next_state = ep.next_state
            if next_state and next_state not in self.endpoints:
                errs.append(
                    f"In {name}, next_state points to an unknown endpoint: {next_state}"
                )

        for e in errs:
            logger.error(e)
        for w in warns:
            logger.warning(w)

        if errs:
            raise Exception("Integrity check not passed")
