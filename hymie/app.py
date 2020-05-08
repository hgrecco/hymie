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
from flask_htpasswd import HtPasswdAuth
from flask_wtf import CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge

from . import common, schema, storage
from .common import logger
from .hymie import Hymie

flask_bootstrap.__version__ = "4.4.1"
flask_bootstrap.BOOTSTRAP_VERSION = flask_bootstrap.get_bootstrap_version(
    flask_bootstrap.__version__
)


def view_link_for(storage, uid, endpoint_name):
    """Create a link for an endpoint with predefined output.

    Parameters
    ----------
    storage : storage.Storage
    uid : str
    endpoint_name : str

    Returns
    -------
    str
    """
    return url_for(
        "view",
        uid=uid,
        hcsf=storage.statehash_for(uid),
        endpoint_name=endpoint_name,
        _external=True,
    )


def create_app(path, app=None):
    """Create or modify a Flask App.

    Parameters
    ----------
    path : str or Path
        The folder containing the `hymie.yaml` file.
    app : Flask App

    Returns
    -------
    Flask App
    """

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
    htpasswd = HtPasswdAuth(APP)

    hobj = Hymie(path)

    hobj.integrity_check(APP)

    hobj.connect_to_app(APP)

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

        return tmpl.render(**kw)

    ####################
    # Common Endpoints
    ####################

    @APP.errorhandler(413)
    def request_entity_too_large(error):
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
        meta, tmpl = hobj.get_page("start", APP)
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
            storage.register(email, hobj.metadata.first_endpoint)
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
    @APP.route("/view/<uid>/<hcsf>/<endpoint_name>", methods=("GET", "POST"))
    def view(uid, hcsf=None, endpoint_name=None):
        """Show a hymie endpoint (start).

        There are two ways to access an endpoint

        ** Show form ** -> /view/<uid>
        - uid: user identifier

        Used by users.

        ** Show form with predefined output ** -> /view/<uid>/<hcsf>/<endpoint_name>
        - uid: user identifier
        - hcsf: hashed state for the user
        - endpoint_name: next endpoint

        GET:
            Display the form
        POST:
            Upload the form

        Used by others to advance the worklow of a user.

        See `_view` for more details.
        """

        storage = hobj.storage

        if endpoint_name is None:
            try:
                endpoint_name = storage.user_retrieve_state(uid)
            except FileNotFoundError:
                return app_render_template(
                    "message.html", message=common.MSG_INVALID_UID
                )
        else:
            current_hcsf = storage.statehash_for(uid)
            if current_hcsf != hcsf:
                return app_render_template(
                    "message.html", message=common.MSG_INVALID_UID_HEP
                )

        try:
            return _view(uid, endpoint_name)
        except RequestEntityTooLarge:
            flash("El límite para los archivos es de 5Mb cada uno", "danger")
            return flask.redirect(url_for("view", uid=uid))
        except Exception as e:
            logger.error(e)
            flash(str(e), "danger")
            return flask.redirect(url_for("view", uid=uid))

    def _view(uid, endpoint_name, form_data=None):
        """Show a hymie endpoint (actual implementation).

        This is tightly coupled to the endpoint definition.

        GET
            1. Retrieve the state for the user.
            2. Show the current form.
        POST
            1. Follow the actions specified for the endpoint.


        Parameters
        ----------
        uid
        endpoint_name
        form_data

        Returns
        -------

        """

        storage = hobj.storage

        ep = hobj.endpoints[endpoint_name]
        form_action = ep.form_action

        json_form = None
        if form_action is None:
            # if there is not form action we store the current endpoint as new state
            # just to reference the transition
            with storage.maybe_store_state(uid, endpoint_name) as hcsf:
                hobj.storage.user_store(
                    uid, endpoint_name, {"_hymie_operator": "admin"}
                )

        else:

            meta, tmpl, form_cls = hobj.get_form(endpoint_name, APP)

            prefill = dict(ep.form_prefill or {})
            form_data = form_data or {}

            for k, v in prefill.items():
                prefill_endpoint, key = v.split(".")
                prefill[k] = storage.user_retrieve(uid, prefill_endpoint)[key]

            if flask.request.method == "GET":
                try:
                    content = storage.user_retrieve(uid, endpoint_name)
                    form = form_cls(**{**prefill, **content, **form_data})
                except FileNotFoundError:
                    form = form_cls(**prefill, **form_data)
                except Exception as e:
                    logger.error(
                        f"While trying to user_retrieve({uid}, {endpoint_name}): {e}"
                    )
                    form = form_cls(**prefill, **form_data)
            else:
                form = form_cls(**form_data)

            if not form.validate_on_submit():
                common.flash_errors(form)

                # build links
                kwargs = {}
                for k, v in meta.items():
                    if not k.startswith("link"):
                        continue
                    endpoint_name = v[0].strip()
                    kwargs[k] = view_link_for(storage, uid, endpoint_name)

                return app_render_template(
                    tmpl,
                    user_email=storage.user_retrieve_email(uid),
                    form=form,
                    **kwargs,
                )

            if form_action == "store":
                json_form = hobj.storage.form_to_dict(form)
                hobj.storage.user_store(uid, endpoint_name, json_form)

        with storage.maybe_store_state(uid, ep.next_state) as hcsf:

            for action in ep.actions:

                # action(app: FlaskForm, hobj: Hymie, uid: str, endpoint: str, form: dict, action_options: ?):
                if isinstance(action, schema.ActionEmail):
                    hobj.action_email(
                        APP, uid, endpoint_name, json_form, action, hcsf=hcsf
                    )

                elif isinstance(action, schema.ActionEmailForm):
                    hobj.action_email_form(APP, uid, endpoint_name, json_form, action)

                else:
                    raise Exception("Action not defined for type %s" % action.__class__)

        try:
            meta, tmpl = hobj.get_page(endpoint_name, APP)
            return app_render_template(tmpl)
        except FileNotFoundError:
            return app_render_template("message.html", message="Hecho")

    ####################
    # Admin Endpoints
    ####################

    @APP.route("/admin")
    @htpasswd.required
    def admin(user):
        """Entry point for the administrator interface.

        Parameters
        ----------
        user : str
            current logged user through htpasswd.

        """
        return flask.redirect(url_for("users"))
        return app_render_template(
            "admin/base.html", crumbs=[("Acceso administrativo", url_for("admin"))]
        )

    @APP.route("/admin/users")
    @htpasswd.required
    def users(user):
        """Display the list of users.

        Parameters
        ----------
        user : str
            current logged user through htpasswd.

        """
        return app_render_template(
            "admin/users.html",
            crumbs=[
                ("Acceso administrativo", url_for("admin")),
                ("Usuarios", url_for("users")),
            ],
        )

    @APP.route("/admin/users_data")
    @htpasswd.required
    def users_data(user):
        """json list of users.

        Parameters
        ----------
        user : str
            current logged user through htpasswd.

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
    @APP.route("/admin/history/<uid>/<plain_endpoint>/<timestamp>")
    @htpasswd.required
    def history(user, uid, plain_endpoint=None, timestamp=None):
        """Display the history for a given user.

        The endpoint and timestamp can be also provided.

        If the timestamp is not given, the most recent for the given endpoint will be shown.
        If the plain_endpoint is also not given, the history for the user will be shown.

        Parameters
        ----------
        user : str
            current logged user through htpasswd.
        uid : str
        plain_endpoint : str or None
        timestamp : str or None

        """

        user_email = hobj.storage.user_retrieve_email(uid)

        try:
            fuid = hobj.friendly_user_id_getter(uid)
        except Exception:
            fuid = None

        (
            current_state,
            current_timestamp,
            current_origin,
        ) = hobj.storage.user_retrieve_state_timestamp_origin(uid)

        if plain_endpoint is None:
            return app_render_template(
                "/admin/history.html",
                uid=uid,
                friendly_user_id=fuid,
                state=current_state,
                timestamp=storage.pprint_timestamp(current_timestamp, locale="es"),
                user_email=user_email,
                action_zone=True,
                admin_links=hobj.endpoints[current_state].admin_links,
                view_link_for=lambda x: view_link_for(hobj.storage, uid, x),
                crumbs=[
                    ("Acceso administrativo", url_for("admin")),
                    ("Usuarios", url_for("users")),
                    ("Historial de " + user_email, url_for("history", uid=uid)),
                ],
            )

        if timestamp is None:
            content = hobj.storage.user_retrieve(uid, plain_endpoint)
            timestamp = content["_hymie_timestamp"]
        else:
            dated_endpoint = plain_endpoint + "_" + timestamp
            content = hobj.storage.user_retrieve(uid, dated_endpoint)

        try:
            meta, tmpl, form_cls = hobj.get_form(
                plain_endpoint, APP, read_only=True, extends="/admin/display_form.html"
            )
            form = form_cls(**content)
        except Exception:
            tmpl = "/admin/noform.html"
            form = None

        return app_render_template(
            tmpl,
            form=form,
            friendly_user_id=fuid,
            endpoint=plain_endpoint,
            timestamp=storage.pprint_timestamp(timestamp, locale="es"),
            user_email=hobj.storage.user_retrieve_email(uid),
            action_zone=((plain_endpoint, timestamp) == current_origin),
            admin_links=hobj.endpoints[current_state].admin_links,
            view_link_for=lambda x: view_link_for(hobj.storage, uid, x),
            crumbs=[
                ("Acceso administrativo", url_for("admin")),
                ("Usuarios", url_for("users")),
                ("Historial de " + user_email, url_for("history", uid=uid)),
                (
                    "Formulario `%s`" % plain_endpoint,
                    url_for(
                        "history",
                        uid=uid,
                        plain_endpoint=plain_endpoint,
                        timestamp=timestamp,
                    ),
                ),
            ],
        )

    @APP.route("/admin/history_data/<uid>")
    @htpasswd.required
    def history_data(user, uid):
        """json state history for a given uid.

        Parameters
        ----------
        user : str
            current logged user through htpasswd.
        uid : str

        Returns
        -------
        json str
        """

        out = []
        previous = None
        for timestamp, endpoint in hobj.yield_user_index_for(uid):
            dt = storage.timestamp_to_datetime(timestamp)
            if previous is None:
                previous = storage.timestamp_to_datetime(timestamp)
                extra = ""
            else:
                delta = dt - previous
                previous = dt
                extra = " (+%d dias)" % int(delta.days)
            out.append((dt.format() + extra, endpoint, (endpoint, timestamp)))
        return jsonify(data=out)

    @APP.route("/endpoint_descriptions")
    def endpoint_descriptions():
        """List of endpoints and their descriptions.

        Returns
        -------
        json str
        """
        return jsonify({k: v.description for k, v in hobj.endpoints.items()})

    return APP
