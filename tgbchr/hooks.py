app_name = "tgbchr"
app_title = "tgbchr"
app_publisher = "shubhangi@easycloud.in"
app_description = "HR"
app_email = "shubhangi@easycloud.in"
app_license = "mit"

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["module", "=", "tgbchr"]],
	},
	{
		"dt": "Client Script",
		"filters": [["module", "=", "tgbchr"]],
	},
	{
		"dt": "Server Script",
		"filters": [["module", "=", "tgbchr"]],
	},
]

scheduler_events = {
	# long queue: default worker is often missing on this bench
	"hourly_long": [
		"tgbchr.api.sync_and_create_checkins",
	],
	"cron": {
		# 12:30 AM IST — process previous working day's Attendance
		"30 0 * * *": [
			"tgbchr.api.process_yesterday_attendance",
		],
		# monthly attendance summary email (~10th of month)
		"0 10 10 * *": [
			"tgbchr.api.send_monthly_attendance_summary",
		],
	},
}

# After Attendance Request submit/cancel, refresh TGBC policy attendance
# (HRMS may set Present/WFH; for checkin-based days we re-apply permission/late rules)
doc_events = {
	"Attendance Request": {
		"on_submit": "tgbchr.attendance_hooks.on_attendance_request_submit",
		"on_cancel": "tgbchr.attendance_hooks.on_attendance_request_cancel",
	},
}

doctype_js = {
    "Employee": "public/js/Employee.js"
}