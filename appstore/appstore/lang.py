"""The language both pages show.

The App Store (``/``) and the container monitor (``/monitor``) share one
setting: both page states inherit ``locale`` from ``LocaleState``, so a
language picked on either page applies to the other at once.  The choice is
kept in the browser (it survives a reload) and synced across tabs, so an App
Store tab and a monitor tab open side by side switch together.

The text itself lives in the ``i18n`` package; see its ``__init__`` for how to
add a language.  A Reflex Var cannot be ``.format()``-ed in a component, so a
string with ``{placeholders}`` is filled in on the server, in a computed var
that reads ``self.locale``.  Such a var is recomputed whenever the language
changes, whichever page or tab changed it.

This module imports only ``i18n``: both page modules import it.
"""

from __future__ import annotations

import reflex as rx

from . import i18n


class LocaleState(rx.State):
    """Parent of both page states: the language and its string table."""

    # New visitors start in English (i18n.DEFAULT).  The storage key predates
    # the App Store being translated (only the monitor page was); it is kept so
    # a language picked there earlier still applies.
    locale: str = rx.LocalStorage(
        i18n.DEFAULT, name="appstore_monitor_locale", sync=True
    )

    @rx.var
    def t(self) -> dict[str, str]:
        """The string table the components read, e.g. ``LocaleState.t["refresh"]``."""
        return dict(i18n.strings(self.locale))

    @rx.var
    def lang_label(self) -> str:
        return i18n.label(self.locale)

    def _strings(self):
        return i18n.strings(self.locale)

    def _set_locale(self, code: str) -> None:
        self.locale = code if code in i18n.CODES else i18n.DEFAULT


def language_picker(state) -> rx.Component:
    """The language menu in a page header; the options come from i18n.LOCALES.

    ``state`` is the page's state class.  It owns whether the menu is open
    (``show_langs``, ``toggle_langs``) and the ``set_locale`` handler, which
    also redoes whatever that page composed in the old language.

    The list is built from a plain Python loop because the available languages
    are fixed when the app compiles — only the *choice* is state.  Each option
    carries its own ``lang``, so its name is drawn with that language's glyphs.
    """
    return rx.el.div(
        rx.el.button(
            rx.icon("languages", class_name="h-4 w-4"),
            rx.el.span(LocaleState.lang_label),
            rx.icon("chevron-down", class_name="h-3.5 w-3.5 opacity-60"),
            on_click=state.toggle_langs,
            title=LocaleState.t["language"],
            class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 font-medium rounded-xl hover:bg-gray-50 transition-all",
        ),
        rx.cond(
            state.show_langs,
            rx.el.div(
                *[
                    rx.el.button(
                        rx.el.span(loc["label"], lang=loc["code"], class_name="flex-1 text-left"),
                        rx.cond(
                            LocaleState.locale == loc["code"],
                            rx.icon("check", class_name="h-4 w-4 text-blue-600"),
                            None,
                        ),
                        on_click=state.set_locale(loc["code"]),
                        class_name="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-lg",
                    )
                    for loc in i18n.LOCALES
                ],
                class_name="absolute right-0 z-20 mt-2 w-44 p-1 bg-white border border-gray-200 rounded-xl shadow-lg",
            ),
            None,
        ),
        class_name="relative",
    )
