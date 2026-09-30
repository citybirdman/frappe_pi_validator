# Copyright (c) 2026, Ahmed Zaytoon and contributors
# For license information, please see license.txt

"""
Whitelisted methods.

Desk page /app/pi-validator (login required):

    POST /api/method/frappe_pi_validator.api.extract_file
         file_url=/private/files/PI.pdf

Public web page /pi-validator (no login):

    POST /api/method/frappe_pi_validator.api.extract_public
         multipart form, field "file"

Public limits (site_config.json, optional):

    "pi_validator_max_file_mb": 10        upload size limit
    "pi_validator_rate_limit": 30         extractions per IP per hour
"""

import os
import tempfile

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

from frappe_pi_validator.extraction.services.table import brands
from frappe_pi_validator.pi_extractor import extract_document

PAGE = "pi-validator"

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".xls"}
DEFAULT_MAX_FILE_MB = 10
DEFAULT_RATE_LIMIT = 30


def use_site_brands() -> None:
	"""
	Recognize the brands of this site's Brand list (ERPNext "Brand"),
	shown exactly as written there. Without Brand records (or without
	the DocType) the built-in brand list is used.
	"""

	names = []

	if frappe.db.exists("DocType", "Brand"):
		names = frappe.get_all("Brand", pluck="name", limit_page_length=0)

	brands.set_known_brands(names)


def extract_with_site_brands(path: str, file_name: str) -> dict:
	use_site_brands()
	return extract_document(path, file_name)


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

	data = extract_with_site_brands(path, file_name)
	data["file_url"] = file_url
	data["file_name"] = file_name

	if not cint(include_result):
		data.pop("result", None)

	return data


def _public_rate_limit() -> int:
	return cint(frappe.conf.get("pi_validator_rate_limit")) or DEFAULT_RATE_LIMIT


def max_file_mb() -> int:
	return cint(frappe.conf.get("pi_validator_max_file_mb")) or DEFAULT_MAX_FILE_MB


@rate_limit(limit=_public_rate_limit, seconds=60 * 60, methods=["POST"])
def extract_upload(upload) -> dict:
	"""
	Extract a PI uploaded to the public page (no login).

	upload: werkzeug FileStorage from frappe.request.files. The file is
	processed in a temporary file and deleted; nothing is stored.
	Raises frappe.ValidationError with a user-facing message.
	"""

	if not upload or not upload.filename:
		frappe.throw(_("Choose a PI file to upload."))

	file_name = os.path.basename(upload.filename)
	extension = os.path.splitext(file_name)[1].lower()

	if extension not in ALLOWED_EXTENSIONS:
		frappe.throw(_("Only PDF, XLSX, XLSM and XLS files are supported."))

	limit_mb = max_file_mb()
	content = upload.stream.read(limit_mb * 1024 * 1024 + 1)

	if len(content) > limit_mb * 1024 * 1024:
		frappe.throw(_("The file is larger than {0} MB.").format(limit_mb))

	if not content:
		frappe.throw(_("The file is empty."))

	with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
		temp_file.write(content)
		temp_path = temp_file.name

	try:
		data = extract_with_site_brands(temp_path, file_name)
	except Exception:
		frappe.log_error(title=_("Public PI extraction failed"), message=frappe.get_traceback())
		frappe.throw(_("The file could not be read. Check that it is a valid PI document."))
	finally:
		os.remove(temp_path)

	data.pop("result", None)
	data["file_name"] = file_name

	return data


@frappe.whitelist(allow_guest=True, methods=["POST"])
def extract_public() -> dict:
	"""Guest endpoint of the public /pi-validator page."""

	return extract_upload(frappe.request.files.get("file"))
