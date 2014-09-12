
function login() {

	var email = $("#email").val();
	var password = $("#password").val();
	
	var content = JSON.stringify({ "email" : email, "password" : password });

	$.post("/login", content,
	 function( data, txtStatus, xhr ) {
		// Sucessful!
		window.location = JSON.parse(data).url;
	})
	.fail(function(data, txtStatus, xhr) {
		$('.alert').show();
		console.log("fail: " + data.responseText);
		json_body = JSON.parse(data.responseText);
		if (json_body.error == "invalid login.") {
			$("#msg").text("Login/Senha inválido(s)- clkasjdalskdj");	
		} else {
			$("#msg").text(json_body.error);	
		}
		
	});
	
	/*

	var email = $("#email").val();
	var password = $("#password").val();

    console.log("Entrou aki no login");
	//Send the AJAX call to the server
  	$.ajax({
    url: 'http://www.google.com' + "/" + email + "/" + password,
    dataType: 'xml',
    complete : function(){
        alert(this.url)
    },
    success: function(xml){

    }
	});
	*/

}