# Copyright (c) 2026, TGBC
# Create Attendance custom fields for late policy tracking

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Attendance": [
				{
					"fieldname": "custom_late_category",
					"label": "Late Category",
					"fieldtype": "Select",
					"options": "\nOn Time\nGrace\nLate Allowed\nLate Exceeded\nAfter 10 AM\nLate Exceeded (Permission)\nAfter 10 AM (Permission)",
					"insert_after": "late_entry",
					"allow_on_submit": 1,
					"module": "tgbchr",
				},
				{
					"fieldname": "custom_attendance_remarks",
					"label": "Attendance Policy Remarks",
					"fieldtype": "Small Text",
					"insert_after": "custom_late_category",
					"allow_on_submit": 1,
					"module": "tgbchr",
				},
			]
		},
		update=True,
	)
