# Copyright (c) 2025
# Attendance Summary Report

import frappe
from frappe.utils import getdate
from calendar import monthrange

def execute(filters=None):
    filters = filters or {}

    if not filters.get("month") or not filters.get("year"):
        frappe.throw("Please select Month and Year")

    month = int(filters.get("month"))
    year = int(filters.get("year"))
    total_days = monthrange(year, month)[1]

    # --------------------------
    # COLUMNS
    # --------------------------
    columns = [
        {"label": "Employee", "fieldname": "employee", "fieldtype": "Link",
         "options": "Employee", "width": 140},
        {"label": "Employee Name", "fieldname": "employee_name", "fieldtype": "Data", "width": 150},
    ]

    # Day-wise columns
    for d in range(1, total_days + 1):
        columns.append({
            "label": f"{d}",
            "fieldname": f"d{d}",
            "fieldtype": "Data",
            "width": 45
        })

    # Summary columns (in requested order)
    columns.extend([
        {"label": "Number of Days", "fieldname": "number_of_days", "fieldtype": "Int", "width": 120},
        {"label": "Total Present", "fieldname": "total_present", "fieldtype": "Float", "width": 120},
        {"label": "Total Half Day", "fieldname": "total_half_day", "fieldtype": "Float", "width": 130},
        {"label": "Total Work From Home", "fieldname": "total_wfh", "fieldtype": "Float", "width": 150},
        {"label": "Total Leave", "fieldname": "total_leave", "fieldtype": "Float", "width": 130},
        {"label": "Total Absent", "fieldname": "total_absent", "fieldtype": "Float", "width": 120},
        {"label": "Payment Days", "fieldname": "payment_days", "fieldtype": "Float", "width": 140},
    ])

    # --------------------------
    # LEGEND + FORMULA MESSAGE
    # --------------------------
    message = """
    <div style="margin:10px 0; padding:12px; font-size:14px; line-height:1.6;">

        <b style="font-size:15px;">Attendance Legend</b><br>

        <span style="color:green; font-weight:600;">P – Present</span>&nbsp;&nbsp;
        <span style="color:red; font-weight:600;">A – Absent</span>&nbsp;&nbsp;
        <span style="color:orange; font-weight:600;">HD – Half Day</span>&nbsp;&nbsp;
        <span style="color:#007bff; font-weight:600;">L – Leave</span>&nbsp;&nbsp;
        <span style="color:brown; font-weight:600;">WFH – Work From Home</span>&nbsp;&nbsp;
        <span style="color:gray; font-weight:600;">WO – Weekly Off</span>&nbsp;&nbsp;
        <span style="color:purple; font-weight:600;">H – Holiday</span>

        <br><br>

        <b style="font-size:15px;">Payment Days Formula:</b><br>
        <span style="color:#444; font-weight:500;">
            Payment Days = (Total Present + Total Work From Home + Total Leave + ((Total Half Day ÷ 2) + 1.5))
        </span>

    </div>
    """

    # --------------------------
    # EMPLOYEE LIST
    # --------------------------
    emp_filters = {"status": "Active"}
    if filters.get("company"): emp_filters["company"] = filters.get("company")
    if filters.get("employee"): emp_filters["name"] = filters.get("employee")

    employees = frappe.get_all(
        "Employee",
        filters=emp_filters,
        fields=["name", "employee_name", "holiday_list"]
    )

    if not employees:
        return columns, [], message

    # --------------------------
    # HOLIDAY MAP
    # --------------------------
    holiday_map = {}

    for emp in employees:
        holiday_map[emp.name] = {}
        if emp.holiday_list:
            holidays = frappe.get_all(
                "Holiday",
                filters={
                    "parent": emp.holiday_list,
                    "holiday_date": ("between", [
                        f"{year}-{month:02d}-01",
                        f"{year}-{month:02d}-{total_days}"
                    ])
                },
                fields=["holiday_date", "weekly_off"]
            )
            for h in holidays:
                day = getdate(h.holiday_date).day
                holiday_map[emp.name][day] = "Weekly Off" if h.weekly_off else "Holiday"

    # --------------------------
    # ATTENDANCE MAP
    # --------------------------
    attendance_raw = frappe.get_all(
        "Attendance",
        filters={
            "docstatus": 1,
            "attendance_date": ("between", [
                f"{year}-{month:02d}-01",
                f"{year}-{month:02d}-{total_days}"
            ])
        },
        fields=["employee", "status", "attendance_date"]
    )

    att_map = {}
    for a in attendance_raw:
        day = getdate(a.attendance_date).day
        att_map.setdefault(a.employee, {})[day] = a.status

    # --------------------------
    # BUILD DATA
    # --------------------------
    data = []

    for emp in employees:

        row = {
            "employee": emp.name,
            "employee_name": emp.employee_name,
            "number_of_days": total_days,
            "total_present": 0,
            "total_absent": 0,
            "total_half_day": 0,
            "total_leave": 0,
            "total_wfh": 0,
            "payment_days": 0,
        }

        for d in range(1, total_days + 1):

            status = att_map.get(emp.name, {}).get(d)
            holiday_status = holiday_map.get(emp.name, {}).get(d)
            icon = ""

            # ---- Attendance Priority ----
            if status == "Present":
                icon = "<span style='color:green;font-weight:bold'>P</span>"
                row["total_present"] += 1

            elif status == "Absent":
                icon = "<span style='color:red;font-weight:bold'>A</span>"
                row["total_absent"] += 1

            elif status == "Half Day":
                icon = "<span style='color:orange;font-weight:bold'>HD</span>"
                row["total_half_day"] += 1

            elif status == "On Leave":
                icon = "<span style='color:#007bff;font-weight:bold'>L</span>"
                row["total_leave"] += 1

            elif status == "Work From Home":
                icon = "<span style='color:brown;font-weight:bold'>WFH</span>"
                row["total_wfh"] += 1

            # ---- Weekly Off / Holiday ----
            elif not status and holiday_status:
                if holiday_status == "Weekly Off":
                    icon = "<span style='color:gray;font-weight:bold'>WO</span>"
                else:
                    icon = "<span style='color:purple;font-weight:bold'>H</span>"
                row["total_present"] += 1  # counted as present

            row[f"d{d}"] = icon

        # ------------------------------
        # PAYMENT DAYS FORMULA
        # ------------------------------
        if row["total_half_day"] > 3:
            row["payment_days"] = (
                row["total_present"]
                + row["total_wfh"]
                + row["total_leave"]
                +((row["total_half_day"] / 2) + 1.5)
            )
        else:
            row["payment_days"] = (
                row["total_present"]
                + row["total_wfh"]
                + row["total_leave"]
                + row["total_half_day"]
            )            

        data.append(row)

    return columns, data, message
