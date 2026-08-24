console.log("TGBCHR Employee JS Loaded");
frappe.ui.form.on('Employee', {

    validate: function(frm) {

        // Aadhaar validation
        if (frm.doc.custom_aadhaar_number) {

            let aadhaar = String(frm.doc.custom_aadhaar_number).trim();

            if (!/^\d{12}$/.test(aadhaar)) {
                frappe.throw(
                    __('Aadhaar Number must contain exactly 12 digits.')
                );
            }
        }

        // Date of Birth validation
        if (frm.doc.date_of_birth) {

            let dob = frappe.datetime.str_to_obj(frm.doc.date_of_birth);
            let today = new Date();

            if (dob > today) {
                frappe.throw(
                    __('Date of Birth cannot be a future date.')
                );
            }
        }

        // Age is calculated only on save
        calculate_age(frm);

        // Tenure with TGB is calculated only on save
        calculate_tenure(frm);
    }
});


function calculate_age(frm) {

    if (!frm.doc.date_of_birth) {
        frm.set_value('custom_age', '');
        return;
    }

    let dob = frappe.datetime.str_to_obj(frm.doc.date_of_birth);
    let today = new Date();

    let age = today.getFullYear() - dob.getFullYear();

    let month_difference =
        today.getMonth() - dob.getMonth();

    if (
        month_difference < 0 ||
        (
            month_difference === 0 &&
            today.getDate() < dob.getDate()
        )
    ) {
        age--;
    }

    frm.set_value('custom_age', age);
}


function calculate_tenure(frm) {

    if (!frm.doc.date_of_joining) {
        frm.set_value('custom_tenure_with_tgb', '');
        return;
    }

    let doj = frappe.datetime.str_to_obj(frm.doc.date_of_joining);
    let today = new Date();

    let years = today.getFullYear() - doj.getFullYear();
    let months = today.getMonth() - doj.getMonth();
    let days = today.getDate() - doj.getDate();

    if (days < 0) {
        months--;
        // borrow days from the previous month
        let prev_month_last_date = new Date(
            today.getFullYear(),
            today.getMonth(),
            0
        ).getDate();
        days += prev_month_last_date;
    }

    if (months < 0) {
        years--;
        months += 12;
    }

    // Format as "X Years Y Months Z Days"
    let tenure_string = `${years} Year(s) ${months} Month(s) ${days} Day(s)`;

    frm.set_value('custom_tenure_with_tgb', tenure_string);
}