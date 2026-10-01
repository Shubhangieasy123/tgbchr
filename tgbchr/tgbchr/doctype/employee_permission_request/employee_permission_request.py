# Copyright (c) 2026, TGBC and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	getdate,
	get_datetime,
	time_diff_in_hours,
	add_days,
	get_url_to_form,
)

from tgbchr.attendance_policy import get_policy_settings


class EmployeePermissionRequest(Document):
	def validate(self):
		self.calculate_hours()
		self.validate_hours_limit()
		self.validate_monthly_limit()
		self.validate_not_consecutive()
		self.validate_hod_approver()

	# ----------------------------------------------------------------
	# WORKFLOW APPROVER SECURITY
	# ----------------------------------------------------------------

	def before_save(self):
		"""
		Only the employee's assigned HOD Approver can
		Approve or Reject the workflow request.
		"""

		self.validate_workflow_approver()

	# ----------------------------------------------------------------
	# WORKFLOW TRANSITION HANDLING
	# ----------------------------------------------------------------

	def on_update(self):
		"""
		Handle emails and status changes when the workflow state changes.
		"""

		old_doc = self.get_doc_before_save()

		if not old_doc:
			return

		old_state = old_doc.workflow_state
		new_state = self.workflow_state

		# ------------------------------------------------------------
		# draft -> Pending for HOD approval
		# ------------------------------------------------------------

		if (
			old_state == "draft"
			and new_state == "Pending for HOD approval"
		):

			# Keep status as Draft
			if self.status != "Draft":
				self.db_set("status", "Draft")

			# Send email to the respective HOD Approver
			# Leave Management users are added in CC
			self.notify_hod_approver()

		# ------------------------------------------------------------
		# Pending for HOD approval -> Approved
		# ------------------------------------------------------------

		elif (
			old_state == "Pending for HOD approval"
			and new_state == "Approved"
		):

			# Change status to Approved
			if self.status != "Approved":
				self.db_set("status", "Approved")

			# Notify employee
			# Leave Management users are added in CC
			self.notify_request_result()

		# ------------------------------------------------------------
		# Pending for HOD approval -> Rejected
		# ------------------------------------------------------------

		elif (
			old_state == "Pending for HOD approval"
			and new_state == "Rejected"
		):

			# Change status to Rejected
			if self.status != "Rejected":
				self.db_set("status", "Rejected")

			# Notify employee
			# Leave Management users are added in CC
			self.notify_request_result()

	# ----------------------------------------------------------------
	# WORKFLOW APPROVER VALIDATION
	# ----------------------------------------------------------------

	def validate_workflow_approver(self):

		old_doc = self.get_doc_before_save()

		if not old_doc:
			return

		old_state = old_doc.workflow_state
		new_state = self.workflow_state

		# ------------------------------------------------------------
		# Approve
		# ------------------------------------------------------------

		if (
			old_state == "Pending for HOD approval"
			and new_state == "Approved"
		):
			self.ensure_hod_approver("approve")

		# ------------------------------------------------------------
		# Reject
		# ------------------------------------------------------------

		elif (
			old_state == "Pending for HOD approval"
			and new_state == "Rejected"
		):
			self.ensure_hod_approver("reject")

	# ----------------------------------------------------------------
	# DOCUMENT EVENTS
	# ----------------------------------------------------------------

	def after_insert(self):
		"""
		Do not send the HOD email when the document is created.

		The email is sent only when the employee clicks
		'Sending for HOD approval'.
		"""
		pass

	def before_submit(self):
		self.ensure_hod_approver("submit")

		self.status = "Approved"

	def before_update_after_submit(self):
		# Only the assigned HOD approver can edit a submitted request
		self.ensure_hod_approver("update")

	def before_cancel(self):
		# Only the assigned HOD approver can cancel a submitted request
		self.ensure_hod_approver("cancel")

	def on_submit(self):
		# After approval, rebuild that day's Attendance
		# so Summary reflects permission
		if self.status == "Approved" and self.employee and self.permission_date:
			self._refresh_attendance()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

		# Revert attendance without this permission
		if self.employee and self.permission_date:
			self._refresh_attendance()

	# ----------------------------------------------------------------
	# APPROVER SECURITY
	# ----------------------------------------------------------------

	def ensure_hod_approver(self, action):

		if frappe.session.user != self.hod_approver:

			frappe.throw(
				_(
					"Only the assigned HOD Approver ({0}) can {1} this request"
				).format(
					self.hod_approver,
					action,
				),
				frappe.PermissionError,
			)

	# ----------------------------------------------------------------
	# HOD APPROVER EMAIL
	# ----------------------------------------------------------------

	def notify_hod_approver(self):

		if not self.hod_approver:
			return

		hod_email = self.get_user_email(self.hod_approver)

		if not hod_email:

			frappe.log_error(
				f"No email found for HOD Approver: {self.hod_approver}",
				"Permission Request HOD Email",
			)

			return

		# ------------------------------------------------------------
		# Get Leave Management users for CC
		# ------------------------------------------------------------

		leave_management_users = frappe.get_all(
			"Has Role",
			filters={
				"role": "Leave Management",
				"parenttype": "User",
			},
			fields=["parent"],
		)

		cc_recipients = []

		for row in leave_management_users:

			email = self.get_user_email(row.parent)

			if email and email != hod_email:
				cc_recipients.append(email)

		# Remove duplicate emails
		cc_recipients = list(set(cc_recipients))

		link = get_url_to_form(
			self.doctype,
			self.name,
		)

		employee = self.employee_name or self.employee

		message = f"""
			<div style="font-family: Arial, sans-serif; font-size: 14px; color: #333333;">

				<p>Hi,</p>

				<p>
					<b>{frappe.utils.escape_html(employee)}</b> has submitted a
					<b>Permission Request</b> which is pending your approval.
				</p>

				<table style="width: 100%; max-width: 700px; border-collapse: collapse; margin: 20px 0;">

					<tr>
						<th style="border: 1px solid #d9d9d9; padding: 10px; text-align: left; background-color: #f5f5f5;">
							Particulars
						</th>

						<th style="border: 1px solid #d9d9d9; padding: 10px; text-align: left; background-color: #f5f5f5;">
							Details
						</th>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Request</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{self.name}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Employee</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{frappe.utils.escape_html(employee)}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Date</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{frappe.format(
								self.permission_date,
								{"fieldtype": "Date"}
							)}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>From</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{self.from_time}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>To</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{self.to_time}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Hours</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{self.hours}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Reason</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							{frappe.utils.escape_html(self.reason or "-")}
						</td>
					</tr>

					<tr>
						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							<b>Status</b>
						</td>

						<td style="border: 1px solid #d9d9d9; padding: 10px;">
							Pending for HOD Approval
						</td>
					</tr>

				</table>

				<p>
					Kindly review the Permission Request and take the appropriate action.
				</p>

				<p>
					<a href="{link}" style="color: #2490ef; text-decoration: none;">
						Open the request
					</a>
				</p>

				<p style="font-size: 12px; color: #b0b0b0;">
					This is a system-generated email. Please do not reply to this message.
				</p>

			</div>
		"""

		frappe.sendmail(
			recipients=[hod_email],
			cc=cc_recipients,
			subject=_(
				"Permission Request {0} from {1} - Pending for Approval"
			).format(
				self.name,
				employee,
			),
			message=message,
			reference_doctype=self.doctype,
			reference_name=self.name,
		)

	# ----------------------------------------------------------------
	# APPROVED / REJECTED EMAIL
	# ----------------------------------------------------------------

	def notify_request_result(self):

		employee_email = self.get_employee_email()

		# ------------------------------------------------------------
		# Get Leave Management users for CC
		# ------------------------------------------------------------

		leave_management_users = frappe.get_all(
			"Has Role",
			filters={
				"role": "Leave Management",
				"parenttype": "User",
			},
			fields=["parent"],
		)

		cc_recipients = []

		for row in leave_management_users:

			email = self.get_user_email(row.parent)

			# Do not add employee to CC if employee also has
			# Leave Management role
			if email and email != employee_email:
				cc_recipients.append(email)

		# Remove duplicate emails
		cc_recipients = list(set(cc_recipients))

		link = get_url_to_form(
			self.doctype,
			self.name,
		)

		employee = self.employee_name or self.employee

		# ============================================================
		# EMAIL TO EMPLOYEE
		# Leave Management users receive the same email in CC
		# ============================================================

		if employee_email:

			employee_message = f"""
				<div style="font-family: Arial, sans-serif; font-size: 14px; color: #333333;">

					<p>Hi {frappe.utils.escape_html(employee)},</p>

					<p>
						Your <b>Permission Request</b> has been
						<b>{self.status}</b>.
					</p>

					<table style="width: 100%; max-width: 700px; border-collapse: collapse; margin: 20px 0;">

						<tr>
							<th style="border: 1px solid #d9d9d9; padding: 10px; text-align: left; background-color: #f5f5f5;">
								Particulars
							</th>

							<th style="border: 1px solid #d9d9d9; padding: 10px; text-align: left; background-color: #f5f5f5;">
								Details
							</th>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>Request</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{self.name}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>Date</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{frappe.format(
									self.permission_date,
									{"fieldtype": "Date"}
								)}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>From</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{self.from_time}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>To</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{self.to_time}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>Hours</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{self.hours}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>Reason</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{frappe.utils.escape_html(self.reason or "-")}
							</td>
						</tr>

						<tr>
							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								<b>Status</b>
							</td>

							<td style="border: 1px solid #d9d9d9; padding: 10px;">
								{self.status}
							</td>
						</tr>

					</table>

					<p>
						<a href="{link}" style="color: #2490ef; text-decoration: none;">
							View Permission Request
						</a>
					</p>

					<p style="font-size: 12px; color: #b0b0b0;">
						This is a system-generated email. Please do not reply to this message.
					</p>

				</div>
			"""

			frappe.sendmail(
				recipients=[employee_email],
				cc=cc_recipients,
				subject=_(
					"Your Permission Request {0} - {1}"
				).format(
					self.name,
					self.status,
				),
				message=employee_message,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

	# ----------------------------------------------------------------
	# EMAIL HELPERS
	# ----------------------------------------------------------------

	def get_user_email(self, user):

		if not user:
			return None

		# If the value itself is already an email
		if "@" in str(user):
			return user

		email = frappe.db.get_value(
			"User",
			user,
			"email",
		)

		return email

	def get_employee_email(self):

		if not self.employee:
			return None

		# First try company email
		email = frappe.db.get_value(
			"Employee",
			self.employee,
			"company_email",
		)

		if email:
			return email

		# Then personal email
		email = frappe.db.get_value(
			"Employee",
			self.employee,
			"personal_email",
		)

		if email:
			return email

		# Finally try linked User
		user_id = frappe.db.get_value(
			"Employee",
			self.employee,
			"user_id",
		)

		if user_id:
			return self.get_user_email(user_id)

		return None

	# ----------------------------------------------------------------
	# ATTENDANCE
	# ----------------------------------------------------------------

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

	# ----------------------------------------------------------------
	# VALIDATIONS
	# ----------------------------------------------------------------

	def validate_hod_approver(self):
		"""HOD approver must be the employee's own leave approver."""

		if not self.employee:
			return

		leave_approver = frappe.db.get_value(
			"Employee",
			self.employee,
			"leave_approver",
		)

		if not leave_approver:

			frappe.throw(
				_("No Leave Approver is set for employee {0}").format(
					self.employee
				)
			)

		if self.hod_approver != leave_approver:

			frappe.throw(
				_(
					"HOD Approver must be {0}, the Leave Approver of {1}"
				).format(
					leave_approver,
					self.employee,
				)
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
