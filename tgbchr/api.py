import frappe
import os
import requests
from datetime import datetime, date, time,timedelta
import calendar
from frappe.utils import now
#Update the Attendence API
@frappe.whitelist(allow_guest=True)
def get_and_update_attendance(from_date=None, to_date=None):
    """
    Sync biometric punches into Raw Attendance Data.

    Date range:
      1. Explicit from_date / to_date args
      2. Fallback: yesterday → tomorrow (scheduler-safe)
    """
    try:
        api_master = frappe.get_all(
            "Biometric API Master",
            fields=[
                "get_token_url",
                "get_attendance_url",
                "user_name",
                "password",
                "from_date",
                "end_date",
            ],
            limit=1
        )

        if not api_master:
            return "API configuration missing"

        api_data = api_master[0]

        user_name = api_data.get("user_name")
        password = api_data.get("password")
        login_url = api_data.get("get_token_url")
        attendance_url = api_data.get("get_attendance_url")

        today_date = frappe.utils.getdate()
        if from_date:
            from_date = frappe.utils.getdate(from_date).strftime("%Y-%m-%d")
        else:
            from_date = frappe.utils.add_days(today_date, -1).strftime("%Y-%m-%d")

        if to_date:
            to_date = frappe.utils.getdate(to_date)
            end_date = min(to_date, frappe.utils.add_days(today_date, 1)).strftime("%Y-%m-%d")
        else:
            end_date = frappe.utils.add_days(today_date, 1).strftime("%Y-%m-%d")

        login_url_with_params = (
            f"{login_url}?UserName={user_name}&Password={password}"
        )

        token_response = requests.get(login_url_with_params, timeout=30)

        if token_response.status_code != 200:
            return "Token API failed"

        token_json = token_response.json()
        auth_token = token_json.get("AuthToken")

        if not auth_token:
            return "AuthToken missing"

        attendance_url_with_params = (
            f"{attendance_url}?FromDatetime={from_date}"
            f"&ToDateTime={end_date}"
        )

        headers = {"AuthToken": auth_token}

        attendance_response = requests.get(
            attendance_url_with_params,
            headers=headers,
            timeout=60
        )

        if attendance_response.status_code != 200:
            return "Attendance API failed"

        attendance_json = attendance_response.json()
        attendance_data = attendance_json.get("Items", [])

        inserted_count = 0
        skipped_count = 0

        for record in attendance_data:

            punch_time_full = record.get("PunchTime")

            if not punch_time_full:
                continue

            punch_date, punch_time = punch_time_full.split("T")

            employee_code = record.get("EmpNo")

            # Check duplicate
            exists = frappe.db.exists("Raw Attendance Data", {
                "employee_code": employee_code,
                "punch_date": punch_date,
                "punch_time": punch_time
            })

            if exists:
                skipped_count += 1
                continue

            frappe.get_doc({
                "doctype": "Raw Attendance Data",
                "employee_code": employee_code,
                "punch_date": punch_date,
                "punch_time": punch_time,
                "punch_id": record.get("IDNo"),
                "biometric_device_id": record.get("CPUID"),
                "biometric_address": record.get("OUCode")
            }).insert(ignore_permissions=True)

            inserted_count += 1

        # Commit once for performance
        frappe.db.commit()

        return f"Sync Completed. Inserted: {inserted_count}, Skipped: {skipped_count}"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Biometric Sync Error")
        return "Error occurred during biometric sync"


@frappe.whitelist()
def sync_and_create_checkins():
	"""Hourly: pull biometric punches, then create Employee Checkin (yesterday + today)."""
	today = frappe.utils.getdate()
	yesterday = frappe.utils.add_days(today, -1)
	sync_msg = get_and_update_attendance(from_date=yesterday, to_date=today)
	checkin_msg = process_raw_attendance(from_date=yesterday, to_date=today)
	return f"{sync_msg}\n{checkin_msg}"

def _map_raw_employee(employee_code):
    if not employee_code:
        return None
    employee = frappe.db.get_value("Employee", {"attendance_device_id": employee_code}, "name")
    if employee:
        return employee
    if frappe.db.exists("Employee", employee_code):
        return employee_code
    return frappe.db.get_value("Employee", {"employee_number": employee_code}, "name")


@frappe.whitelist(allow_guest=True)
def process_raw_attendance(from_date=None, to_date=None):
    today_date = frappe.utils.getdate()
    sync_from = frappe.utils.getdate(from_date) if from_date else frappe.utils.add_days(today_date, -1)
    sync_to = frappe.utils.getdate(to_date) if to_date else today_date

    raw_attendance_records = frappe.get_all(
        "Raw Attendance Data",
        fields=["name", "employee_code", "punch_date", "punch_time"],
        filters={"punch_date": ["between", [sync_from, sync_to]]},
    )

    if not raw_attendance_records:
        return f"No attendance records found from {sync_from} to {sync_to}."

    attendance_by_employee = {}
    for record in raw_attendance_records:
        key = (record.get("employee_code"), record.get("punch_date"))
        if key not in attendance_by_employee:
            attendance_by_employee[key] = []
        attendance_by_employee[key].append(record.get("punch_time"))

    created = 0
    skipped_employee = 0

    for (employee_code, punch_date), punch_times in attendance_by_employee.items():
        if not punch_times:
            continue

        min_punch_time = min(punch_times)
        max_punch_time = max(punch_times)

        employee = _map_raw_employee(employee_code)
        if not employee:
            skipped_employee += 1
            continue

        emp_status = frappe.db.get_value("Employee", employee, "status")
        if emp_status != "Active":
            skipped_employee += 1
            continue

        in_time = f"{punch_date} {min_punch_time}"
        if not frappe.db.exists("Employee Checkin", {"employee": employee, "time": in_time}):
            try:
                frappe.get_doc({
                    "doctype": "Employee Checkin",
                    "employee": employee,
                    "time": in_time,
                    "log_type": "IN"
                }).insert(ignore_permissions=True)
                created += 1
            except Exception as exc:
                frappe.log_error(title="Checkin IN failed", message=f"{employee} {in_time}: {exc}")

        out_time = f"{punch_date} {max_punch_time}"
        if in_time != out_time and not frappe.db.exists("Employee Checkin", {"employee": employee, "time": out_time}):
            try:
                frappe.get_doc({
                    "doctype": "Employee Checkin",
                    "employee": employee,
                    "time": out_time,
                    "log_type": "OUT"
                }).insert(ignore_permissions=True)
                created += 1
            except Exception as exc:
                frappe.log_error(title="Checkin OUT failed", message=f"{employee} {out_time}: {exc}")

    frappe.db.commit()
    return (
        f"Employee Checkin created from {sync_from} to {sync_to}. "
        f"Inserted: {created}. Unmapped employees: {skipped_employee}."
    )

@frappe.whitelist(allow_guest=True)
def get_auth_token():
    login_url = 'http://bd.easycloud.in/smartface/api/WebApi/Login'
    # Biometric master
    sql_query = """
        SELECT user_name, password FROM `tabBiometric API Master` tbam where docstatus=1
    """
    credentials = frappe.db.sql(sql_query, as_dict=True)
    credentials = credentials[0]
    # print("credentials:",credentials)
    user=credentials.get("user_name")
    pwd=credentials.get("password")
    params = {
        'UserName': user,
        'Password': pwd
    }
    
    try:
        response = requests.get(login_url, params=params)
        # print("Login API Response Status Code:", response.status_code)
        # print("Login API Response Text:", response.text)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('Message') == 'Success':
                return data.get('AuthToken')
            else:
                return "Login API Error"
        else:
            return "Login API Request Failed. Status Code"
    except Exception as e:
        return "Exception occurred while calling Login API"
    
    return None

def check_employee_status(auth_token, ref_no):
    status_url = f'http://bd.easycloud.in/smartface/api/EmployeeRequest/StatusOfNewEmployee?RefNo={ref_no}'
    headers = {
        'AuthToken': auth_token,
        'Content-Type': 'application/json'
    }
    response = requests.get(status_url, headers=headers)
    # print("responseREFNO:", response)
    return response

@frappe.whitelist(allow_guest=True)
def register_NewEmployee():
    """Register employees created today on the biometric device API.

    Requires Employee.custom_device_unit (Link to Device Master). If that
    field is not installed on the site, return quietly so the scheduler
    does not fail every minute.
    """
    try:
        emp_meta = frappe.get_meta("Employee")
        if not emp_meta.has_field("custom_device_unit"):
            return "Skipped: Employee field custom_device_unit is not set up on this site."

        auth_token = get_auth_token()
        if not auth_token or not isinstance(auth_token, str) or auth_token.startswith("Login") or auth_token.startswith("Exception"):
            return "Failed to retrieve authentication token."

        today = frappe.utils.nowdate()
        employees = frappe.get_all(
            "Employee",
            filters={
                "creation": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
                "attendance_device_id": ["is", "set"],
                "custom_device_unit": ["is", "set"],
            },
            fields=["employee_name", "attendance_device_id", "custom_device_unit"],
        )
        if not employees:
            return "No new employees to register today."

        status_responses = []
        for employee in employees:
            employee_name = employee.get("employee_name")
            attendance_device_id = employee.get("attendance_device_id")
            custom_device_unit = employee.get("custom_device_unit")
            ou = frappe.db.get_value("Device Master", custom_device_unit, "ou")

            data = {
                "Name": employee_name,
                "EmpNo": attendance_device_id,
                "IDNo": attendance_device_id,
                "OU": ou,
                "Device": custom_device_unit,
                "StartDate": datetime.now().isoformat(),
            }
            headers = {
                "AuthToken": auth_token,
                "Content-Type": "application/json",
            }
            response = requests.post(
                "http://bd.easycloud.in/smartface/api/EmployeeRequest/ProcessEmployeeRegistration",
                headers=headers,
                json=data,
                timeout=30,
            )
            if response.status_code != 200:
                status_responses.append({
                    "employee_name": employee_name,
                    "error": f"HTTP {response.status_code}",
                })
                continue

            registration_response = response.json()
            if not (registration_response.get("Message") == "Success" and registration_response.get("IsSucceed")):
                status_responses.append({
                    "employee_name": employee_name,
                    "error": registration_response,
                })
                continue

            ref_no = registration_response["Item"]["RefNo"]
            status_response = check_employee_status(auth_token, ref_no)
            status_responses.append({
                "employee_name": employee_name,
                "status_response": status_response.json() if status_response.status_code == 200 else status_response.text,
            })

        return status_responses
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Register New Employee")
        return "Error in register_NewEmployee (see Error Log)"

@frappe.whitelist()
def update_all_shifts_last_sync():
    try:
        shift_types = frappe.get_all("Shift Type", filters={"enable_auto_attendance": 1}, fields=["name"])

        for shift in shift_types:
            shift_doc = frappe.get_doc("Shift Type", shift["name"])
            shift_doc.last_sync_of_checkin = now()
            shift_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {"status": "success", "message": "Last Sync Date updated for all Shift Types"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def send_monthly_attendance_summary():
    today = date.today()
    if today.day != calendar.monthrange(today.year, today.month)[1]:
        return

    first_day = today.replace(day=1)
    last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    employees = frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name", "user_id", "employee", "reports_to", "employee_number"])

    for emp in employees:
        # Get attendance records for the month
        attendance_data = frappe.db.get_all(
            "Attendance",
            filters={
                "employee": emp.name,
                "attendance_date": ["between", [first_day, last_day]],
                "status": "Absent"
            },
            fields=["attendance_date", "status"]
        )
        if not attendance_data:
            continue

        table_rows = ""
        for entry in attendance_data:
            att_date = entry.attendance_date
            status = entry.status or ""

            # Default values
            wfh = "Request Not Raised"
            on_duty = "Request Not Raised"
            leave = "Request Not Raised"
            remarks = ""

            # Check Attendance Request for WFH or On Duty
            att_req = frappe.db.get_value("Attendance Request", {
                "employee": emp.name,
                "from_date": ["<=", att_date],
                "to_date": [">=", att_date],
                "docstatus": 0
            }, ["reason"])

            if att_req:
                if "work from home" in att_req.lower():
                    wfh = "Request Raised But Not Submitted"
                elif "on duty" in att_req.lower():
                    on_duty = "Request Raised But Not Submitted"

            # Check Leave Application
            leave_type = frappe.db.get_value("Leave Application", {
                "employee": emp.name,
                "from_date": ["<=", att_date],
                "to_date": [">=", att_date]
            }, ["leave_type"])

            if leave_type:
                leave = leave_type

            # Remarks logic
            if status == "Absent":
                if not (wfh or on_duty or leave):
                    remarks = "Needs to Raise Request"
                elif wfh == "Request Not Raised" and on_duty == "Request Not Raised" and leave == "Request Not Raised":
                    remarks = "Needs to Raise Request"
                else:
                    remarks = "Needs to Submit Raised Request"

            # Approver
            approver = ""
            if emp.reports_to:
                approver = frappe.get_value("Employee", emp.reports_to, "employee_name") or ""

            table_rows += f"""
                <tr>
                    <td>{emp.employee_number}</td>
                    <td>{emp.employee_name}</td>
                    <td>{att_date}</td>
                    <td>{status}</td>
                    <td>{wfh}</td>
                    <td>{on_duty}</td>
                    <td>{leave}</td>
                    <td>{remarks}</td>
                    <td>{approver}</td>
                </tr>
            """

        html_table = f"""
            <p>Dear {emp.employee_name},</p>
            <p>Please find below your attendance summary for {today.strftime('%B %Y')}:</p>
            <table border="1" cellpadding="5" cellspacing="0">
                <thead>
                    <tr>
                        <th>Employee ID</th>
                        <th>Employee Name</th>
                        <th>Date</th>
                        <th>Attendance Status</th>
                        <th>WFH</th>
                        <th>On Duty</th>
                        <th>Leave</th>
                        <th>Remarks</th>
                        <th>Approver</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
            <p>Please review your monthly attendance. If any action is required from your side or your approver’s side, kindly ensure it is completed or reach out to them accordingly.</p>
        """

        if emp.user_id:
            try:
                frappe.sendmail(
                recipients=[emp.user_id],
                subject=f"Attendance Summary for {today.strftime('%B %Y')}",
                message=html_table,
                delayed=False
                )
                # print(f"Email sent to {emp.user_id}")
            except Exception as e:
                frappe.log_error(f"Failed to send email to {emp.user_id}: {e}", "Monthly Attendance Summary Email")
                # print(f"Failed to send email to {emp.user_id}: {e}")

@frappe.whitelist(allow_guest=True)
def process_employee_attendance(process_date=None, force=False):
	"""
	Create/submit Attendance from Employee Checkin using TGBC late & permission policy.

	Work timings: Mon–Sat 09:30–18:00
	Grace: until 09:40
	Allowed late: 09:40–10:00 up to 3 times/month, then Half Day
	After 10:00: Half Day

	force=True cancels existing non-leave Attendance for the day and recreates it.
	"""
	from tgbchr.attendance_policy import evaluate_attendance, get_policy_settings_for_employee

	if process_date:
		process_date = frappe.utils.getdate(process_date)
	else:
		# Scheduler / default: previous day (punches are complete after midnight)
		process_date = frappe.utils.add_days(frappe.utils.getdate(), -1)

	# Sunday is weekly off (Mon–Sat working days)
	if process_date.weekday() == 6:
		return f"Skipped {process_date}: Sunday (weekly off)"

	force = frappe.utils.cint(force)

	cleared = 0
	if force:
		to_clear = frappe.get_all(
			"Attendance",
			filters={"attendance_date": process_date, "docstatus": ["<", 2]},
			fields=["name", "status", "docstatus"],
		)
		for row in to_clear:
			if row.status == "On Leave":
				continue
			try:
				doc = frappe.get_doc("Attendance", row.name)
				doc.flags.ignore_permissions = True
				frappe.db.sql(
					"update `tabEmployee Checkin` set attendance=null where attendance=%s",
					doc.name,
				)
				if doc.docstatus == 1:
					doc.cancel()
				elif doc.docstatus == 0:
					doc.delete()
				cleared += 1
			except Exception as exc:
				frappe.log_error(
					title="Attendance force-clear failed",
					message=f"{row.name} {process_date}: {exc}",
				)
		frappe.db.commit()

	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "default_shift", "holiday_list", "date_of_joining"],
	)

	created = 0
	skipped = 0
	holiday_skip = 0
	joining_skip = 0
	half_days = 0
	lates_allowed = 0

	for emp_data in employees:
		emp = emp_data.name

		if emp_data.date_of_joining and process_date < emp_data.date_of_joining:
			joining_skip += 1
			continue

		if emp_data.holiday_list:
			is_holiday = frappe.db.exists(
				"Holiday",
				{"parent": emp_data.holiday_list, "holiday_date": process_date},
			)
			if is_holiday:
				holiday_skip += 1
				continue

		if frappe.db.exists(
			"Attendance",
			{"employee": emp, "attendance_date": process_date, "docstatus": ["<", 2]},
		):
			skipped += 1
			continue

		# Approved leave for the day → skip (do not override leave with late policy)
		on_leave = frappe.db.exists(
			"Attendance",
			{
				"employee": emp,
				"attendance_date": process_date,
				"docstatus": 1,
				"status": "On Leave",
			},
		)
		if on_leave:
			skipped += 1
			continue

		leave_app = frappe.db.exists(
			"Leave Application",
			{
				"employee": emp,
				"docstatus": 1,
				"status": "Approved",
				"from_date": ["<=", process_date],
				"to_date": [">=", process_date],
			},
		)
		# Policy: CL/SL/EL cannot adjust late arrivals — if full-day leave exists, mark On Leave via HRMS normally.
		# Here we only skip creating a conflicting Present/Half Day when leave already covers the day.
		if leave_app:
			skipped += 1
			continue

		start_dt = datetime.combine(process_date, time(0, 0, 0))
		end_dt = datetime.combine(process_date, time(23, 59, 59))

		checkins = frappe.get_all(
			"Employee Checkin",
			filters={"employee": emp, "time": ["between", [start_dt, end_dt]]},
			fields=["name", "time", "log_type"],
			order_by="time asc",
		)

		in_logs = [c for c in checkins if c.log_type == "IN"]
		out_logs = [c for c in checkins if c.log_type == "OUT"]

		in_time = in_logs[0].time if in_logs else None
		out_time = out_logs[-1].time if out_logs else None

		emp_settings = get_policy_settings_for_employee(emp, process_date)
		eval_result = evaluate_attendance(
			employee=emp,
			process_date=process_date,
			in_time=in_time,
			out_time=out_time,
			settings=emp_settings,
		)

		att_dict = {
			"doctype": "Attendance",
			"employee": emp,
			"attendance_date": process_date,
			"shift": emp_settings.get("shift_name") or emp_data.default_shift,
			"status": eval_result["status"],
			"in_time": in_time,
			"out_time": out_time,
			"late_entry": eval_result["late_entry"],
			"early_exit": eval_result["early_exit"],
		}
		if frappe.get_meta("Attendance").has_field("custom_late_category"):
			att_dict["custom_late_category"] = eval_result.get("late_category") or ""
		if frappe.get_meta("Attendance").has_field("custom_attendance_remarks"):
			att_dict["custom_attendance_remarks"] = eval_result.get("remarks") or ""

		try:
			att = frappe.get_doc(att_dict)
			att.insert(ignore_permissions=True)
			att.submit()
		except Exception as exc:
			frappe.log_error(
				title="Attendance process failed",
				message=f"{emp} {process_date}: {exc}",
			)
			continue

		created += 1
		if eval_result["status"] == "Half Day":
			half_days += 1
		if eval_result.get("late_category") == "Late Allowed":
			lates_allowed += 1

	frappe.db.commit()

	return f"""
Attendance Processed for {process_date}

Cleared old (force): {cleared}
Created & Submitted: {created}
Half Days: {half_days}
Late Allowed (quota used today): {lates_allowed}
Skipped Existing / Leave: {skipped}
Holiday / Weekly Off: {holiday_skip}
Skipped (Before Joining Date): {joining_skip}
"""


@frappe.whitelist()
def reprocess_employee_attendance(employee, process_date, force=True):
	"""Cancel (if force) and recreate Attendance for one employee on one date.

	Used when Permission Request / Attendance Request is submitted so Summary
	updates without a full-day force reprocess.
	"""
	from tgbchr.attendance_policy import evaluate_attendance, get_policy_settings_for_employee

	if not employee or not process_date:
		frappe.throw("employee and process_date are required")

	process_date = frappe.utils.getdate(process_date)
	force = frappe.utils.cint(force)

	if process_date.weekday() == 6:
		return f"Skipped {process_date}: Sunday (weekly off)"

	emp_data = frappe.db.get_value(
		"Employee",
		employee,
		["name", "status", "default_shift", "holiday_list", "date_of_joining"],
		as_dict=True,
	)
	if not emp_data or emp_data.status != "Active":
		return f"Skipped {employee}: not an Active Employee"

	if emp_data.date_of_joining and process_date < emp_data.date_of_joining:
		return f"Skipped {employee}: before joining date"

	if emp_data.holiday_list and frappe.db.exists(
		"Holiday",
		{"parent": emp_data.holiday_list, "holiday_date": process_date},
	):
		return f"Skipped {employee}: holiday on {process_date}"

	# Do not touch leave attendance
	leave_att = frappe.db.exists(
		"Attendance",
		{
			"employee": employee,
			"attendance_date": process_date,
			"docstatus": 1,
			"status": "On Leave",
		},
	)
	if leave_att:
		return f"Skipped {employee}: On Leave attendance exists"

	leave_app = frappe.db.exists(
		"Leave Application",
		{
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			"from_date": ["<=", process_date],
			"to_date": [">=", process_date],
		},
	)
	if leave_app:
		return f"Skipped {employee}: approved leave covers {process_date}"

	if force:
		existing = frappe.get_all(
			"Attendance",
			filters={
				"employee": employee,
				"attendance_date": process_date,
				"docstatus": ["<", 2],
			},
			fields=["name", "status", "docstatus"],
		)
		for row in existing:
			if row.status == "On Leave":
				continue
			doc = frappe.get_doc("Attendance", row.name)
			doc.flags.ignore_permissions = True
			frappe.db.sql(
				"update `tabEmployee Checkin` set attendance=null where attendance=%s",
				doc.name,
			)
			if doc.docstatus == 1:
				doc.cancel()
			elif doc.docstatus == 0:
				doc.delete()

	# If not force and attendance already exists, stop
	if frappe.db.exists(
		"Attendance",
		{"employee": employee, "attendance_date": process_date, "docstatus": ["<", 2]},
	):
		return f"Skipped {employee}: attendance already exists for {process_date}"

	start_dt = datetime.combine(process_date, time(0, 0, 0))
	end_dt = datetime.combine(process_date, time(23, 59, 59))
	checkins = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [start_dt, end_dt]]},
		fields=["name", "time", "log_type"],
		order_by="time asc",
	)
	in_logs = [c for c in checkins if c.log_type == "IN"]
	out_logs = [c for c in checkins if c.log_type == "OUT"]
	in_time = in_logs[0].time if in_logs else None
	out_time = out_logs[-1].time if out_logs else None

	emp_settings = get_policy_settings_for_employee(employee, process_date)
	eval_result = evaluate_attendance(
		employee=employee,
		process_date=process_date,
		in_time=in_time,
		out_time=out_time,
		settings=emp_settings,
	)

	att_dict = {
		"doctype": "Attendance",
		"employee": employee,
		"attendance_date": process_date,
		"shift": emp_settings.get("shift_name") or emp_data.default_shift,
		"status": eval_result["status"],
		"in_time": in_time,
		"out_time": out_time,
		"late_entry": eval_result["late_entry"],
		"early_exit": eval_result["early_exit"],
	}
	if frappe.get_meta("Attendance").has_field("custom_late_category"):
		att_dict["custom_late_category"] = eval_result.get("late_category") or ""
	if frappe.get_meta("Attendance").has_field("custom_attendance_remarks"):
		att_dict["custom_attendance_remarks"] = eval_result.get("remarks") or ""

	att = frappe.get_doc(att_dict)
	att.insert(ignore_permissions=True)
	att.submit()
	frappe.db.commit()

	return (
		f"Updated Attendance for {employee} on {process_date}: "
		f"{eval_result['status']} ({eval_result.get('remarks') or ''})"
	)


@frappe.whitelist()
def process_yesterday_attendance():
	"""Nightly job: sync punches, create checkins, then (re)build yesterday's Attendance."""
	today = frappe.utils.getdate()
	yesterday = frappe.utils.add_days(today, -1)
	sync_msg = get_and_update_attendance(from_date=yesterday, to_date=today)
	checkin_msg = process_raw_attendance(from_date=yesterday, to_date=yesterday)
	att_msg = process_employee_attendance(yesterday, force=True)
	return f"{sync_msg}\n{checkin_msg}\n{att_msg}"


@frappe.whitelist()
def process_attendance_range(from_date, to_date=None, force=False):
	"""Process Attendance for each working day in the date range (inclusive)."""
	start = frappe.utils.getdate(from_date)
	end = frappe.utils.getdate(to_date) if to_date else frappe.utils.getdate()
	if end < start:
		frappe.throw("to_date cannot be before from_date")

	results = []
	cur = start
	while cur <= end:
		try:
			results.append(process_employee_attendance(cur, force=force))
		except Exception as exc:
			frappe.log_error(title="Attendance range day failed", message=f"{cur}: {exc}")
			results.append(f"Failed {cur}: {exc}")
		cur = cur + timedelta(days=1)
	return "\n\n".join(results)
