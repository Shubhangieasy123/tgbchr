frappe.ui.form.on("Employee Permission Request", {
	setup(frm) {
		// Only the selected employee's leave approver is selectable
		frm.set_query("hod_approver", () => {
			return {
				filters: {
					name: ["in", frm._leave_approver ? [frm._leave_approver] : [""]],
				},
			};
		});
	},

	refresh(frm) {
		// Restore the filter when an existing record is opened
		if (frm.doc.employee) {
			set_leave_approver(frm, false);
		}

		

		const is_approver = frappe.session.user === frm.doc.hod_approver;

		// Status cannot be changed by the HOD approver on a saved draft
		const can_edit_status = !frm.is_new() && frm.doc.docstatus === 0 && is_approver;
		frm.set_df_property("status", "read_only", 1);

		if (!frm.is_new() && frm.doc.docstatus < 2 && !is_approver) {
			// disable_form() clears the primary button, so do it first
			frm.disable_form();
		}
	},

	employee(frm) {
		frm.set_value("hod_approver", "");
		frm._leave_approver = null;
		if (frm.doc.employee) {
			set_leave_approver(frm, true);
		}
	},

	from_time(frm) {
		frm.trigger("calc_hours");
	},
	to_time(frm) {
		frm.trigger("calc_hours");
	},
	calc_hours(frm) {
		if (!frm.doc.from_time || !frm.doc.to_time) return;
		const start = moment(frm.doc.from_time, "HH:mm:ss");
		const end = moment(frm.doc.to_time, "HH:mm:ss");
		const hours = moment.duration(end.diff(start)).asHours();
		if (hours > 0) {
			frm.set_value("hours", hours.toFixed(2));
		}
	},
});


function set_leave_approver(frm, autofill) {
	frappe.db.get_value("Employee", frm.doc.employee, "leave_approver").then((r) => {
		const approver = r.message && r.message.leave_approver;
		frm._leave_approver = approver || null;

		if (autofill) {
			if (approver) {
				frm.set_value("hod_approver", approver);
			} else {
				frappe.show_alert({
					message: __("No Leave Approver is set for this employee"),
					indicator: "orange",
				});
			}
		}
	});
}