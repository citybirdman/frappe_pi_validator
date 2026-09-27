# Copyright (c) 2026, Ahmed Zaytoon and contributors
# For license information, please see license.txt

"""
Whitelisted methods used by the PI Validator page.

    POST /api/method/frappe_pi_validator.api.extract_file
         file_url=/private/files/PI.pdf
"""

import frappe
from frappe import _
from frappe.utils import cint

from frappe_pi_validator.pi_extractor import extract_document

PAGE = "pi-validator"


def check_page_access():
	"""Same roles as the PI Validator page."""

	if not frappe.get_doc("Page", PAGE).is_permitted():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def get_file_path(file_url: str) -> tuple[str, str]:
	"""(absolute path, file name) of an uploaded File."""

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	file_doc.check_permission("read")

	return file_doc.get_full_path(), file_doc.file_name


@frappe.whitelist()
def extract_file(file_url: str, include_result: bool = False) -> dict:
	"""
	Extract an uploaded PI (PDF / XLSX / XLSM / XLS).

	Returns items, summary and unrecognized tables; the full engine
	output only with include_result=1.
	"""

	check_page_access()

	path, file_name = get_file_path(file_url)

	data = extract_document(path, file_name)
	data["file_url"] = file_url
	data["file_name"] = file_name

	if not cint(include_result):
		data.pop("result", None)

	return data
