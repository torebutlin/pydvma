"""The web logger's working folder when it is served locally.

When the app is opened through ``pydvma-serve`` or `pydvma.launch`, saving
and loading work on the serving machine's disk directly instead of through
browser downloads (which a browser such as Edge files away in Downloads
without asking). The WORKING FOLDER is the default for both: it starts as
the directory the server was started in, which for `pydvma.launch` is the
notebook kernel's working directory, i.e. the notebook's own folder, so a
saved file sits next to the notebook and loads back with a relative path.
The app's header pill changes it; the Save and Load dialogs can browse to
another folder for one file without changing it.

`SaveFolder` holds that folder and does the reading and writing. The
``/engine`` websocket (`pydvma.engine_host.handle_connection`) exposes it to
the app as five ops: ``files_info``, ``files_list``, ``files_set_dir``,
``files_save`` and ``files_read``. Because reading and writing files is a
privilege a web page must not get by accident, those ops are answered only
for a request that `is_local_app_request` accepts: the page must come from
the server itself (same origin) under a loopback host name. Any other
website open in the same browser, including one using DNS rebinding to look
local, is refused. `SaveFolder.save` also writes only data, export and
figure files (`SAVE_EXTENSIONS`) and never replaces an existing file unless
told to, and `SaveFolder.read` reads only loadable data files
(`LISTED_EXTENSIONS`).
"""
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .journal import _replace_with_retry

#: File types `SaveFolder.save` will write: datasets, the data exports and
#: figures. Anything else is refused, so the save op cannot be used to drop
#: scripts or executables on the serving machine.
SAVE_EXTENSIONS = ('.dvma', '.mat', '.csv', '.png', '.pdf', '.svg')

#: File types `SaveFolder.listing` shows beside the subfolders, so the folder
#: chooser shows what is already there (the files the app can load).
LISTED_EXTENSIONS = ('.dvma', '.mat', '.csv', '.npy')

#: Host names that address this machine only.
LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '::1')


def is_local_app_request(origin, host):
    """Whether a websocket request comes from the served app itself.

    True only when the browser's ``Origin`` header names the same scheme-less
    host and port the request was sent to (``Host``), and that host is a
    loopback name. A page from any other site carries its own origin and is
    refused; a DNS-rebinding page (another site's name resolving to
    127.0.0.1) passes the same-origin test but not the loopback one. A
    request with no ``Origin`` (not a browser) is refused too.

    Args:
        origin (str or None): the request's ``Origin`` header.
        host (str or None): the request's ``Host`` header.

    Returns:
        allowed (bool): True when file ops may be answered.
    """
    if not origin or not host:
        return False
    try:
        parsed = urlsplit(origin)
        target = urlsplit('//' + host)
        hostname = target.hostname
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    if parsed.netloc.lower() != host.strip().lower():
        return False
    return (hostname or '').lower() in LOOPBACK_HOSTS


def _resolve(path, base):
    """``path`` (str or Path, ``~`` expanded) made absolute against ``base``."""
    p = Path(os.path.expanduser(str(path).strip()))
    if not p.is_absolute():
        p = Path(base) / p
    return Path(os.path.abspath(p))


class SaveFolder:
    """The folder the served web logger saves into, and its file operations.

    Thread-safe: the folder can be read and changed from any ``/engine``
    connection (one per open tab) and from the notebook, via
    `pydvma.session.Session.save_dir`.

    Args:
        path (str or pathlib.Path or None): the starting folder; ``None``
            uses the current working directory, which for `pydvma.launch`
            is the notebook's folder. It must exist.

    Raises:
        ValueError: ``path`` is not an existing folder.
    """

    def __init__(self, path=None):
        self._lock = threading.Lock()
        start = _resolve(path if path is not None else os.getcwd(), os.getcwd())
        if not start.is_dir():
            raise ValueError('save folder does not exist: %s' % start)
        self._path = start

    @property
    def path(self):
        """The current folder, as an absolute `pathlib.Path`."""
        with self._lock:
            return self._path

    def info(self):
        """The current folder as a dict for the app.

        Returns:
            info (dict): ``dir`` (absolute path), ``name`` (its last part,
                or the whole path at a drive or filesystem root) and
                ``sep`` (this system's path separator).
        """
        p = self.path
        return {'dir': str(p), 'name': p.name or str(p), 'sep': os.sep}

    def set_dir(self, path):
        """Make ``path`` the folder saves go to.

        Args:
            path (str or pathlib.Path): an existing folder, absolute or
                relative to the current one; ``~`` is expanded.

        Returns:
            info (dict): `info` for the new folder.

        Raises:
            ValueError: ``path`` is not an existing folder.
        """
        target = _resolve(path, self.path)
        if not target.is_dir():
            raise ValueError('not a folder: %s' % target)
        with self._lock:
            self._path = target
        return self.info()

    def listing(self, path=None):
        """What the folder chooser shows for ``path``.

        Args:
            path (str or pathlib.Path or None): the folder to list,
                absolute or relative to the current one; ``None`` lists the
                current folder. Listing does not change the save folder.

        Returns:
            listing (dict): ``dir`` (absolute path listed), ``parent`` (its
                parent, or None at a root), ``folders`` (subfolder names,
                hidden ones left out) and ``files`` (names of the loadable
                data files there, `LISTED_EXTENSIONS`), both sorted
                case-insensitively.

        Raises:
            ValueError: ``path`` is not a folder, or cannot be read.
        """
        target = self.path if path is None else _resolve(path, self.path)
        if not target.is_dir():
            raise ValueError('not a folder: %s' % target)
        folders, files = [], []
        try:
            with os.scandir(target) as entries:
                for entry in entries:
                    name = entry.name
                    if name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir():
                            folders.append(name)
                        elif os.path.splitext(name)[1].lower() in LISTED_EXTENSIONS:
                            files.append(name)
                    except OSError:
                        continue              # an entry we may not stat
        except OSError as e:
            raise ValueError('cannot read %s: %s' % (target, e.strerror or e)) from e
        parent = target.parent if target.parent != target else None
        return {
            'dir': str(target),
            'parent': None if parent is None else str(parent),
            'folders': sorted(folders, key=str.lower),
            'files': sorted(files, key=str.lower),
        }

    def save(self, name, data, overwrite=False):
        """Write ``data`` as ``name`` in the folder.

        The write is atomic (a temporary file in the same folder, then a
        replace), so a failed save never leaves a truncated file behind.
        An existing file is replaced only with ``overwrite=True``; otherwise
        nothing is written and the result says the file exists, so the app
        can ask first.

        Args:
            name (str): file name, or a path relative to the folder (its
                parent folders must exist), or an absolute path. Must end in
                one of `SAVE_EXTENSIONS`.
            data (bytes): the file's contents.
            overwrite (bool): replace an existing file.

        Returns:
            result (dict): ``path`` (absolute path), ``saved`` (whether it
                was written) and ``exists`` (whether a file was already
                there).

        Raises:
            ValueError: a bad name or type, a missing parent folder, or a
                write the system refused (the message says why).
        """
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError('save needs file bytes')
        text = str(name or '').strip()
        if not text or text.endswith(('/', '\\')):
            raise ValueError('save needs a file name')
        target = _resolve(text, self.path)
        if target.suffix.lower() not in SAVE_EXTENSIONS:
            raise ValueError('cannot save a %s file here; allowed: %s'
                             % (target.suffix or 'nameless',
                                ', '.join(SAVE_EXTENSIONS)))
        if not target.parent.is_dir():
            raise ValueError('folder does not exist: %s' % target.parent)
        exists = target.exists()
        if exists and not target.is_file():
            raise ValueError('not a file: %s' % target)
        if exists and not overwrite:
            return {'path': str(target), 'saved': False, 'exists': True}
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix='.' + target.name + '.',
                    suffix='.tmp', delete=False) as f:
                tmp = f.name
                f.write(bytes(data))
            _replace_with_retry(tmp, str(target))
            tmp = None
        except OSError as e:
            raise ValueError('could not save %s: %s'
                             % (target, e.strerror or e)) from e
        finally:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return {'path': str(target), 'saved': True, 'exists': exists}

    def read(self, path):
        """Read a data file for the app's Load Data.

        Args:
            path (str or pathlib.Path): the file, absolute or relative to
                the folder. Must be one of `LISTED_EXTENSIONS`, the files
                the app can load; nothing else is read.

        Returns:
            result (dict): ``name`` (the file name), ``path`` (absolute
                path) and ``data`` (its bytes).

        Raises:
            ValueError: not a loadable file type, not a file, or unreadable.
        """
        target = _resolve(path, self.path)
        if target.suffix.lower() not in LISTED_EXTENSIONS:
            raise ValueError('cannot load a %s file; loadable: %s'
                             % (target.suffix or 'nameless',
                                ', '.join(LISTED_EXTENSIONS)))
        if not target.is_file():
            raise ValueError('no such file: %s' % target)
        try:
            data = target.read_bytes()
        except OSError as e:
            raise ValueError('could not read %s: %s'
                             % (target, e.strerror or e)) from e
        return {'name': target.name, 'path': str(target), 'data': data}
