# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import add_days, add_months, comma_sep, getdate, today

from erpnext.setup.doctype.employee.employee import get_all_employee_emails, get_employee_email

from hrms.hr.utils import get_holidays_for_employee


# -----------------
# HOLIDAY REMINDERS
# -----------------
def send_reminders_in_advance_weekly():
	to_send_in_advance = int(frappe.db.get_single_value("HR Settings", "send_holiday_reminders"))
	frequency = frappe.db.get_single_value("HR Settings", "frequency")
	if not (to_send_in_advance and frequency == "Weekly"):
		return

	send_advance_holiday_reminders("Weekly")


def send_reminders_in_advance_monthly():
	to_send_in_advance = int(frappe.db.get_single_value("HR Settings", "send_holiday_reminders"))
	frequency = frappe.db.get_single_value("HR Settings", "frequency")
	if not (to_send_in_advance and frequency == "Monthly"):
		return

	send_advance_holiday_reminders("Monthly")


def send_advance_holiday_reminders(frequency):
	"""Send Holiday Reminders in Advance to Employees
	`frequency` (str): 'Weekly' or 'Monthly'
	"""
	if frequency == "Weekly":
		start_date = getdate()
		end_date = add_days(getdate(), 7)
	elif frequency == "Monthly":
		# Sent on 1st of every month
		start_date = getdate()
		end_date = add_months(getdate(), 1)
	else:
		return

	employees = frappe.db.get_all("Employee", filters={"status": "Active"}, pluck="name")
	for employee in employees:
		holidays = get_holidays_for_employee(
			employee, start_date, end_date, only_non_weekly=True, raise_exception=False
		)

		send_holidays_reminder_in_advance(employee, holidays)


def send_holidays_reminder_in_advance(employee, holidays):
	if not holidays:
		return

	employee_doc = frappe.get_doc("Employee", employee)
	employee_email = get_employee_email(employee_doc)
	frequency = frappe.db.get_single_value("HR Settings", "frequency")
	sender_email = get_sender_email()
	email_header = _("Holidays this Month.") if frequency == "Monthly" else _("Holidays this Week.")
	frappe.sendmail(
		sender=sender_email,
		recipients=[employee_email],
		subject=_("Upcoming Holidays Reminder"),
		template="holiday_reminder",
		args=dict(
			reminder_text=_("Hey {}! This email is to remind you about the upcoming holidays.").format(
				employee_doc.get("first_name")
			),
			message=_("Below is the list of upcoming holidays for you:"),
			advance_holiday_reminder=True,
			holidays=holidays,
			frequency=frequency[:-2],
		),
		header=email_header,
	)


# ------------------
# BIRTHDAY REMINDERS
# ------------------
@frappe.whitelist()
def send_birthday_reminders():
    """Send Employee Birthday Reminders only to their managers (reports_to hierarchy)."""
    print("Executing send_birthday_reminders...")

    to_send = int(frappe.db.get_single_value("HR Settings", "send_birthday_reminders"))
    print(f"Send Birthday Reminders Enabled: {to_send}")

    if not to_send:
        print("Birthday Reminders are disabled. Exiting function.")
        return

    sender = get_sender_email()
    print(f"Sender Email: {sender}")

    employees_born_today = get_employees_who_are_born_today()
    print(f"Employees Having Birthday Today: {employees_born_today}")

    message = "A friendly reminder to celebrate our team member’s birthday today! 🎉"

    for company, birthday_persons in employees_born_today.items():
        for person in birthday_persons:
            print(f"Processing employee: {person['user_id']}")

            employee_name = frappe.get_value("Employee", {"user_id": person["user_id"]}, "name")
            if not employee_name:
                print(f"Employee record not found for {person['user_id']}. Skipping.")
                continue

            employee_doc = frappe.get_doc("Employee", employee_name)
            all_employee_emails = frappe.get_all(
				"Employee",
				filters={"status": "Active"},
				fields=["user_id"],
			)
            email_list = [emp["user_id"] for emp in all_employee_emails if emp.get("user_id")]

            # Get all managers recursively using reports_to hierarchy
            # managers_emails = get_all_managers_recursive(employee_doc.reports_to)
            # if not managers_emails:
            #     print(f"No valid managers found for {employee_doc.name}. Skipping.")
            #     continue

            print(f"Managers Emails for {employee_doc.name}: {email_list}")

            # Prepare the reminder text
            reminder_text = get_birthday_reminder_text_and_message([person])
            print(f"Reminder Text: {reminder_text}")

            # Send the email to managers
            send_birthday_reminder(email_list, reminder_text, [person], message, sender)
            print(f"Email sent to: {email_list}")




def get_birthday_reminder_text_and_message(birthday_persons):
	if len(birthday_persons) == 1:
		birthday_person_text = birthday_persons[0]["name"]
	else:
		# converts ["Jim", "Rim", "Dim"] to Jim, Rim & Dim
		person_names = [d["name"] for d in birthday_persons]
		birthday_person_text = comma_sep(person_names, frappe._("{0} & {1}"), False)

	reminder_text = _("Today is {0}'s birthday 🎉").format(birthday_person_text)
	message = _("A friendly reminder of an important date for our team.")
	message += "<br>"
	message += _("Everyone, let’s congratulate {0} on their birthday.").format(birthday_person_text)

	return reminder_text, message


def send_birthday_reminder(recipients, reminder_text, birthday_persons, message, sender=None):
	frappe.sendmail(
		sender=sender,
		recipients=recipients,
		subject=_("Birthday Reminder"),
		template="birthday_reminder",
		args=dict(
			reminder_text=reminder_text,
			birthday_persons=birthday_persons,
			message=message,
		),
		header=_("Birthday Reminder 🎂"),
	)


def get_employees_who_are_born_today():
	"""Get all employee born today & group them based on their company"""
	return get_employees_having_an_event_today("birthday")


def get_employees_having_an_event_today(event_type):
	"""Get all employee who have `event_type` today
	& group them based on their company. `event_type`
	can be `birthday` or `work_anniversary`"""

	from collections import defaultdict

	# Set column based on event type
	if event_type == "birthday":
		condition_column = "date_of_birth"
	elif event_type == "work_anniversary":
		condition_column = "date_of_joining"
	else:
		return

	employees_born_today = frappe.db.multisql(
		{
			"mariadb": f"""
			SELECT `personal_email`, `company`, `company_email`, `user_id`, `employee_name` AS 'name', `image`, `date_of_joining`
			FROM `tabEmployee`
			WHERE
				DAY({condition_column}) = DAY(%(today)s)
			AND
				MONTH({condition_column}) = MONTH(%(today)s)
			AND
				YEAR({condition_column}) < YEAR(%(today)s)
			AND
				`status` = 'Active'
		""",
			"postgres": f"""
			SELECT "personal_email", "company", "company_email", "user_id", "employee_name" AS 'name', "image"
			FROM "tabEmployee"
			WHERE
				DATE_PART('day', {condition_column}) = date_part('day', %(today)s)
			AND
				DATE_PART('month', {condition_column}) = date_part('month', %(today)s)
			AND
				DATE_PART('year', {condition_column}) < date_part('year', %(today)s)
			AND
				"status" = 'Active'
		""",
		},
		dict(today=today(), condition_column=condition_column),
		as_dict=1,
	)

	grouped_employees = defaultdict(lambda: [])

	for employee_doc in employees_born_today:
		grouped_employees[employee_doc.get("company")].append(employee_doc)

	return grouped_employees


# --------------------------
# WORK ANNIVERSARY REMINDERS
# --------------------------

@frappe.whitelist()
def send_work_anniversary_reminders():
    """Send Employee Work Anniversary Reminders to their manager and all higher-level managers recursively"""
    to_send = frappe.db.get_single_value("HR Settings", "send_work_anniversary_reminders")

    if not int(to_send):
        return

    sender = get_sender_email()
    # print(f"Sender Email: {sender}")

    employees_joined_today = get_employees_having_an_event_today("work_anniversary")

    message = "A friendly reminder of an important date for our team.<br>"
    message += "Please take a moment to congratulate them on their work anniversary!"

    for company, anniversary_persons in employees_joined_today.items():
        for person in anniversary_persons:

            employee_name = frappe.get_value("Employee", {"user_id": person["user_id"]}, "name")
            if not employee_name:
                continue

            employee_doc = frappe.get_doc("Employee", employee_name)

            # Get all managers recursively using a for loop
            managers_emails = get_all_managers_recursive(employee_doc.reports_to)
            if not managers_emails:
                continue

            # Prepare the reminder text
            reminder_text = get_work_anniversary_reminder_text([person])
            # Send the email to all managers in the hierarchy
            send_work_anniversary_reminder(managers_emails, reminder_text, [person], message, sender)

def get_all_managers_recursive(reports_to, managers=None):
    """Recursively fetch all managers up the hierarchy and collect their emails."""
    if managers is None:
        managers = set()

    if not reports_to:
        return list(managers)

    # Fetch the manager's email
    manager_email = frappe.get_value("Employee", reports_to, "user_id")
    
    if manager_email:
        if manager_email not in managers:  # Avoid duplicates
            managers.add(manager_email)
    # Fetch the next level reports_to
    next_manager = frappe.get_value("Employee", reports_to, "reports_to")

    if next_manager:
        get_all_managers_recursive(next_manager, managers)  # Recursively fetch higher-level managers

    return list(managers)

def get_work_anniversary_reminder_text(anniversary_persons: list) -> str:
	if len(anniversary_persons) == 1:
		anniversary_person = anniversary_persons[0]["name"]
		completed_years = getdate().year - anniversary_persons[0]["date_of_joining"].year
		return _("Today {0} completed {1} year(s) at our Company! 🎉").format(
			_(anniversary_person), completed_years
		)

	names_grouped_by_years = {}

	for person in anniversary_persons:
		completed_years = getdate().year - person["date_of_joining"].year
		names_grouped_by_years.setdefault(completed_years, []).append(person["name"])

	person_names_with_years = [
		_("{0} completed {1} year(s)").format(comma_sep(person_names, _("{0} & {1}"), False), years)
		for years, person_names in names_grouped_by_years.items()
	]

	# converts ["Jim", "Rim", "Dim"] to Jim, Rim & Dim
	anniversary_person = comma_sep(person_names_with_years, _("{0} & {1}"), False)
	return _("Today {0} at our Company! 🎉").format(_(anniversary_person))


def send_work_anniversary_reminder(
	recipients,
	reminder_text,
	anniversary_persons,
	message,
	sender=None,
):
	frappe.sendmail(
		sender=sender,
		recipients=recipients,
		subject=_("Work Anniversary Reminder"),
		template="anniversary_reminder",
		args=dict(
			reminder_text=reminder_text,
			anniversary_persons=anniversary_persons,
			message=message,
		),
		header=_("Work Anniversary Reminder"),
	)


def get_sender_email() -> str | None:
	return frappe.db.get_single_value("HR Settings", "sender_email")

