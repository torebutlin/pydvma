# Session Module

The notebook front door. `dvma.launch(settings)` starts the whole
logger — acquisition bridge, native compute engine, session journal and
embedded web UI — on a background thread inside the calling kernel, and
returns a `Session` handle for pulling data out and pushing data back.
It is the successor to the removed `dvma.Logger`.

The server process, not the browser tab, owns the session document, so
closing the tab loses nothing: reopen the URL and the app offers the
session back.

## Launching a Session

::: pydvma.session.launch
    options:
      show_source: false
      heading_level: 3

## The Session Handle

::: pydvma.session.Session
    options:
      show_source: false
      heading_level: 3
      members: true

## The Session Journal

The server-side store behind `Session.data` and `Session.push`. Held by
`pydvma.serve.BridgeServer`; the browser app reads and writes it over
the `/engine` socket. Normally used through `Session` rather than
directly.

::: pydvma.journal.SessionJournal
    options:
      show_source: false
      heading_level: 3
      members: true
