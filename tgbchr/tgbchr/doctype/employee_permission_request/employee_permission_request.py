# Copyright (c) 2026, TGBC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime, time_diff_in_hours, add_days, nowdate

from tgbchr.attendance_policy import get_policy_settings


class EmployeePermissionRequest(Document):
	def validate(self):
		self.calculate_hours()
		self.validate_hours_limit()
		self.validate_monthly_limit()
		self.validate_not_consecutive()
		self.validate_advance_notice()

	def before_submit(self):
		if self.status not in ("Approved", "Rejected"):
			self.status = "Approved"

	def on_submit(self):
		# After approval, rebuild that day's Attendance so Summary reflects permission
		if self.status == "Approved" and self.employee and self.permission_date:
			self._refresh_attendance()

	def on_cancel(self):
		self.status = "Cancelled"
		# Revert attendance without this permission
		if self.employee and self.permission_date:
			self._refresh_attendance()

	def _refresh_attendance(self):
		try:
			from tgbchr.api import reprocess_employee_attendance

			msg = reprocess_employee_attendance(
				self.employee, self.permission_date, force=True
			)
			frappe.msgprint(msg)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Permission attendance refresh failed ({self.name})",
			)
			frappe.msgprint(
				_("Permission saved, but Attendance could not be auto-updated. "
				  "Please reprocess attendance for {0}.").format(self.permission_date),
				indicator="orange",
			)

	def calculate_hours(self):
		if self.from_time and self.to_time:
			# time_diff_in_hours needs datetime-like; use same dummy date
			start = get_datetime(f"2000-01-01 {self.from_time}")
			end = get_datetime(f"2000-01-01 {self.to_time}")
			if end <= start:
				frappe.throw(_("To Time must be after From Time"))
			self.hours = round(time_diff_in_hours(end, start), 2)

	def validate_hours_limit(self):
		settings = get_policy_settings()
		max_hours = settings["permission_hours"]
		if self.hours and self.hours > max_hours + 0.01:
			frappe.throw(
				_("Permission cannot exceed {0} hours (requested {1})").format(
					max_hours, self.hours
				)
			)

	def validate_monthly_limit(self):
		if not self.employee or not self.permission_date:
			return
		settings = get_policy_settings()
		limit = settings["permission_per_month"]
		d = getdate(self.permission_date)
		month_start = d.replace(day=1)
		if d.month == 12:
			month_end = d.replace(year=d.year + 1, month=1, day=1)
		else:
			month_end = d.replace(month=d.month + 1, day=1)

		filters = {
			"employee": self.employee,
			"permission_date": ["between", [month_start, add_days(month_end, -1)]],
			"docstatus": 1,
			"status": "Approved",
			"name": ["!=", self.name],
		}
		count = frappe.db.count("Employee Permission Request", filters)
		if count >= limit:
			frappe.throw(
				_("Only {0} approved permissions allowed per month. Already used: {1}").format(
					limit, count
				)
			)

	def validate_not_consecutive(self):
		"""Cannot use permission on consecutive days."""
		if not self.employee or not self.permission_date:
			return
		d = getdate(self.permission_date)
		for other in (add_days(d, -1), add_days(d, 1)):
			exists = frappe.db.exists(
				"Employee Permission Request",
				{
					"employee": self.employee,
					"permission_date": other,
					"docstatus": 1,
					"status": "Approved",
					"name": ["!=", self.name],
				},
			)
			if exists:
				frappe.throw(
					_("2-hour permission cannot be used on consecutive days (conflict with {0})").format(
						exists
					)
				)

	def validate_advance_notice(self):
		"""Request must be at least 1 day before permission date (when creating)."""
		if self.is_new() and self.permission_date:
			if getdate(self.permission_date) <= getdate(nowdate()):
				# Allow HR/System Manager to backfill; Employees must request in advance
				roles = frappe.get_roles()
				if "HR Manager" not in roles and "System Manager" not in roles:
					frappe.throw(
						_("Permission must be requested at least one day in advance")
					)
