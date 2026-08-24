# Copyright (c) 2026, TGBC
# Employee Device Unit — required by biometric register_NewEmployee

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Employee": [
				{
					"fieldname": "custom_device_unit",
					"label": "Device Unit",
					"fieldtype": "Link",
					"options": "Device Master",
					"insert_after": "attendance_device_id",
					"module": "tgbchr",
				},
			]
		},
		update=True,
	)
