# main.py
#
# Copyright 2026 MM 喵了个
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

import sys
import os
import locale
import gettext
import builtins

APP_ID = 'com.github.mimiaomc.nextstop'
GETTEXT_DOMAIN = 'nextstop'

LOCALE_DIR = '/app/share/locale'
if not os.path.exists(LOCALE_DIR):
    LOCALE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'po')

try:
    locale.bindtextdomain(GETTEXT_DOMAIN, LOCALE_DIR)
    locale.textdomain(GETTEXT_DOMAIN)
    gettext.bindtextdomain(GETTEXT_DOMAIN, LOCALE_DIR)
    gettext.textdomain(GETTEXT_DOMAIN)
except AttributeError:
    pass

builtins._ = gettext.gettext

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw
from .window import NextstopWindow


class NextstopApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id='com.github.mimiaomc.nextstop',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/com/github/mimiaomc/nextstop')
        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action, ['<control>comma'])

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        win = self.props.active_window
        if not win:
            win = NextstopWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        about = Adw.AboutDialog(application_name='NextStop',
                                application_icon='com.github.mimiaomc.nextstop',
                                developer_name='MM 喵了个',
                                version='0.1.0',
                                comments=_('Transit announcement and broadcast simulator'),
                                website='https://github.com/mimiaomc/NextStop',
                                issue_url='https://github.com/mimiaomc/NextStop/issues',
                                # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
                                translator_credits=_('translator-credits'),
                                developers=['MM 喵了个'],
                                copyright='© 2026 MM 喵了个',
                                license_type=Gtk.License.LGPL_3_0)
        about.present(self.props.active_window)

    def on_preferences_action(self, widget, _):
        """Callback for the app.preferences action."""
        win = self.props.active_window
        if win and hasattr(win, "open_preferences_dialog"):
            win.open_preferences_dialog()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """The application's entry point."""
    app = NextstopApplication()
    return app.run(sys.argv)
