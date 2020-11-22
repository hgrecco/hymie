"""
    hymie.storage
    ~~~~~~~~~~~~~

    A simple, file-based key-value based storage with a file upload space.

    :copyright: 2020 by hymie Authors, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""

import contextlib
import functools
import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Tuple

import arrow
from flask import url_for
from flask_uploads import UploadSet


def split_endpoint_timestamp(file):
    """Split a file into the endpoint and timestamp part.

    Parameters
    ----------
    file : pathlib.Path
        Can be a dated file or a link.

    Returns
    -------
    str, str
        endpoint name and timestamp
    """
    endpoint, date, time = file.resolve().stem.rsplit("_", 2)
    return endpoint, date + "_" + time


def datetime_to_timestamp(dt=None):
    """Convert a datetime to a timestamp string.

    Parameters
    ----------
    dt : datetime (defaults to now)

    Returns
    -------
    str
    """
    if dt is None:
        dt = arrow.now()
    return dt.strftime("%Y%m%d_%H%M%S")


def timestamp_to_datetime(ts):
    """Convert a timestamp string into an arrow datetime object.

    Parameters
    ----------
    ts : str

    Returns
    -------
    arrow.Arrow
    """
    return arrow.get(ts, "YYYYMMDD_HHmmss")


def pprint_timestamp(timestamp, locale="en_us"):
    """Pretty print timestamp

    Parameters
    ----------
    timestamp : str
    locale : str

    Returns
    -------
    str
    """
    dt = timestamp_to_datetime(timestamp)
    return dt.format(fmt="YYYY-MM-DD HH:mm") + " (%s) " % dt.humanize(locale=locale)


def _retrieve(json_file):
    """Read json file from disk into dict.

    In addition the to the actual content, the plain endpoint and timestamp are added.

    Parameters
    ----------
    json_file : pathlib.Path

    Returns
    -------
    dict
    """

    with json_file.open("r", encoding="utf-8") as fi:
        content = json.load(fi)

    endpoint, timestamp = split_endpoint_timestamp(json_file)
    content["_hymie_endpoint"] = endpoint
    content["_hymie_timestamp"] = timestamp
    return content


def _store(json_file, data):
    """Store dict into a json file in dict.

    Parameters
    ----------
    json_file : pathlib.Path
    data : dict
    """
    with json_file.open("w", encoding="utf-8") as fo:
        json.dump(data, fo)


# {"state": "plan_en_evaluacion", "origin": ["plan_pendiente", "20200527_094911"], "form_dated_file": ["plan", "20200527_095607"]}
@dataclass
class State:
    """State
    """

    state: str

    #: current timestamp
    timestamp: str

    #: previous state and timestamp
    origin_dated_tuple: Tuple[str, str]

    #: previous
    form_dated_tuple: Tuple[str, str]

    @classmethod
    def from_hymie_dict(cls, d):
        if d["form_dated_tuple"]:
            fdt = tuple(d["form_dated_tuple"])
        else:
            fdt = None
        return cls(
            state=d["state"],
            timestamp=d["_hymie_timestamp"],
            origin_dated_tuple=tuple(d["origin"]),
            form_dated_tuple=fdt,
        )


class Storage:
    """A file based storage backend for Hymie.

    Within a folder specified in `path`, a folder for each user is created.
    All information is stored as json files.

    Users are identified only by their e-mail. A hashed version of their e-mail
    using the salt parameter (referred in the code as *uid*) is used to create
    a unique folder for each user.

    All operations, except the registration step, require using the uid to
    identify the user.

    Files are named as `<endpoint>_<timestamp>.json` and are referred in
    the code as *dated files*.

    Multiple dated files for the same plain endpoint are possible.

    A symlink pointing to the most recent dated file is created for each endpoint.

    Endpoints controlled by the system are prefixed with an underscore ('_'). Two
    of these exist:
        1. _email: indicates the e-mail address for this hash.
        2. _state: indicates the current state for this user.

    For a large base of active users database backend is suggested.
    """

    def __init__(self, path, salt):

        #: Root path for the storage backend.
        self.path = pathlib.Path(path)

        #: Path to keep the uploaded files.
        self.upload_path = self.path.joinpath("uploads")

        #: We create the folders (if necessary)
        self.path.mkdir(parents=True, exist_ok=True)
        self.upload_path.mkdir(parents=True, exist_ok=True)

        salt_file = self.path.joinpath("salt.txt")
        if salt_file.exists():
            if salt_file.read_text(encoding="utf-8") != salt:
                raise Exception(
                    "The salt value for the current storage does not match the provided value."
                )
        else:
            salt_file.write_text(salt, encoding="utf-8")

        # We create an empty file just to see that we have write privileges
        # to these folders
        self.path.joinpath("ok").touch(exist_ok=True)
        self.upload_path.joinpath("ok").touch(exist_ok=True)

        #: User defined salt to hash the e-mail.
        self.salt = salt.encode("utf-8")

        self.upload_set = UploadSet("files", ("pdf",))

    @functools.lru_cache(maxsize=512)
    def hash_for(self, email):
        """Return unique hash for a given e-mail
        """
        return hashlib.pbkdf2_hmac(
            "sha256", email.encode("utf-8"), self.salt, 100000,
        ).hex()

    def statehash_for(self, uid):
        """Return the current state hash for user.
        """
        fn = self.path.joinpath(uid, "_state").with_suffix(".json").resolve().stem
        return self.hash_for(uid + fn)

    def folder_for(self, email):
        """Return the folder a user given the e-mail.
        """
        return self.path.joinpath(self.hash_for(email))

    def register(self, email, first_state):
        """Register an e-mail in the system.

        Parameters
        ----------
        email : str
        first_state : str
            Name of the state that will be assigned

        Returns
        -------
        pathlib.Path, pathlib.Path
            link file and dated file for the email storage.s
        """
        folder = self.folder_for(email)
        folder.mkdir()
        self.user_store(folder, "_email", dict(email=email))
        return self.user_store_state(folder, first_state)

    def is_registered(self, email):
        """Return True if the email is registered in the system.
        """
        return self.folder_for(email).exists()

    def yield_uids(self):
        """Yield all uid.
        """
        for f in self.path.iterdir():
            if not f.is_dir():
                continue
            if f.stem != "uploads":
                yield f.stem

    def retrieve_scheduled_emails(self):
        return _retrieve(self.path.joinpath("cron.json"))

    def store_scheduled_emails(self, cron):
        return _store(self.path.joinpath("cron.json"), cron)

    ####################################################
    # Methods to access information of a specific user
    ####################################################

    @functools.lru_cache(maxsize=512)
    def user_retrieve_email(self, uid):
        """Retrieve e-mail for uid.

        Parameters
        ----------
        uid : str

        Returns
        -------
        str
        """
        return self.user_retrieve(uid, "_email")["email"]

    def user_retrieve_state(self, uid):
        """Retrieve current state for uid.

        Parameters
        ----------
        uid : str

        Returns
        -------
        State
        """

        return State.from_hymie_dict(self.user_retrieve(uid, "_state"))

    def user_store(self, uid, endpoint, data, make_link_file=True):
        """Store data for a given user.
`
        Parameters
        ----------
        uid : str or pathlib.Path
        endpoint : str
            plain endpoint name
        data : dict
            content to store
        make_link_file : bool
            if True, a link file will be created.

        Returns
        -------
        pathlib.Path, pathlib.Path
            link file and dated file
        """
        if isinstance(uid, pathlib.Path):
            folder = uid
        else:
            folder = self.path.joinpath(uid)

        dated_file = folder.joinpath(
            endpoint + "_" + datetime_to_timestamp()
        ).with_suffix(".json")

        _store(dated_file, data)

        link_file = folder.joinpath(endpoint).with_suffix(".json")

        if make_link_file:
            if link_file.exists():
                link_file.unlink()

            link_file.symlink_to(dated_file.relative_to(link_file.parent))

        return link_file, dated_file

    def user_store_state(self, uid, state, make_link_file=True, form_dated_tuple=None):
        """Store a new state for given user.

        Parameters
        ----------
        uid : str
        state : str
        make_link_file : bool
            if True,

        Returns
        -------
        pathlib.Path, pathlib.Path
            link file and dated file
        """
        try:
            current_state = self.user_retrieve_state(uid)
            origin = current_state.state, current_state.timestamp
        except FileNotFoundError:
            origin = "register", datetime_to_timestamp(arrow.now().shift(minutes=-1))

        return self.user_store(
            uid,
            "_state",
            dict(state=state, origin=origin, form_dated_tuple=form_dated_tuple),
            make_link_file=make_link_file,
        )

    def user_retrieve(self, uid, endpoint):
        """Retrieve the endpoint content for a given user.

        In addition the to the actual content, the plain endpoint and timestamp are added.

        Parameters
        ----------
        uid : str
        endpoint : str
            Can be plain or dated endpoint.
        Returns
        -------
        dict
        """
        file = self.path.joinpath(uid, endpoint).with_suffix(".json")
        return _retrieve(file)

    def user_retrieve_form_data(self, uid, endpoint, form_cls):
        data = self.user_retrieve(uid, endpoint)
        # noinspection PyProtectedMember
        for name, value in data.items():
            field = getattr(form_cls, name, None)
            if field is None:
                continue
            field_type = field.__dict__["field_class"].__name__
            if field_type == "DateField":
                data[name] = arrow.get(value, "DD/MM/YY").datetime
            elif field_type == "TimeField":
                data[name] = arrow.get(value, "HH:mm").datetime

        return data

    def user_retrieve_current(self, uid, endpoints):
        """Retrieve the content of all non-system endpoints at the most recent dates.

        Parameters
        ----------
        uid : str
        endpoints : tuple
            endpoints to retrieve

        Returns
        -------
        dict
            endpoint -> content
        """
        out = {}
        for p in self.path.joinpath(uid).iterdir():
            if p.is_dir():
                continue
            if not p.is_symlink():
                continue
            endpoint = p.stem
            if endpoint not in endpoints:
                continue

            out[endpoint] = _retrieve(p)
        return out

    def user_retrieve_all_current(self, uid, skip=()):
        """Retrieve the content of all non-system endpoints at the most recent dates.

        Parameters
        ----------
        uid : str
        skip : tuple
            endpoints to ignore

        Returns
        -------
        dict
            endpoint -> content
        """
        out = {}
        for p in self.path.joinpath(uid).iterdir():
            if p.is_dir():
                continue
            if not p.is_symlink():
                continue
            endpoint = p.stem
            if endpoint.startswith("_"):
                continue
            if endpoint in skip:
                continue

            out[endpoint] = _retrieve(p)
        return out

    def user_retrieve_index(self, uid):
        """Retrieve a list of all non-system dated endpoints.

        Parameters
        ----------
        uid : str

        Returns
        -------
        tuple of (str, str)
            tuple of timestamp, plain endpoint ordered by timestamp.
        """
        out = {}
        for p in self.path.joinpath(uid).iterdir():
            if p.is_dir() or p.is_symlink():
                continue

            if p.stem.startswith("_"):
                continue

            endpoint, timestamp = split_endpoint_timestamp(p)

            out[timestamp] = endpoint

        return tuple((k, out[k]) for k in sorted(out.keys()))

    def user_retrieve_state_history(self, uid):
        """Retrieve the state history.

        Parameters
        ----------
        uid : str

        Returns
        -------
        dict:
            timestamp -> state, form_dated_file
        """
        out = {}
        for p in self.path.joinpath(uid).iterdir():
            if p.is_dir() or p.is_symlink():
                continue
            if not p.stem.startswith("_state"):
                continue
            content = self.user_retrieve(uid, p.stem)
            out[content["_hymie_timestamp"]] = State.from_hymie_dict(content)

        return out

    @contextlib.contextmanager
    def maybe_store_state(self, uid, state, store_form=None):
        """Context manager usesd to state a new state.

        Parameters
        ----------
        uid : str
        state : str
            new state

        Returns
        -------

        """

        if not state:
            raise Exception("State should not be empty.")

        else:

            dated_file = None
            form_link_file = None
            form_dated_file = None

            try:
                if store_form:
                    form_name, json_form = store_form
                    form_link_file, form_dated_file = self.user_store(
                        uid, form_name, json_form, make_link_file=False
                    )

                last_file, dated_file = self.user_store_state(
                    uid,
                    state,
                    make_link_file=False,
                    form_dated_tuple=split_endpoint_timestamp(form_dated_file),
                )

                yield self.hash_for(uid + dated_file.stem)

                if last_file.exists():
                    last_file.unlink()

                if form_dated_file:
                    if form_link_file.exists():
                        form_link_file.unlink()

                    form_link_file.symlink_to(form_dated_file)

                last_file.symlink_to(dated_file)

            except Exception:
                if form_dated_file:
                    form_dated_file.unlink()
                if dated_file:
                    dated_file.unlink()
                raise

    ##############################
    # Methods to store form data
    ##############################

    def store_form(self, uid, endpoint, form):
        """Store form.

        Parameters
        ----------
        uid : str
        endpoint : str
        form : FlaskForm

        Returns
        -------
        pathlib.Path, pathlib.Path
            link file and dated file
        """
        data = self.form_to_dict(form)
        return self.user_store(uid, endpoint, data)

    def store_filefield(self, field):
        """Store the content of a FileField via flask-uploads

        Parameters
        ----------
        field : FileField

        Returns
        -------
        str
            The url for the uploaded file.
        """
        filename = self.upload_set.save(field)
        return self.upload_set.url(filename)

    def form_to_dict(self, form):
        """Convert a form to a dict.

        Fields are serialized to build an object easy to dump to json.

        Parameters
        ----------
        form : FlaskForm

        Returns
        -------
        dict
        """
        data = {}
        # noinspection PyProtectedMember
        for name, field in form._fields.items():
            if name in ("csrf_token", "submit"):
                continue
            if field.type == "FileField":
                if field.data is None:
                    data[name] = None
                    continue
                fileid = self.upload_set.save(field.data)
                data[name] = url_for("file", fileid=fileid, _external=True)
            elif field.type == "DateField":
                data[name] = field.data.strftime("%d/%m/%y")
            elif field.type == "TimeField":
                data[name] = field.data.strftime("%H:%M")
            else:
                data[name] = field.data

        return data
