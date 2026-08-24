// Copyright (c) 2025, Bharathi and contributors
// For license information, please see license.txt

frappe.query_reports["Attendance Summary"] = {
	"filters": [
        {
            fieldname: "month",
            label: __("Month"),
            fieldtype: "Select",
            reqd: 1,
            options: [
                { "value": "1", "label": "January" },
                { "value": "2", "label": "February" },
                { "value": "3", "label": "March" },
                { "value": "4", "label": "April" },
                { "value": "5", "label": "May" },
                { "value": "6", "label": "June" },
                { "value": "7", "label": "July" },
                { "value": "8", "label": "August" },
                { "value": "9", "label": "September" },
                { "value": "10", "label": "October" },
                { "value": "11", "label": "November" },
                { "value": "12", "label": "December" }
            ],
            default: (new Date().getMonth() + 1).toString()
        },
        {
            fieldname: "year",
            label: __("Year"),
            fieldtype: "Select",
            reqd: 1,
            options: [
                new Date().getFullYear() - 1,
                new Date().getFullYear()
            ].join("\n"),
            default: new Date().getFullYear().toString()
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            reqd: 0
        },
        {
            fieldname: "employee",
            label: __("Employee"),
            fieldtype: "Link",
            options: "Employee",
            reqd: 0
        }
    ]
};
