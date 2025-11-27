# GUI Module

Graphical user interface components for interactive data logging and analysis.

## Main Logger Class

::: pydvma.gui.Logger
    options:
      show_source: false
      heading_level: 3
      members: true
      filters: ["!^_"]

## Window Classes

::: pydvma.gui.PreviewWindow
    options:
      show_source: false
      heading_level: 3

::: pydvma.gui.DampingFitWindow
    options:
      show_source: false
      heading_level: 3

!!! note
    The GUI module is primarily intended for interactive use through the
    Logger interface. Most users will instantiate `Logger(settings)` rather
    than using these classes directly.
