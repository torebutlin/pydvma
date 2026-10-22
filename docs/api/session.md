# Session Module

The notebook front door. `dvma.launch(settings)` starts the whole
logger — acquisition bridge, native compute engine, session journal and
embedded web UI — on a background thread inside the calling kernel, and
returns a `Session` handle for pulling data out, pushing data back, and
changing the open app's acquisition settings (`Session.apply_settings`).
It is the successor to the removed `dvma.Logger`.

The server process, not the browser tab, owns the session document, so
closing the tab loses nothing: reopen the URL and the app offers the
session back.

## Launching a Session

::: pydvma.session.launch

## The Session Handle

::: pydvma.session.Session

## The Session Journal

The server-side store behind `Session.data` and `Session.push`. Held by
`pydvma.serve.BridgeServer`; the browser app reads and writes it over
the `/engine` socket. Normally used through `Session` rather than
directly.

::: pydvma.journal.SessionJournal

## The Working Folder

Where the served app saves and loads by default: the folder the server
started in, which for `dvma.launch` is the notebook's own folder. Held
by `pydvma.serve.BridgeServer`; the app reads, lists and writes it over
the `/engine` socket, and `Session.save_dir` reads and sets it from the
notebook.

::: pydvma.savefolder.SaveFolder

::: pydvma.savefolder.is_local_app_request
