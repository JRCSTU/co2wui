/* File upload functions */

/* Non submitting file uploader */
$('#file_xhr').change(function(){
	$('#file_path_xhr').val($(this).val());
});

/* Generic file uploader */
$('#file_browser_xhr').click(function(e){
	e.preventDefault();
	$('#file_xhr').click();
});

$('#file_path_xhr').click(function(){
	$('#file_browser_xhr').click();
});

/* Generic file uploader */
$('#file_browser').click(function(e){		
	e.preventDefault();		
	$('#file').click();		
});		
$('#file').change(function(){		
	$('#file_path').val($(this).val());
	this.form.submit();
});		
$('#file_path').click(function(){		
	$('#file_browser').click();
});

/* Encryption keys */
$('#file_browser_enc_keys').click(function(e){		
	e.preventDefault();		
	$('#file_enc_keys').click();		
});		
$('#file_enc_keys').change(function(){		
	$('#file_path_enc_keys').val($(this).val());
	this.form.submit();
});		
$('#file_path_enc_keys').click(function(){		
	$('#file_browser_enc_keys').click();
});

/* Key passwords */
$('#file_browser_key_pass').click(function(e){		
	e.preventDefault();		
	$('#file_key_pass').click();		
});		
$('#file_key_pass').change(function(){		
	$('#file_path_key_pass').val($(this).val());
	this.form.submit();
});		
$('#file_path_key_pass').click(function(){		
	$('#file_browser_key_pass').click();
});

/* Signatures */
$('#file_browser_key_sign').click(function(e){		
	e.preventDefault();		
	$('#file_key_sign').click();		
});		
$('#file_key_sign').change(function(){		
	$('#file_path_key_sign').val($(this).val());
	this.form.submit();
});		
$('#file_path_key_sign').click(function(){		
	$('#file_browser_key_sign').click();
});

/* Change between type approval mode and engineering mode */
$(function() {
	$('#tamode').change(function() {
		if ($(this).prop('checked')) {
			$('#simulation-mode').text('Type approval mode');
			$('#ta-label').show();
		} else {
			$('#simulation-mode').text('Engineering mode');
			$('#ta-label').hide();
		}
	})
})

/* Advanced options */
function toggle_options() {
	$('#advanced_options').toggle();
}

/* Synchronisation form dynamic fields */
function toggle_wltp_class(el) {
	
	if (el.value == 'wltp') {
		$('#wltpclass-group').show();
		$('#gearbox-type-group').hide();
	} else {
		$('#wltpclass-group').hide();
		$('#gearbox-type-group').show();
	}
	
}

/* Simulation form advanced options */
$('#chk_only_summary').change(function () {					
	if ($('#chk_only_summary').is(':checked')) {
			$('#only_summary').val('true');
	}   
	else {
			$('#only_summary').val(null);
	}
});

$('#chk_declaration_mode').change(function () {					
	if ($('#chk_declaration_mode').is(':checked')) {

			$('#declaration_mode').val('true');

			$('#chk_hard_validation').prop("checked", true);
			$('#chk_hard_validation').prop("disabled", false);
			$('#hard_validation').val('true');

			if ($('#chk_enable_selector').is(':checked')) {
				alert('"Enable selector" cannot be used when "Declaration mode" is enabled');
				$('#chk_enable_selector').prop("checked", false);
				$('#enable_selector').val(null);
			}
			$('#chk_enable_selector').prop("disabled", true);
	}   
	else {
			$('#declaration_mode').val(null);
			$('#chk_enable_selector').prop("disabled", false);
			$('#chk_hard_validation').prop("disabled", false);
	}
});	

$('#chk_hard_validation').change(function () {					
	if ($('#chk_hard_validation').is(':checked')) {
			$('#hard_validation').val('true');
	}   
	else {
			$('#hard_validation').val(null);
	}
});

$('#chk_enable_selector').change(function () {					
	if ($('#chk_enable_selector').is(':checked')) {
			$('#enable_selector').val('true');
	}   
	else {
			$('#enable_selector').val(null);
	}
});

$('#chk_custom_conf').change(function () {

	if ($('#chk_custom_conf').is(':checked')) {
			$('#custom_conf').val('true');
	}
	else {
			$('#custom_conf').val(null);
	}
});

/* Synchronisation form advanced options */
$('#option_reference_name').change(function () {
	$('#reference_name').val($('#option_reference_name').val());
})

$('#option_x_label').change(function () {					
	$('#x_label').val($('#option_x_label').val());
})

$('#option_y_label').change(function () {					
	$('#y_label').val($('#option_y_label').val());
})

$('#option_interpolation_method').change(function () {					
	$('#interpolation_method').val($('#option_interpolation_method').val());
})

$('#option_header_row_number').change(function () {					
	$('#header_row_number').val($('#option_header_row_number').val());
})


/* Run synchronisation */
function run_synchronisation() {
	$('#synchronise-button').html("<i class=\"fa fa-spin fa-refresh\"></i> Synchronisation in progress...");
	$.ajax({
		url: "/sync/run-synchronisation",
		method: "post",
		data: $('#synchronise-form').serialize(),
		context: document.body
	}).done(function(msg) {
		if (msg == 'OK') {
			$('#logarea').load('/sync/load-log');
			if ($('#logarea').val() == '') {
				$('#log-section').hide();
			}
			$('#synchronise-button').html("<i class=\"fa fa-refresh\"></i> Synchronise data...");
			$('#synchronise-button').hide();
			$('#file-list').hide();
			$('#file-chooser').hide();
			$('#advanced_options').hide();
			$('#form-container').hide();
			$('#options-link').hide();
			$('#result-toolbar').show();
			$('#sync-result').show();
		} else {
			$('#result-toolbar').show();
			$('#logarea').load('/sync/load-log', function() {
				if ($('#logarea').val() == '') {
					$('#log-section').hide();
				} else {
					$('#logarea').prepend("There was an error during the synchronisation\n")
				}
			})
			$('#synchronise-button').hide();
		}
	});
}

function load_summary(result_name) {
	$('.modal-dialog').css("width", "85%");
	$('#modal-content').load('/run/view-summary/' + result_name);
	$('#modal-default').modal('show');
}

function check_ta_mode() {
	if ($('#tamode').prop('checked')) {
		$('#advanced_options').hide();
		$('#advanced_link').hide();
	} else {
		$('#advanced_link').show();
	}
}

function check_boxes() {
	if ($('#select-all').prop("checked")) {
		$(".run-delete").prop( "checked", true);
	} else {
		$(".run-delete").prop( "checked", false);
	}
}

$('.sidebar-menu').tree({accordion: false});

function exclude_files(num, checked) {

	files = [];
	excluded = $('#exclude_list').val();
	if (excluded != '') {
		files = excluded.split("|");
	}

	var index = files.indexOf(num.toString());
	if (index > -1) {
		files.splice(index, 1);
	}

	if (checked) {
		if (num) {
			files.push(num);
		}
	}
	$('#exclude_list').val(files.join("|"))

}