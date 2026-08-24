# Copyright (c) 2026, TGBC
# Auto-refresh Attendance when related requests are submitted/cancelled

import frappe
from frappe.utils import getdate, add_days, date_diff


def on_attendance_request_submit(doc, method=None):
	"""HRMS already creates/updates Attendance. Re-apply TGBC policy only when
	the request does not force Work From Home / On Duty status.
	"""
	reason = (doc.reason or "").strip()
	# These statuses are set by HRMS from the request itself — do not overwrite
	if reason in ("Work From Home", "On Duty"):
		return
	_refresh_range(doc.employee, doc.from_date, doc.to_date)


def on_attendance_request_cancel(doc, method=None):
	"""After cancel, rebuild from checkins + permission policy."""
	_refresh_range(doc.employee, doc.from_date, doc.to_date)


def _refresh_range(employee, from_date, to_date):
	if not employee or not from_date:
		return
	from_date = getdate(from_date)
	to_date = getdate(to_date or from_date)
	days = date_diff(to_date, from_date) + 1
	from tgbchr.api import reprocess_employee_attendance

	for i in range(max(days, 0)):
		day = add_days(from_date, i)
		try:
			reprocess_employee_attendance(employee, day, force=True)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Attendance Request refresh failed ({employee} {day})",
			)
