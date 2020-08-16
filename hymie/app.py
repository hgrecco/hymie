"""
    hymie.app
    ~~~~~~~~~

    Flask App creation.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

from pathlib import Path

import flask
import flask_bootstrap
from flask import Markup, flash, jsonify, render_template, send_from_directory, url_for
from flask_bootstrap import Bootstrap
from flask_httpauth import HTTPBasicAuth
from flask_wtf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from . import common, schema, storage
from .common import logger
from .hymie import Hymie

flask_bootstrap.__version__ = "4.4.1"
flask_bootstrap.BOOTSTRAP_VERSION = flask_bootstrap.get_bootstrap_version(
    flask_bootstrap.__version__
)


def create_app(path, app=None, production=False):
    """Create or modify a Flask App.

    Parameters
    ----------
    path : str or Path
        The folder containing the `hymie.yaml` file.
    app : Flask App
    production : bool
        indicates if the testing or production yaml file is going to be used.

    Returns
    -------
    Flask App
    """

    hobj = Hymie(path, production)

    if app is None:
        APP = flask.Flask("hymie")
    else:
        APP = app

    # This is just to avoid stupid mistakes.
    del app

    APP.config["BOOTSTRAP_SERVE_LOCAL"] = True
    Bootstrap(APP)

    CSRFProtect(APP)

    APP.config["FLASK_HTPASSWD_PATH"] = str(Path(path).joinpath(".htpasswd"))
    APP.config["FLASK_AUTH_REALM"] = "You are not an administrator yet!"
    auth = HTTPBasicAuth()

    hobj.integrity_check(APP)

    hobj.connect_to_app(APP)

    USERS = {
        "admin": generate_password_hash(hobj.config.secret.admin_password),
    }

    @auth.verify_password
    def verify_password(username, password):
        if username in USERS and check_password_hash(USERS.get(username), password):
            return username

    # try:
    #     import atexit
    #     from uwsgidecorators import timer
    #
    #     # List of tuples: (timestamp, dict destination, cc, bcc, subject, html)
    #     scheduled_emails = hobj.storage.retrieve_scheduled_emails()
    #
    #     def _store_scheduled_emails():
    #         logger.info('Saving scheduled e-mails to disk')
    #         hobj.storage.store_scheduled_emails(scheduled_emails)
    #
    #     atexit.register(_store_scheduled_emails)
    #
    #     @timer(24*60*60)
    #     def daily_timer():
    #         """
    #         """
    #         before_count = len(scheduled_emails)
    #
    #         logger.info('Sending scheduled e-mails. Queued: %d' % before_count)
    #         to_remove = []
    #         now = datetime.now().timestamp()
    #
    #         for ndx, (timestamp, content) in enumerate(scheduled_emails):
    #
    #             if timestamp < now:
    #                 continue
    #
    #             try:
    #                 destination = content['destination']
    #                 hobj.send(destination, content['subject'], content['html'],
    #                           content.get('cc', None), content.get('bcc', None))
    #                 logger.info('e-mail sent to %s' % destination)
    #                 to_remove.append(ndx)
    #             except Exception as ex:
    #                 logger.error('While sending email in timer', ex)
    #
    #         for ndx in reversed(to_remove):
    #             del to_remove[ndx]
    #
    #         after_count = len(scheduled_emails)
    #
    #         if after_count == before_count:
    #             logger.info('No emails were sent')
    #         else:
    #             logger.info('%d scheduled e-mails sent. Queued: %d' % (after_count-before_count, after_count))
    #             _store_scheduled_emails()
    #
    #     daily_timer()
    #
    # except ImportError:
    #     logger.warning('Not running under uwsgi, timer will not be disabled')

    def app_render_template(tmpl, **kwargs):
        """A wrapper for Flask template rendering that can either render a template
        or load it by name and then render it.

        It injects the app metadata.

        Parameters
        ----------
        tmpl : str or Template
        kwargs :
            Additional values to inject for rendering

        Returns
        -------

        """
        kw = {**hobj.template_vars, **kwargs}

        if isinstance(tmpl, str):
            return render_template(tmpl, **kw)

        return tmpl.render(**kw).strip()

    def app_render_template_previous(uid, tmpl, tmpl_vars, **kwargs):
        """A wrapper for Flask template rendering that can either render a template
        or load it by name and then render it.

        It injects the app metadata and previous form valus for uid

        Parameters
        ----------
        tmpl : str or Template
        kwargs :
            Additional values to inject for rendering

        Returns
        -------

        """

        previous = hobj.storage.user_retrieve_current(
            uid, tuple(v.split(".")[1] for v in tmpl_vars if v.startswith("previous.")),
        )

        return app_render_template(tmpl, previous=previous, **kwargs)

    def app_string_render_template(s, **kwargs):
        return app_render_template(common.BASE_JINJA_ENV.from_string(s), **kwargs)

    ####################
    # Common Endpoints
    ####################

    @APP.errorhandler(413)
    def request_entity_too_large(error):
        logger.error(error)
        return app_render_template("toobig.html")
        # flash('Los archivos adjuntos no pueden superar los 5MB cada uno.', 'danger')
        # try:
        #     uid = flask.request.view_args['uid']
        #     endpoint_name = hobj.storage.user_retrieve_state(uid)
        #     return _view(uid, endpoint_name, form_data=flask.request.data)
        # except Exception as e:
        #     logger.error(e)
        #     return flask.redirect(flask.request.full_path)

    @APP.route("/")
    def index():
        """Welcome page.
        """
        _, tmpl, _ = hobj.get_page("start.md", APP)
        return app_render_template(
            tmpl,
            link_register=url_for("register", _external=True),
            link_recover=url_for("recover", _external=True),
        )

    @APP.route("/register", methods=("GET", "POST"))
    def register():
        """Register e-mail address in the system to receive an access link.

        GET
            1. show RegisterForm
        POST
            1. Validate Form
            2. Verify that the e-mail address has not been registered before
            3. Register the e-mail address
            4. Send the access link to the e-mail address
            6. Show a final message.

        If any step fails, form is shown again.
        """

        form = common.RegisterForm()

        if not form.validate_on_submit():
            common.flash_errors(form)
            return app_render_template("register.html", form=form)

        storage = hobj.storage
        email = form.e_mail.data

        if storage.is_registered(email):
            flash(
                Markup(common.MSG_ALREADY_REGISTERED % url_for("recover", email=email)),
                "danger",
            )
            return app_render_template("register.html", form=form)

        try:
            storage.register(email, hobj.metadata.first_state)
        except Exception as ex:
            logger.error("while trying to register an email address", ex)
            flash(common.MSG_ERROR_REGISTERING, "danger")
            return app_render_template("register.html", form=form)

        uid = storage.hash_for(email)
        link = url_for("view", uid=uid, _external=True)

        try:
            hobj.action_email(
                APP,
                uid,
                "register",
                form,
                schema.ActionEmail(dict(template="welcome.md", destination="user",)),
                link=link,
            )
        except Exception as ex:
            logger.error("while trying to send an email", ex)
            flash(common.MSG_ERROR_SENDING, "danger")
            return app_render_template("register.html", form=form)

        return app_render_template(
            "message.html", message=common.MSG_EMAIL_SENT % email
        )

    @APP.route("/recover", methods=("GET", "POST"))
    @APP.route("/recover/<email>", methods=("GET", "POST"))
    def recover(email=None):
        """Recover the access link.

        Parameters
        ----------
        email : str

        """
        form = None

        if email is None:
            form = common.RegisterForm()

            if not form.validate_on_submit():
                common.flash_errors(form)
                return app_render_template(
                    "register.html", form=form, form_title="Recuperá tu clave de acceso"
                )

            email = form.e_mail.data

        uid = hobj.storage.hash_for(email)
        link = url_for("view", uid=uid, _external=True)

        try:
            hobj.action_email(
                APP,
                uid,
                "recover",
                form,
                schema.ActionEmail(dict(template="welcome.md", destination="user",)),
                link=link,
            )
        except Exception as ex:
            logger.error("while trying to send an email", ex)
            flash(common.MSG_ERROR_SENDING, "danger")
            return app_render_template(
                "recover.html", recover_link=url_for("recover", email=email)
            )

        return app_render_template(
            "message.html", message=common.MSG_EMAIL_SENT % email
        )

    @APP.route("/file/<path:fileid>")
    def file(fileid):
        """Download an uploaded file.

        Parameters
        ----------
        fileid : patt

        """

        storage = hobj.storage

        return send_from_directory(directory=str(storage.upload_path), filename=fileid)

    @APP.route("/view/<uid>", methods=("GET", "POST"))
    @APP.route("/view/<uid>/<hcsf>/<state_name>", methods=("GET", "POST"))
    def view(uid, hcsf=None, state_name=None):

        # TODO: Deprecate this in favor of view_state or goto_state

        if state_name is None:
            return view_current_state(uid)

        current_hcsf = hobj.storage.statehash_for(uid)
        if current_hcsf != hcsf:
            return app_render_template(
                "message.html", message=common.MSG_INVALID_UID_HEP
            )
        return admin_view(uid, state_name)

    @APP.route("/view_current_state/<uid>", methods=("GET", "POST"))
    @APP.route("/view_current_state/<uid>/<int:form_number>", methods=("GET", "POST"))
    def view_current_state(uid, form_number=None):
        """Show the current form/page for a given user.

        There are two ways to access an endpoint

        ** Show form ** -> /view/<uid>
        - uid: user identifier
        Displays a list of available forms or the first if only one present at this state.

        ** Show form ** -> /view/<uid>/<form_number>
        - uid: user identifier
        - form_number in multi form state

        GET:
            Display the form
        POST:
            Upload the form

        See `_view` for more details.
        """

        storage = hobj.storage

        try:
            state_name = storage.user_retrieve_state(uid).state
        except FileNotFoundError:
            return app_render_template("message.html", message=common.MSG_INVALID_UID)

        state = hobj.states[state_name]

        if len(state.forms) == 0:
            # No form given, try lo show page
            return _view_page(uid, state_name)

        if len(state.forms) != 1:
            if form_number is None:
                return app_render_template(
                    "form_chooser.html",
                    form_links=state.forms,
                    view_link_for=lambda x: common.view_link_for(uid, x),
                )
            elif form_number >= len(state.forms):
                return app_render_template(
                    "message.html", message=common.MSG_INVALID_UID
                )

        try:
            return _view_form_in_state(uid, state.forms[form_number or 0])
        except RequestEntityTooLarge:
            flash("El límite para los archivos es de 5Mb cada uno", "danger")
            return flask.redirect(url_for("view", uid=uid))
        except Exception as e:
            logger.error(e)
            flash(str(e), "danger")
            return flask.redirect(url_for("view", uid=uid))

    def _view_page(uid, state_name):

        state = hobj.states[state_name]

        if state.page_template:
            _, tmpl, tmpl_vars = hobj.get_page(state.page_template, APP)
            return app_render_template_previous(
                uid, tmpl, tmpl_vars, **state.page_render_kw
            )
        else:
            return app_render_template("message.html", message=common.MSG_NO_FORM_PAGE)

    def _view_form_in_state(uid, fis):
        """Show a hymie endpoint (actual implementation).

        This is tightly coupled to the endpoint definition.

        GET
            1. Retrieve the state for the user.
            2. Show the current form.
        POST
            1. Follow the actions specified for the endpoint.


        Parameters
        ----------
        uid : str
        fis : schema.FormInState

        Returns
        -------

        """

        storage = hobj.storage

        form_name = fis.form
        form_cfg = hobj.forms[form_name]

        meta, tmpl, form_cls, tmpl_vars = hobj.get_form_by_name(form_name, APP)

        kwargs = dict(form_cfg.template_render_kw or {})
        kwargs.update(common.build_links(meta, uid, storage))

        if flask.request.method == "GET":
            # If this is a get request we try to fill the form with:
            # - prefill data
            # - previously filled data
            # - data passed to this funcion
            try:
                stored_form_data = storage.user_retrieve(uid, form_name)
            except FileNotFoundError:
                stored_form_data = {}
            except Exception as e:
                logger.error(f"While trying to user_retrieve({uid}, {form_name}): {e}")
                stored_form_data = {}

            form_obj = form_cls(**stored_form_data)

            return app_render_template_previous(
                uid,
                tmpl,
                tmpl_vars,
                user_email=storage.user_retrieve_email(uid),
                form=form_obj,
                **kwargs,
            )
        else:
            # If this is a post request we just get it
            form_obj = form_cls()

        if not form_obj.validate_on_submit():
            common.flash_errors(form_obj)

            return app_render_template_previous(
                uid,
                tmpl,
                tmpl_vars,
                user_email=storage.user_retrieve_email(uid),
                form=form_obj,
                **kwargs,
            )

        json_form = hobj.storage.form_to_dict(form_obj)

        for condition in fis.conditional_next_state:
            if (
                app_string_render_template(condition.condition, form=json_form)
                == "True"
            ):
                next_state = condition.next_state
                break
        else:
            next_state = fis.next_state

        with storage.maybe_store_state(
            uid, next_state, store_form=(form_name, json_form)
        ) as hcsf:

            for action in form_cfg.on_submit:
                if isinstance(action, schema.Action):

                    # AFAIK there is no **safe** way to evaluate that contains user provided values
                    # a boolean expression in python without a parser.
                    # As jinja already has a parser that is used everywhere, we reuse it here.
                    if (
                        app_string_render_template(action.condition, form=json_form)
                        != "True"
                    ):
                        continue

                    # action(app: FlaskForm, hobj: Hymie, uid: str, endpoint: str, form: dict, action_options: ?):
                    if isinstance(action, schema.ActionEmail):
                        try:
                            hobj.action_email(
                                APP, uid, form_name, json_form, action, hcsf=hcsf
                            )
                        except Exception as e:
                            logger.error(str(e))

                    elif isinstance(action, schema.ActionEmailForm):
                        try:
                            hobj.action_email_form(
                                APP, uid, form_name, json_form, action
                            )
                        except Exception as e:
                            logger.error(str(e))
                    else:
                        raise Exception(
                            "Action not defined for type %s" % action.__class__
                        )
                else:

                    logger.error("Action is not a subclass of Action: %s " % action)

        try:
            _, tmpl, tmpl_vars = hobj.get_page(form_cfg.after_template, APP)
            return app_render_template_previous(
                uid, tmpl, tmpl_vars, **form_cfg.after_render_kw
            )
        except FileNotFoundError:
            return app_render_template("message.html", message="Hecho")

    ####################
    # Admin Endpoints
    ####################

    @APP.route("/admin")
    @auth.login_required
    def admin():
        """Entry point for the administrator interface.
        """
        return flask.redirect(url_for("users"))
        return app_render_template(
            "admin/base.html", crumbs=[("Acceso administrativo", url_for("admin"))]
        )

    @APP.route("/admin/view/<uid>/<state_name>", methods=("GET", "POST"))
    @APP.route(
        "/admin/view/<uid>/<state_name>/<int:form_number>", methods=("GET", "POST")
    )
    @auth.login_required
    def admin_view(uid, state_name, form_number=None):
        """Show a hymie endpoint (start).

        There are two ways to access an endpoint

        ** Show form ** -> /view/<uid>
        - uid: user identifier

        Used by users.

        ** Show form with predefined output ** -> /view/<uid>/<hcsf>/<endpoint_name>
        - uid: user identifier
        - hcsf: hashed state for the user
        - state_name: state to show
        - form_number

        GET:
            Display the form
        POST:
            Upload the form

        Used by others to advance the worklow of a user.

        See `_view` for more details.
        """

        state = hobj.states[state_name]

        try:
            return _view_form_in_state(uid, state.admin_forms[form_number or 0])
        except RequestEntityTooLarge:
            flash("El límite para los archivos es de 5Mb cada uno", "danger")
            return flask.redirect(url_for("view", uid=uid))
        except Exception as e:
            logger.error(e)
            flash(str(e), "danger")
            return flask.redirect(url_for("view", uid=uid))

    @APP.route("/admin/users")
    @auth.login_required
    def users():
        """Display the list of users.
        """
        return app_render_template(
            "admin/users.html",
            crumbs=[
                ("Acceso administrativo", url_for("admin")),
                ("Usuarios", url_for("users")),
            ],
        )

    @APP.route("/admin/users_data")
    @auth.login_required
    def users_data():
        """json list of users.

        Returns
        -------
        json str
        """
        out = []
        for uid, nuid, email, state, timestamp in hobj.yield_users_state():
            out.append(
                (
                    nuid,
                    email,
                    storage.pprint_timestamp(timestamp, locale="es"),
                    state,
                    uid,
                )
            )
        return jsonify(data=out)

    @APP.route("/admin/history/<uid>")
    @APP.route("/admin/history/<uid>/<form_name>/<timestamp>")
    @auth.login_required
    def history(uid, form_name=None, timestamp=None):
        """Display the history for a given user.

        The endpoint and timestamp can be also provided.

        If the timestamp is not given, the most recent for the given endpoint will be shown.
        If the plain_endpoint is also not given, the history for the user will be shown.

        Parameters
        ----------
        uid : str
        form_name : str or None
        timestamp : str or None

        """

        user_email = hobj.storage.user_retrieve_email(uid)

        try:
            fuid = hobj.friendly_user_id_getter(uid)
        except Exception:
            fuid = None

        current_state = hobj.storage.user_retrieve_state(uid)

        # No form name given, show history.

        if form_name is None:
            return app_render_template(
                "/admin/history.html",
                uid=uid,
                friendly_user_id=fuid,
                state=current_state.state,
                timestamp=storage.pprint_timestamp(
                    current_state.timestamp, locale="es"
                ),
                user_email=user_email,
                action_zone=True,
                admin_forms=hobj.states[current_state.state].admin_forms,
                view_admin_link_for=lambda x: common.view_admin_link_for(
                    uid, current_state.state, x
                ),
                crumbs=[
                    ("Acceso administrativo", url_for("admin")),
                    ("Usuarios", url_for("users")),
                    ("Historial de " + user_email, url_for("history", uid=uid)),
                ],
            )

        # Form name was given, show it.

        if timestamp is None:
            # Get last form submission
            content = hobj.storage.user_retrieve(uid, form_name)
            timestamp = content["_hymie_timestamp"]
        else:
            content = hobj.storage.user_retrieve(uid, form_name + "_" + timestamp)

        form_dated_tuple = (form_name, timestamp)

        tmpl_vars = set()
        if {"_hymie_endpoint", "_hymie_timestamp"} != set(content.keys()):
            try:
                meta, tmpl, form_cls, tmpl_vars = hobj.get_form_by_name(
                    form_name, APP, read_only=True, extends="/admin/display_form.html"
                )
                form_obj = form_cls(**content)
            except Exception:
                tmpl = "/admin/noform.html"
                form_obj = None
        else:
            tmpl = "/admin/display_form_no_data.html"
            form_obj = None

        return app_render_template_previous(
            uid,
            tmpl,
            tmpl_vars,
            form=form_obj,
            friendly_user_id=fuid,
            endpoint=form_name,
            timestamp=storage.pprint_timestamp(timestamp, locale="es"),
            user_email=hobj.storage.user_retrieve_email(uid),
            action_zone=(form_dated_tuple == current_state.form_dated_tuple),
            admin_forms=hobj.states[current_state.state].admin_forms,
            view_admin_link_for=lambda x: common.view_admin_link_for(
                uid, current_state.state, x
            ),
            crumbs=[
                ("Acceso administrativo", url_for("admin")),
                ("Usuarios", url_for("users")),
                ("Historial de " + user_email, url_for("history", uid=uid)),
                (
                    "Formulario `%s` (%s)" % (form_name, timestamp),
                    url_for(
                        "history",
                        uid=uid,
                        plain_endpoint=form_name,
                        timestamp=timestamp,
                    ),
                ),
            ],
        )

    @APP.route("/admin/history_data/<uid>")
    @auth.login_required
    def history_data(uid):
        """json state history for a given uid.

        Parameters
        ----------
        uid : str

        Returns
        -------
        json str
        """

        out = []
        previous = None
        history = hobj.storage.user_retrieve_state_history(uid)
        for timestamp in sorted(history.keys()):
            state = history[timestamp]
            dt = storage.timestamp_to_datetime(timestamp)
            if previous is None:
                previous = storage.timestamp_to_datetime(timestamp)
                extra = ""
            else:
                delta = dt - previous
                previous = dt
                extra = " (+%d dias)" % int(delta.days)
            out.append((dt.format() + extra, state.state, state.form_dated_tuple))
        return jsonify(data=out)

    @APP.route("/endpoint_descriptions")
    def endpoint_descriptions():
        """List of endpoints and their descriptions.

        Returns
        -------
        json str
        """
        return jsonify({k: v.description for k, v in hobj.states.items()})

    return APP
