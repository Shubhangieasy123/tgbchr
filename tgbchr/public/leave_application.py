import frappe
from frappe import _
from frappe.utils import (
	getdate,
	today,
	get_url_to_form,
)


# ============================================================
# 1. LEAVE DATE VALIDATION
# ============================================================

def validate_leave_application(doc, method):

	if not doc.from_date:
		return

	# Sick Leave can be applied immediately
	if doc.leave_type == "Sick Leave":
		return

	# Other leave types must be applied at least 1 day before
	if getdate(doc.from_date) <= getdate(today()):
		frappe.throw(
			_(
				"Leave Application must be requested at least 1 day "
				"before the leave date."
			)
		)


# ============================================================
# 2. WORKFLOW APPROVER SECURITY
# ============================================================

def validate_workflow_approver(doc, method):

	old_doc = doc.get_doc_before_save()

	if not old_doc:
		return

	old_state = old_doc.workflow_state
	new_state = doc.workflow_state

	if (
		old_state == "Pending for HOD approval"
		and new_state == "Approved"
	):
		ensure_hod_approver(doc, "approve")

	elif (
		old_state == "Pending for HOD approval"
		and new_state == "Rejected"
	):
		ensure_hod_approver(doc, "reject")


# ============================================================
# 3. CHECK RESPECTIVE EMPLOYEE'S LEAVE APPROVER
# ============================================================

def ensure_hod_approver(doc, action):

	if not doc.employee:
		frappe.throw(
			_("Employee is required.")
		)

	leave_approver = frappe.db.get_value(
		"Employee",
		doc.employee,
		"leave_approver",
	)

	if not leave_approver:
		frappe.throw(
			_(
				"No Leave Approver is set for employee {0}."
			).format(
				doc.employee
			)
		)

	if frappe.session.user != leave_approver:
		frappe.throw(
			_(
				"Only the assigned Leave Approver ({0}) can {1} "
				"this Leave Application."
			).format(
				leave_approver,
				action,
			),
			frappe.PermissionError,
		)


# ============================================================
# 4. HANDLE WORKFLOW CHANGES
# ============================================================

def handle_workflow_update(doc, method):

	old_doc = doc.get_doc_before_save()

	if not old_doc:
		return

	old_state = old_doc.workflow_state
	new_state = doc.workflow_state

	# --------------------------------------------------------
	# draft -> Pending for HOD approval
	# --------------------------------------------------------

	if (
		old_state == "draft"
		and new_state == "Pending for HOD approval"
	):

		doc.db_set("status", "Open")

		notify_hod_approver(doc)

	# --------------------------------------------------------
	# Pending -> Approved
	# --------------------------------------------------------

	elif (
		old_state == "Pending for HOD approval"
		and new_state == "Approved"
	):

		doc.db_set("status", "Approved")

		notify_request_result(doc, "Approved")

	# --------------------------------------------------------
	# Pending -> Rejected
	# --------------------------------------------------------

	elif (
		old_state == "Pending for HOD approval"
		and new_state == "Rejected"
	):

		doc.db_set("status", "Rejected")

		notify_request_result(doc, "Rejected")


# ============================================================
# 5. GET USER EMAIL
# ============================================================

def get_user_email(user):

	if not user:
		return None

	if "@" in str(user):
		return user

	return frappe.db.get_value(
		"User",
		user,
		"email",
	)


# ============================================================
# 6. GET EMPLOYEE EMAIL
# ============================================================

def get_employee_email(employee):

	if not employee:
		return None

	# First try company email
	email = frappe.db.get_value(
		"Employee",
		employee,
		"company_email",
	)

	if email:
		return email

	# Then personal email
	email = frappe.db.get_value(
		"Employee",
		employee,
		"personal_email",
	)

	if email:
		return email

	# Finally try linked User
	user_id = frappe.db.get_value(
		"Employee",
		employee,
		"user_id",
	)

	if user_id:
		return get_user_email(user_id)

	return None


# ============================================================
# 7. GET LEAVE MANAGEMENT USERS
# ============================================================

def get_leave_management_emails(exclude_email=None):

	users = frappe.get_all(
		"Has Role",
		filters={
			"role": "Leave Management",
			"parenttype": "User",
		},
		fields=["parent"],
	)

	emails = []

	for row in users:

		email = get_user_email(row.parent)

		if not email:
			continue

		if exclude_email and email == exclude_email:
			continue

		emails.append(email)

	# Remove duplicate emails
	return list(set(emails))


# ============================================================
# 8. EMAIL LEAVE APPROVER
# ============================================================

def notify_hod_approver(doc):

	if not doc.leave_approver:
		return

	hod_email = get_user_email(
		doc.leave_approver
	)

	if not hod_email:

		frappe.log_error(
			f"No email found for Leave Approver: {doc.leave_approver}",
			"Leave Application HOD Email",
		)

		return

	# --------------------------------------------------------
	# Leave Management users in CC
	# --------------------------------------------------------

	cc_recipients = get_leave_management_emails(
		exclude_email=hod_email
	)

	link = get_url_to_form(
		doc.doctype,
		doc.name,
	)

	employee = doc.employee_name or doc.employee

	message = f"""
		<div style="
			font-family: Arial, Helvetica, sans-serif;
			font-size: 14px;
			color: #333333;
			max-width: 750px;
			margin: 0 auto;
			background-color: #ffffff;
		">

			<p>Hi,</p>

			<p>
				<b>{frappe.utils.escape_html(employee)}</b> has submitted
				a <b>Leave Application</b> which is pending your approval.
			</p>

			<!-- ================================================= -->
			<!-- LEAVE APPLICATION HEADER -->
			<!-- ================================================= -->

			<table style="
				width: 100%;
				border-collapse: collapse;
				margin-top: 20px;
				border: 1px solid #dddddd;
			">

				<tr>
					<td style="
						padding: 16px;
						background-color: #f5f7fa;
						border-bottom: 1px solid #dddddd;
					">

						<div style="
							font-size: 18px;
							font-weight: bold;
							color: #222222;
						">
							Leave Application
						</div>

						<div style="
							font-size: 13px;
							color: #777777;
							margin-top: 5px;
						">
							Application No: <b>{doc.name}</b>
						</div>

					</td>
				</tr>

			</table>


			<!-- ================================================= -->
			<!-- EMPLOYEE DETAILS -->
			<!-- ================================================= -->

			<table style="
				width: 100%;
				border-collapse: collapse;
				border-left: 1px solid #dddddd;
				border-right: 1px solid #dddddd;
			">

				<tr>

					<td style="
						width: 50%;
						padding: 12px 15px;
						border-bottom: 1px solid #eeeeee;
						border-right: 1px solid #eeeeee;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							Employee
						</div>

						<div style="
							margin-top: 4px;
							font-weight: bold;
						">
							{frappe.utils.escape_html(employee)}
						</div>

					</td>

					<td style="
						width: 50%;
						padding: 12px 15px;
						border-bottom: 1px solid #eeeeee;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							Employee ID
						</div>

						<div style="
							margin-top: 4px;
							font-weight: bold;
						">
							{doc.employee}
						</div>

					</td>

				</tr>

			</table>


			<!-- ================================================= -->
			<!-- LEAVE DETAILS -->
			<!-- ================================================= -->

			<table style="
				width: 100%;
				border-collapse: collapse;
				border: 1px solid #dddddd;
				border-top: none;
			">

				<tr>

					<td style="
						width: 33.33%;
						padding: 14px 15px;
						border-right: 1px solid #eeeeee;
						border-bottom: 1px solid #eeeeee;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							Leave Type
						</div>

						<div style="
							margin-top: 5px;
							font-weight: bold;
						">
							{frappe.utils.escape_html(doc.leave_type or "-")}
						</div>

					</td>

					<td style="
						width: 33.33%;
						padding: 14px 15px;
						border-right: 1px solid #eeeeee;
						border-bottom: 1px solid #eeeeee;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							From Date
						</div>

						<div style="
							margin-top: 5px;
							font-weight: bold;
						">
							{doc.from_date}
						</div>

					</td>

					<td style="
						width: 33.33%;
						padding: 14px 15px;
						border-bottom: 1px solid #eeeeee;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							To Date
						</div>

						<div style="
							margin-top: 5px;
							font-weight: bold;
						">
							{doc.to_date}
						</div>

					</td>

				</tr>

				<tr>

					<td colspan="3" style="
						padding: 14px 15px;
					">

						<div style="
							font-size: 11px;
							color: #888888;
							text-transform: uppercase;
						">
							Total Leave Days
						</div>

						<div style="
							margin-top: 5px;
							font-weight: bold;
							font-size: 15px;
						">
							{doc.total_leave_days}
						</div>

					</td>

				</tr>

			</table>


			<!-- ================================================= -->
			<!-- DESCRIPTION -->
			<!-- ================================================= -->

			<table style="
				width: 100%;
				border-collapse: collapse;
				border: 1px solid #dddddd;
				border-top: none;
			">

				<tr>

					<td style="
						padding: 12px 15px;
						background-color: #fafafa;
						border-bottom: 1px solid #dddddd;
						font-weight: bold;
						font-size: 14px;
						color: #444444;
					">
						Reason
					</td>

				</tr>

				<tr>

					<td style="
						padding: 15px;
						line-height: 1.6;
						color: #555555;
					">
						{frappe.utils.escape_html(
							doc.description or "No description provided."
						)}
					</td>

				</tr>

			</table>


			<!-- ================================================= -->
			<!-- ACTION -->
			<!-- ================================================= -->

			<table style="
				width: 100%;
				border-collapse: collapse;
				margin-top: 20px;
			">

				<tr>

					<td style="
						text-align: center;
						padding: 10px;
					">

						<a href="{link}" style="
							display: inline-block;
							padding: 12px 25px;
							background-color: #2490ef;
							color: #ffffff;
							text-decoration: none;
							border-radius: 4px;
							font-weight: bold;
						">
							Open Leave Application
						</a>

					</td>

				</tr>

			</table>


			<p style="
				font-size: 12px;
				color: #999999;
				margin-top: 20px;
			">
				This is a system-generated email. Please do not reply to this message.
			</p>

		</div>
	"""

	frappe.sendmail(
		recipients=[hod_email],
		cc=cc_recipients,
		subject=_(
			"Leave Application {0} from {1} - Pending for Approval"
		).format(
			doc.name,
			employee,
		),
		message=message,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)


# ============================================================
# 9. APPROVED / REJECTED EMAIL
# ============================================================

def notify_request_result(doc, result):

	employee_email = get_employee_email(
		doc.employee
	)

	# --------------------------------------------------------
	# Leave Management users will receive the SAME email
	# in CC
	# --------------------------------------------------------

	cc_recipients = get_leave_management_emails(
		exclude_email=employee_email
	)

	link = get_url_to_form(
		doc.doctype,
		doc.name,
	)

	employee = doc.employee_name or doc.employee

	# ========================================================
	# EMAIL TO EMPLOYEE
	# Leave Management users are in CC
	# ========================================================

	if employee_email:

		employee_message = f"""
			<div style="
				font-family: Arial, Helvetica, sans-serif;
				font-size: 14px;
				color: #333333;
				max-width: 750px;
				margin: 0 auto;
				background-color: #ffffff;
			">

				<p>
					Hi {frappe.utils.escape_html(employee)},
				</p>

				<p>
					Your <b>Leave Application</b> has been
					<b>{result}</b>.
				</p>


				<!-- HEADER -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					border: 1px solid #dddddd;
				">

					<tr>

						<td style="
							padding: 16px;
							background-color: #f5f7fa;
							border-bottom: 1px solid #dddddd;
						">

							<div style="
								font-size: 18px;
								font-weight: bold;
								color: #222222;
							">
								Leave Application
							</div>

							<div style="
								font-size: 13px;
								color: #777777;
								margin-top: 5px;
							">
								Application No: <b>{doc.name}</b>
							</div>

						</td>

					</tr>

				</table>


				<!-- EMPLOYEE DETAILS -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					border-left: 1px solid #dddddd;
					border-right: 1px solid #dddddd;
				">

					<tr>

						<td style="
							width: 50%;
							padding: 12px 15px;
							border-bottom: 1px solid #eeeeee;
							border-right: 1px solid #eeeeee;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								Employee
							</div>

							<div style="
								margin-top: 4px;
								font-weight: bold;
							">
								{frappe.utils.escape_html(employee)}
							</div>

						</td>

						<td style="
							width: 50%;
							padding: 12px 15px;
							border-bottom: 1px solid #eeeeee;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								Employee ID
							</div>

							<div style="
								margin-top: 4px;
								font-weight: bold;
							">
								{doc.employee}
							</div>

						</td>

					</tr>

				</table>


				<!-- LEAVE DETAILS -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					border: 1px solid #dddddd;
					border-top: none;
				">

					<tr>

						<td style="
							width: 33.33%;
							padding: 14px 15px;
							border-right: 1px solid #eeeeee;
							border-bottom: 1px solid #eeeeee;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								Leave Type
							</div>

							<div style="
								margin-top: 5px;
								font-weight: bold;
							">
								{frappe.utils.escape_html(
									doc.leave_type or "-"
								)}
							</div>

						</td>

						<td style="
							width: 33.33%;
							padding: 14px 15px;
							border-right: 1px solid #eeeeee;
							border-bottom: 1px solid #eeeeee;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								From Date
							</div>

							<div style="
								margin-top: 5px;
								font-weight: bold;
							">
								{doc.from_date}
							</div>

						</td>

						<td style="
							width: 33.33%;
							padding: 14px 15px;
							border-bottom: 1px solid #eeeeee;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								To Date
							</div>

							<div style="
								margin-top: 5px;
								font-weight: bold;
							">
								{doc.to_date}
							</div>

						</td>

					</tr>

					<tr>

						<td colspan="3" style="
							padding: 14px 15px;
						">

							<div style="
								font-size: 11px;
								color: #888888;
								text-transform: uppercase;
							">
								Total Leave Days
							</div>

							<div style="
								margin-top: 5px;
								font-weight: bold;
								font-size: 15px;
							">
								{doc.total_leave_days}
							</div>

						</td>

					</tr>

				</table>


				<!-- STATUS -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					border: 1px solid #dddddd;
					border-top: none;
				">

					<tr>

						<td style="
							padding: 15px;
							text-align: center;
							font-size: 16px;
							font-weight: bold;
						">

							Application Status:
							<b>{result}</b>

						</td>

					</tr>

				</table>


				<!-- DESCRIPTION -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					border: 1px solid #dddddd;
					border-top: none;
				">

					<tr>

						<td style="
							padding: 12px 15px;
							background-color: #fafafa;
							border-bottom: 1px solid #dddddd;
							font-weight: bold;
						">
							Reason
						</td>

					</tr>

					<tr>

						<td style="
							padding: 15px;
							line-height: 1.6;
							color: #555555;
						">
							{frappe.utils.escape_html(
								doc.description or "No description provided."
							)}
						</td>

					</tr>

				</table>


				<!-- LINK -->

				<table style="
					width: 100%;
					border-collapse: collapse;
					margin-top: 20px;
				">

					<tr>

						<td style="
							text-align: center;
							padding: 10px;
						">

							<a href="{link}" style="
								display: inline-block;
								padding: 12px 25px;
								background-color: #2490ef;
								color: #ffffff;
								text-decoration: none;
								border-radius: 4px;
								font-weight: bold;
							">
								View Leave Application
							</a>

						</td>

					</tr>

				</table>


				<p style="
					font-size: 12px;
					color: #999999;
					margin-top: 20px;
				">
					This is a system-generated email. Please do not reply to this message.
				</p>

			</div>
		"""

		frappe.sendmail(
			recipients=[employee_email],
			cc=cc_recipients,
			subject=_(
				"Your Leave Application {0} - {1}"
			).format(
				doc.name,
				result,
			),
			message=employee_message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)

	else:

		# --------------------------------------------------------
		# Employee has no email.
		# Send to Leave Management users instead.
		# --------------------------------------------------------

		if cc_recipients:

			frappe.sendmail(
				recipients=cc_recipients,
				subject=_(
					"Leave Application {0} - {1}"
				).format(
					doc.name,
					result,
				),
				message=employee_message,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
			)
