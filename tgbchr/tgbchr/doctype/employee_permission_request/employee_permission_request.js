frappe.ui.form.on("Employee Permission Request", {
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
