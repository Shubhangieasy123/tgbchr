import frappe
from frappe import _
from frappe.utils import (
	date_diff,
	escape_html,
	get_url_to_form,
)

# Role whose users are CC'd on every email (same as Leave Application)
LEAVE_MANAGEMENT_ROLE = "Leave Management"

PENDING_STATE = "Pending for HOD approval"


# ============================================================
# 1. WORKFLOW APPROVER SECURITY
# ============================================================

def validate_workflow_approver(doc, method):

	old_doc = doc.get_doc_before_save()

	if not old_doc:
		return

	old_state = old_doc.get("workflow_state")
	new_state = doc.get("workflow_state")

	if old_state == PENDING_STATE and new_state == "Approved":
		ensure_hod_approver(doc, "approve")

	elif old_state == PENDING_STATE and new_state == "Rejected":
		ensure_hod_approver(doc, "reject")


# ============================================================
# 2. CHECK RESPECTIVE EMPLOYEE'S APPROVER
# ============================================================

def get_approver(doc):
	"""Approver is the Employer's Approver set on the Attendance Request."""

	return doc.get("custom_employers_approver")


def ensure_hod_approver(doc, action):

	if not doc.employee:
		frappe.throw(_("Employee is required."))

	approver = get_approver(doc)

	if not approver:
		frappe.throw(
			_("Employer's Approver is not set on this Attendance Request.")
		)

	if frappe.session.user != approver:
		frappe.throw(
			_(
				"Only the assigned Approver ({0}) can {1} "
				"this Attendance Request."
			).format(approver, action),
			frappe.PermissionError,
		)


# ============================================================
# 3. HANDLE WORKFLOW CHANGES
# ============================================================

def handle_workflow_update(doc, method):

	old_doc = doc.get_doc_before_save()

	if not old_doc:
		return

	old_state = old_doc.get("workflow_state")
	new_state = doc.get("workflow_state")

	if old_state == "Draft" and new_state == PENDING_STATE:
		notify_hod_approver(doc)

	elif old_state == PENDING_STATE and new_state == "Approved":
		notify_request_result(doc, "Approved")

	elif old_state == PENDING_STATE and new_state == "Rejected":
		notify_request_result(doc, "Rejected")


# ============================================================
# 4. EMAIL HELPERS
# ============================================================

def get_user_email(user):

	if not user:
		return None

	if "@" in str(user):
		return user

	return frappe.db.get_value("User", user, "email")


def get_employee_email(employee):

	if not employee:
		return None

	for field in ("company_email", "personal_email"):
		email = frappe.db.get_value("Employee", employee, field)
		if email:
			return email

	user_id = frappe.db.get_value("Employee", employee, "user_id")

	if user_id:
		return get_user_email(user_id)

	return None


def get_leave_management_emails(exclude_email=None):

	users = frappe.get_all(
		"Has Role",
		filters={
			"role": LEAVE_MANAGEMENT_ROLE,
			"parenttype": "User",
		},
		fields=["parent"],
	)

	emails = set()

	for row in users:
		email = get_user_email(row.parent)

		if not email or email == exclude_email:
			continue

		emails.add(email)

	return list(emails)


def _cell(label, value, width="33.33%", border_right=True):

	border = "border-right:1px solid #eeeeee;" if border_right else ""

	return f"""
		<td style="width:{width};padding:14px 15px;{border}border-bottom:1px solid #eeeeee;">
			<div style="font-size:11px;color:#888888;text-transform:uppercase;">{label}</div>
			<div style="margin-top:5px;font-weight:bold;">{value}</div>
		</td>
	"""


def build_email_html(doc, greeting, intro, button_label, result=None):
	"""One shared template for the approver mail and the result mail."""

	link = get_url_to_form(doc.doctype, doc.name)
	employee = escape_html(doc.employee_name or doc.employee or "")

	total_days = date_diff(doc.to_date, doc.from_date) + 1
	if doc.get("half_day"):
		total_days -= 0.5

	half_day_text = "-"
	if doc.get("half_day"):
		half_day_text = str(doc.get("half_day_date") or "Yes")

	status_block = ""
	if result:
		status_block = f"""
			<table style="width:100%;border-collapse:collapse;border:1px solid #dddddd;border-top:none;">
				<tr>
					<td style="padding:15px;text-align:center;font-size:16px;font-weight:bold;">
						Application Status: <b>{result}</b>
					</td>
				</tr>
			</table>
		"""

	return f"""
		<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333333;max-width:750px;margin:0 auto;background-color:#ffffff;">

			<p>{greeting}</p>
			<p>{intro}</p>

			<table style="width:100%;border-collapse:collapse;margin-top:20px;border:1px solid #dddddd;">
				<tr>
					<td style="padding:16px;background-color:#f5f7fa;border-bottom:1px solid #dddddd;">
						<div style="font-size:18px;font-weight:bold;color:#222222;">Attendance Request</div>
						<div style="font-size:13px;color:#777777;margin-top:5px;">
							Request No: <b>{doc.name}</b>
						</div>
					</td>
				</tr>
			</table>

			<table style="width:100%;border-collapse:collapse;border-left:1px solid #dddddd;border-right:1px solid #dddddd;">
				<tr>
					{_cell("Employee", employee, "50%")}
					{_cell("Employee ID", doc.employee, "50%", border_right=False)}
				</tr>
			</table>

			<table style="width:100%;border-collapse:collapse;border:1px solid #dddddd;border-top:none;">
				<tr>
					{_cell("Request Type", escape_html(doc.get("reason") or "-"))}
					{_cell("From Date", doc.from_date)}
					{_cell("To Date", doc.to_date, border_right=False)}
				</tr>
				<tr>
					{_cell("Total Days", total_days)}
					{_cell("Half Day", half_day_text)}
					{_cell("Shift", escape_html(doc.get("shift") or "-"), border_right=False)}
				</tr>
			</table>

			{status_block}

			<table style="width:100%;border-collapse:collapse;border:1px solid #dddddd;border-top:none;">
				<tr>
					<td style="padding:12px 15px;background-color:#fafafa;border-bottom:1px solid #dddddd;font-weight:bold;">
						Explanation
					</td>
				</tr>
				<tr>
					<td style="padding:15px;line-height:1.6;color:#555555;">
						{escape_html(doc.get("explanation") or "No explanation provided.")}
					</td>
				</tr>
			</table>

			<table style="width:100%;border-collapse:collapse;margin-top:20px;">
				<tr>
					<td style="text-align:center;padding:10px;">
						<a href="{link}" style="display:inline-block;padding:12px 25px;background-color:#2490ef;color:#ffffff;text-decoration:none;border-radius:4px;font-weight:bold;">
							{button_label}
						</a>
					</td>
				</tr>
			</table>

			<p style="font-size:12px;color:#999999;margin-top:20px;">
				This is a system-generated email. Please do not reply to this message.
			</p>

		</div>
	"""


# ============================================================
# 5. EMAIL APPROVER
# ============================================================

def notify_hod_approver(doc):

	approver = get_approver(doc)

	if not approver:
		return

	hod_email = get_user_email(approver)

	if not hod_email:
		frappe.log_error(
			f"No email found for Approver: {approver}",
			"Attendance Request HOD Email",
		)
		return

	cc_recipients = get_leave_management_emails(exclude_email=hod_email)

	employee = doc.employee_name or doc.employee

	message = build_email_html(
		doc,
		greeting="Hi,",
		intro=(
			f"<b>{escape_html(employee)}</b> has submitted an "
			f"<b>Attendance Request</b> which is pending your approval."
		),
		button_label="Open Attendance Request",
	)

	frappe.sendmail(
		recipients=[hod_email],
		cc=cc_recipients,
		subject=_(
			"Attendance Request {0} from {1} - Pending for Approval"
		).format(doc.name, employee),
		message=message,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)


# ============================================================
# 6. APPROVED / REJECTED EMAIL
# ============================================================

def notify_request_result(doc, result):

	employee_email = get_employee_email(doc.employee)

	cc_recipients = get_leave_management_emails(exclude_email=employee_email)

	employee = doc.employee_name or doc.employee

	# Built once, so it is also available when the employee has no email
	message = build_email_html(
		doc,
		greeting=f"Hi {escape_html(employee)},",
		intro=f"Your <b>Attendance Request</b> has been <b>{result}</b>.",
		button_label="View Attendance Request",
		result=result,
	)

	subject = _("Your Attendance Request {0} - {1}").format(doc.name, result)

	if employee_email:
		frappe.sendmail(
			recipients=[employee_email],
			cc=cc_recipients,
			subject=subject,
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)

	elif cc_recipients:
		# Employee has no email: send to Leave Management users instead
		frappe.sendmail(
			recipients=cc_recipients,
			subject=subject,
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)