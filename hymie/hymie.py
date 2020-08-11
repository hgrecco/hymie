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
from typing import Dict

from flask import Flask, url_for
from flask_emails import Message
from flask_uploads import configure_uploads
from markdown import Markdown
from mdform import FormExtension

from . import common, schema
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
        self.metadata: schema.Metadata = content.metadata
        self.config: schema.Config = content.config
        self.states: Dict[str, schema.State] = content.states
        self.forms: Dict[str, schema.Form] = content.forms

        # This dictionary is injected when rendering every template.
        self.template_vars = dict(
            name=content.metadata.name,
            description=content.metadata.description,
            maintainer=content.metadata.maintainer,
            maintainer_email=content.metadata.maintainer_email,
            yaml_timestamp=datetime.fromtimestamp(mtime).strftime("%Y-%m-%d-%H:%M"),
        )

        self.storage = Storage(self.config.storage.path, self.config.storage.salt)
        self.subject_prefix = self.config.email.subject.strip() + " "

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

                    state = self.storage.user_retrieve_state(uid)
                    yield (
                        uid,
                        nuid,
                        self.storage.user_retrieve_email(uid),
                        state.state,
                        state.timestamp,
                    )
                except Exception as e:
                    logger.exception(f"While yield_users_state: {e}")
        else:
            for uid in self.storage.yield_uids():
                try:
                    state = self.storage.user_retrieve_state(uid)
                    yield (
                        uid,
                        uid,
                        self.storage.user_retrieve_email(uid),
                        state.state,
                        state.timestamp,
                    )
                except Exception as e:
                    logger.exception(f"While yield_users_state: {e}")

    def yield_user_index_for(self, uid):
        # Timestamp, endpoint
        yield from self.storage.user_retrieve_index(uid)

    @functools.lru_cache(maxsize=64)
    def get_email(self, template_filename):
        """Get e-mail template from template name

        Parameters
        ----------
        template_filename : str
            Name of the e-mail template

        Returns
        -------
        dict, jinja2.Template, dict
            attributes of the template, e-mail as jinja2 template, variables (with modifiers) in the template
        """

        mdfile = self.path.joinpath("emails", template_filename)

        with mdfile.open(mode="r", encoding="utf-8") as fi:
            md = Markdown(extensions=["meta"])
            html = md.convert(fi.read())

        variables = extract_jinja2_variables(html)

        return md.Meta, BASE_JINJA_ENV.from_string(html), variables

    def get_form_by_name(self, name, app, read_only=False, extends="form.html"):
        template = self.forms[name].template or (name + ".md")
        return self.get_form(template, app, read_only, extends)

    @functools.lru_cache(maxsize=64)
    def get_form(self, template_filename, app, read_only=False, extends="form.html"):
        """Get form template from template name.

        Parameters
        ----------
        template_filename : str
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
        dict, jinja2.Template, WTForm, set
            form attributes, form as jinja2 template, form object, jinja2 variables
        """

        mdfile = self.path.joinpath("forms", template_filename)

        with mdfile.open(mode="r", encoding="utf-8") as fi:
            md = Markdown(extensions=["meta", FormExtension(wtf=True)])
            html = md.convert(fi.read())

        if read_only:
            wtform = generate_read_only_form_cls(template_filename, md.Form)
        else:
            wtform = generate_form_cls(template_filename, md.Form)

        tmpl = ""
        if extends:
            tmpl += '{%- extends "' + extends + '" %}'

        tmpl += "{% block innerform %}"
        tmpl += html
        tmpl += "{% endblock %})"

        if app:
            return (
                md.Meta,
                app.jinja_env.from_string(tmpl),
                wtform,
                extract_jinja2_variables(html),
            )

        return (
            md.Meta,
            BASE_JINJA_ENV.from_string(tmpl),
            wtform,
            extract_jinja2_variables(html),
        )

    @functools.lru_cache(maxsize=64)
    def get_page(self, template_filename, app, extends="simple.html"):
        """Get page template from template name.

        Parameters
        ----------
        template_filename : str
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
        mdfile = self.path.joinpath("pages", template_filename)

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
            return (
                md.Meta,
                app.jinja_env.from_string(tmpl),
                extract_jinja2_variables(html),
            )

        return md.Meta, BASE_JINJA_ENV.from_string(tmpl), extract_jinja2_variables(html)

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
            raise Exception(
                "Message not sent (code %s). Please retry\n\n"
                "%s" % (r.status_code, message.as_string())
            )

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
        form_name: str,
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

        self.send(destination, form_name, html, cc, bcc)

    def action_email(
        self,
        app: Flask,
        uid: str,
        form_name: str,
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
        kwargs["form_name"] = form_name
        kwargs["uid"] = uid
        kwargs["previous"] = self.storage.user_retrieve_all_current(
            uid, skip=[form_name]
        )
        kwargs["previous"][form_name] = json_form
        kwargs["link"] = url_for("view", uid=uid, _external=True)

        # build links
        kwargs.update(common.build_links(meta, uid, self.storage))

        html = tmpl.render(**kwargs)

        subject_tmpl = BASE_JINJA_ENV.from_string(meta.get("subject", [""])[0])
        subject = subject_tmpl.render(**kwargs)

        return self.send(destination, subject, html, cc, bcc)

    ###################
    # Integrity checks
    ###################

    # These functions are used to test the hymie app for posible logic errors
    # before it is served.

    def check_prefixed_variable(self, app, form_name, variable, known_links):
        if form_name and variable.startswith("form."):
            return self.check_variable(app, form_name + "." + variable[len("form.") :])
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
                errs.append(f"the condition {action.condition} {msg}")

        return errs

    def integrity_email_form(self, name, app, action):
        return self.integrity_action_base(name, app, action)

    def integrity_email(self, name, app, action):
        errs = self.integrity_action_base(name, app, action)
        template = action.template
        try:
            email_meta, email_tmpl, email_variables = self.get_email(template)
        except FileNotFoundError:
            errs.append(f"the e-mail template file not found '{template}'")
            return errs
        except Exception as e:
            errs.append(f"could not get e-mail template '{template}': {e}")
            return errs

        # Check subject
        errs.extend(
            f"the e-mail template '{template}' " + s
            for s in self.check_str_template(
                app, email_meta.get("subject", "")[0], name
            )
        )

        # Check that all the links in the header exists

        def _view_link_for(storage, uid, endpoint_name):
            if endpoint_name not in self.states:
                errs.append(
                    f"the e-mail template '{template}' contains a link to an unknown state: {endpoint_name}"
                )

        def _view_admin_link_for(uid, state_name, form_number=None):
            if state_name not in self.states:
                errs.append(
                    f"the e-mail template '{template}' contains a link to an unknown form: {state_name}"
                )
            if form_number is not None and form_number >= len(
                self.states[state_name].admin_forms
            ):
                errs.append(
                    f"the e-mail template '{template}' contains a link to an unknown form_number: {form_number} in {state_name}"
                )

        known_links = set(
            common.build_links(
                email_meta, None, None, _view_link_for, _view_admin_link_for
            ).keys()
        )

        # Check that all the form and previous fields exist.
        for variable in tuple(email_variables):

            msg = self.check_prefixed_variable(app, name, variable, known_links)

            if msg is not True:
                errs.append(f"the e-mail template '{template}' {msg}")

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

        if form_variable.startswith("wtf"):
            return True

        if form_variable in ("link", "form", "previous", "user_email"):
            return True

        if form_variable in self.template_vars:
            return True

        if form_variable in self.forms:
            return True

        try:
            form_name, attr_name = form_variable.split(".")
        except Exception:
            raise Exception(f"Could not split '{form_variable}'")

        try:
            _, _, pwtform, _ = self.get_form_by_name(form_name, app)
        except FileNotFoundError:
            return f"refers to an unavailable form: {form_name}"
        except Exception as e:
            return f"could not be loaded. {form_name}: {e}"

        if not hasattr(pwtform, attr_name):
            return f"contains an unknown variable: '{form_variable}'"

        return True

    def integrity_page_check(self, app, template, prefill, form_name=None):

        errs = []

        try:
            _, tmpl, tmpl_vars = self.get_page(template, app)
            tmp = (
                self.check_prefixed_variable(app, form_name, tmpl_var, ())
                for tmpl_var in tmpl_vars
                if tmpl_var not in prefill
            )
            errs.extend(f"the after_page " + s for s in tmp if s is not True)

            errs.extend(
                f"page_render_kw key '{k}' is not in template '{template}'"
                for k in prefill.keys()
                if k not in tmpl_vars
            )

        except FileNotFoundError:
            errs.append(f"page file '{template}'  not found")
        except Exception as e:
            errs.append(f"could not get page: {e}")

        return errs

    def integrity_check(self, app):

        errs = []
        warns = []

        first = self.metadata.first_state
        if first in self.states:
            logger.debug(f"first_state is '{first}'")
        else:
            errs.append(f"first_state not found: '{first}'")

        if self.metadata.friendly_user_id:
            errs.extend(
                "In friendly_user_id, " + err
                for err in self.check_str_template(app, self.metadata.friendly_user_id)
            )

        for name, state in self.states.items():

            err_prefix = f"In state '{name}',"

            if name.startswith("_"):
                errs.append(
                    f"{err_prefix} state names cannot start with an underscore."
                )

            if state.page_template:
                errs.extend(
                    f"{err_prefix} " + s
                    for s in self.integrity_page_check(
                        app, state.page_template, state.page_render_kw
                    )
                )

            for fis in state.forms + state.admin_forms:

                if fis.form not in self.forms:
                    errs.append(f"{err_prefix} the form {fis.form} is not in forms")
                    continue

                for cne in fis.conditional_next_state:
                    errs.extend(
                        (
                            f"{err_prefix} condition " + s
                            for s in self.check_str_template(
                                app, cne.condition, fis.form
                            )
                        )
                    )
                    if cne.next_state not in self.states:
                        errs.append(
                            f"{err_prefix} conditional next_state points to an unknown state: {cne.next_state}"
                        )

                next_state = fis.next_state
                if next_state and next_state not in self.states:
                    errs.append(
                        f"{err_prefix} next_state points to an unknown state: {next_state}"
                    )

        for name, form in self.forms.items():

            err_prefix = f"In form '{name}',"

            if name.startswith("_"):
                errs.append(f"{err_prefix} form names cannot start with an underscore.")

            try:
                _, tmpl, _, tmpl_vars = self.get_form_by_name(name, app)
                tmp = (
                    self.check_prefixed_variable(app, name, tmpl_var, ())
                    for tmpl_var in tmpl_vars
                    if tmpl_var not in form.template_render_kw
                )
                errs.extend(f"{err_prefix} the form " + s for s in tmp if s is not True)

                for k in form.template_render_kw.keys():
                    if k not in tmpl_vars:
                        errs.append(
                            f"{err_prefix} template_render_kw key '{k}' is not in template '{form.template}'"
                        )

            except FileNotFoundError:
                errs.append(f"{err_prefix} form file '{form.template}' not found")
            except Exception as e:
                errs.append(f"{err_prefix} could not get form: {e}")

            for action in form.on_submit:
                if isinstance(action, schema.ActionEmailForm):
                    errs.extend(
                        f"{err_prefix} " + s
                        for s in self.integrity_email_form(name, app, action)
                    )
                elif isinstance(action, schema.ActionEmail):
                    errs.extend(
                        f"{err_prefix} " + s
                        for s in self.integrity_email(name, app, action)
                    )
                else:
                    errs.append(
                        f"{err_prefix} no integrity check defined for {action.__class__.__name__}"
                    )

            errs.extend(
                f"{err_prefix} " + s
                for s in self.integrity_page_check(
                    app, form.after_template, form.after_render_kw, name
                )
            )

        for e in errs:
            logger.error(e)
        for w in warns:
            logger.warning(w)

        if errs:
            raise Exception("Integrity check not passed")
