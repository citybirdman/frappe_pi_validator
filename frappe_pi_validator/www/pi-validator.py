# Copyright (c) 2026, Ahmed Zaytoon and contributors
# For license information, please see license.txt

"""
Public page /pi-validator (no login needed).

The page script sends the file to frappe_pi_validator.api.extract_public
and shows the result in place, like the desk page.
"""

import frappe
from frappe import _

from frappe_pi_validator.api import max_file_mb

no_cache = 1


def get_context(context):
	context.title = _("PI Validator")
	context.no_breadcrumbs = True
	context.show_sidebar = False
	context.max_file_mb = max_file_mb()

	# Logged-in users must send the CSRF token with the upload.
	context.csrf_token = frappe.sessions.get_csrf_token() if frappe.session.user != "Guest" else ""
