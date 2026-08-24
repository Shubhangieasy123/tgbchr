# Copyright (c) 2026, TGBC and contributors
# Attendance / late-arrival / permission policy helpers

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe.utils import getdate, get_datetime, get_first_day, get_last_day


# Defaults matching company policy
DEFAULTS = {
	"shift_start": time(9, 30),
	"grace_end": time(9, 40),
	"late_window_end": time(10, 0),
	"shift_end": time(18, 0),
	"allowed_late_per_month": 3,
	"permission_hours": 2,
	"permission_per_month": 2,
}


def _parse_time_value(value):
	"""Normalize Time field / string / timedelta to datetime.time."""
	if value is None or value == "":
		return None
	if isinstance(value, time):
		return value
	if isinstance(value, timedelta):
		total = int(value.total_seconds())
		hours, rem = divmod(total, 3600)
		minutes, seconds = divmod(rem, 60)
		return time(hours % 24, minutes, seconds)
	if isinstance(value, datetime):
		return value.time()
	# string like "09:30:00" or "9:30:00"
	text = str(value).strip()
	for fmt in ("%H:%M:%S", "%H:%M:%S.%f", "%H:%M"):
		try:
			return datetime.strptime(text, fmt).time()
		except ValueError:
			continue
	try:
		return get_datetime(f"2000-01-01 {text}").time()
	except Exception:
		return None


def _minutes_between(start: time, end: time) -> int:
	dummy = datetime(2000, 1, 1)
	return int((datetime.combine(dummy.date(), end) - datetime.combine(dummy.date(), start)).total_seconds() // 60)


def _add_minutes(t: time, minutes: int) -> time:
	return (datetime.combine(datetime.today().date(), t) + timedelta(minutes=minutes)).time()


def get_policy_settings() -> dict:
	"""Load settings from TGBC Attendance Settings (Single), else defaults."""
	settings = DEFAULTS.copy()
	settings["shift_name"] = ""
	if not frappe.db.exists("DocType", "TGBC Attendance Settings"):
		return settings

	doc = frappe.get_single("TGBC Attendance Settings")
	mapping = {
		"shift_start": "shift_start",
		"grace_end": "grace_end",
		"late_window_end": "late_window_end",
		"shift_end": "shift_end",
	}
	for key, field in mapping.items():
		parsed = _parse_time_value(doc.get(field))
		if parsed is not None:
			settings[key] = parsed

	if doc.allowed_late_per_month is not None:
		settings["allowed_late_per_month"] = int(doc.allowed_late_per_month)
	if doc.permission_hours is not None:
		settings["permission_hours"] = float(doc.permission_hours)
	if doc.permission_per_month is not None:
		settings["permission_per_month"] = int(doc.permission_per_month)
	return settings


def get_employee_shift(employee: str, process_date) -> str | None:
	"""Shift Assignment for the date, else Employee.default_shift."""
	process_date = getdate(process_date)
	if frappe.db.exists("DocType", "Shift Assignment"):
		rows = frappe.get_all(
			"Shift Assignment",
			filters={
				"employee": employee,
				"docstatus": 1,
				"status": "Active",
				"start_date": ["<=", process_date],
			},
			fields=["shift_type", "end_date"],
			order_by="start_date desc",
			limit=10,
		)
		for row in rows:
			if not row.end_date or getdate(row.end_date) >= process_date:
				if row.shift_type:
					return row.shift_type

	return frappe.db.get_value("Employee", employee, "default_shift")


def get_policy_settings_for_employee(employee: str, process_date=None) -> dict:
	"""Company timings, overridden by the employee's Shift Type when set.

	Grace and late windows keep the same offsets as TGBC Attendance Settings
	(default: +10 min grace, +30 min late-allowed window).
	"""
	settings = get_policy_settings()
	process_date = getdate(process_date) if process_date else getdate()
	shift_name = get_employee_shift(employee, process_date)
	settings["shift_name"] = shift_name or ""
	if not shift_name or not frappe.db.exists("Shift Type", shift_name):
		return settings

	start = _parse_time_value(frappe.db.get_value("Shift Type", shift_name, "start_time"))
	end = _parse_time_value(frappe.db.get_value("Shift Type", shift_name, "end_time"))
	if not start or not end:
		return settings

	grace_mins = max(_minutes_between(settings["shift_start"], settings["grace_end"]), 0)
	late_mins = max(_minutes_between(settings["shift_start"], settings["late_window_end"]), 0)

	settings["shift_start"] = start
	settings["shift_end"] = end
	settings["grace_end"] = _add_minutes(start, grace_mins)
	settings["late_window_end"] = _add_minutes(start, late_mins)
	return settings



def _to_time(value):
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.time()
	if isinstance(value, time):
		return value
	return get_datetime(value).time()


def count_allowed_lates_in_month(employee: str, process_date) -> int:
	"""Count prior 'Late Allowed' attendances in the same calendar month (before process_date)."""
	process_date = getdate(process_date)
	month_start = get_first_day(process_date)
	return frappe.db.count(
		"Attendance",
		{
			"employee": employee,
			"docstatus": 1,
			"attendance_date": ["between", [month_start, process_date - timedelta(days=1)]],
			"custom_late_category": "Late Allowed",
		},
	)


def has_approved_permission(employee: str, process_date, in_time=None, out_time=None) -> bool:
	"""True if an approved Employee Permission Request exists for this date."""
	if not frappe.db.exists("DocType", "Employee Permission Request"):
		return False

	process_date = getdate(process_date)
	return bool(
		frappe.db.exists(
			"Employee Permission Request",
			{
				"employee": employee,
				"permission_date": process_date,
				"status": "Approved",
				"docstatus": 1,
			},
		)
	)


def evaluate_attendance(
	employee: str,
	process_date,
	in_time,
	out_time,
	settings: dict | None = None,
) -> dict:
	"""
	Apply company late / grace / half-day policy.

	Returns dict:
	  status, late_entry, early_exit, late_category, remarks
	"""
	settings = settings or get_policy_settings()
	process_date = getdate(process_date)

	shift_start = settings["shift_start"]
	grace_end = settings["grace_end"]
	late_window_end = settings["late_window_end"]
	shift_end = settings["shift_end"]
	allowed_lates = settings["allowed_late_per_month"]

	result = {
		"status": "Absent",
		"late_entry": 0,
		"early_exit": 0,
		"late_category": "",
		"remarks": "",
	}

	if not in_time or not out_time:
		result["remarks"] = "Missing IN or OUT punch"
		return result

	in_t = _to_time(in_time)
	out_t = _to_time(out_time)

	permission_ok = has_approved_permission(employee, process_date, in_time, out_time)

	# Early exit (before shift end) — half day unless permission covers
	early_exit = out_t < shift_end
	result["early_exit"] = 1 if early_exit else 0

	# --- Late / grace evaluation ---
	if in_t <= shift_start:
		late_category = "On Time"
		late_entry = 0
		status_from_in = "Present"
		remarks = "On-time login"
	elif in_t <= grace_end:
		late_category = "Grace"
		late_entry = 0
		status_from_in = "Present"
		remarks = f"Within daily grace (by {grace_end.strftime('%H:%M')})"
	elif in_t <= late_window_end:
		# 9:40 – 10:00 : up to N allowed lates / month, else half day
		used = count_allowed_lates_in_month(employee, process_date)
		late_entry = 1
		if used < allowed_lates:
			late_category = "Late Allowed"
			status_from_in = "Present"
			remarks = f"Allowed late ({used + 1}/{allowed_lates} this month)"
		else:
			late_category = "Late Exceeded"
			status_from_in = "Half Day"
			remarks = (
				f"Exceeded {allowed_lates} allowed late logins this month "
				f"— half-day deduction"
			)
	else:
		# After 10:00 AM
		late_entry = 1
		late_category = "After 10 AM"
		status_from_in = "Half Day"
		remarks = f"Login after {late_window_end.strftime('%H:%M')} — half-day salary deduction"

	result["late_entry"] = late_entry
	result["late_category"] = late_category

	# Permission can waive half-day for late (not for missing punches)
	if status_from_in == "Half Day" and permission_ok and late_category in (
		"Late Exceeded",
		"After 10 AM",
	):
		# Policy: 2-hour permission with prior HOD approval — treat as Present for that day
		status_from_in = "Present"
		remarks = f"{remarks}; waived by approved 2-hour permission"
		result["late_category"] = f"{late_category} (Permission)"

	# Early exit without permission → half day (if otherwise Present)
	if early_exit and status_from_in == "Present":
		if permission_ok:
			remarks = f"{remarks}; early exit covered by permission"
		else:
			status_from_in = "Half Day"
			remarks = f"{remarks}; early exit before {shift_end.strftime('%H:%M')} — half day"

	result["status"] = status_from_in
	result["remarks"] = remarks
	return result
