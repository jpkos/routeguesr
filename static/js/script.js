function checkGuess() {
    const guess = document.getElementById('place-dropdown').value;
    fetch('/check_guess', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `guess=${encodeURIComponent(guess)}`
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('result').textContent = data.result;
        document.getElementById('total-guesses').textContent = data.total_guesses;
        document.getElementById('correct-guesses').textContent = data.correct_guesses;
        document.getElementById('correct-pct').textContent = data.correct_pct;
        // Disable the guess button to prevent further guesses
        document.getElementById('guess-btn').disabled = true;
    })
    .catch(error => console.error('Error:', error));
}

function newLine() {
    fetch('/new_line')
    .then(response => response.text())
    .then(html => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        document.getElementById('map').innerHTML = doc.getElementById('map').innerHTML;
        document.getElementById('place-dropdown').innerHTML = doc.getElementById('place-dropdown').innerHTML;
        document.getElementById('result').textContent = '';
        // Re-enable the guess button for the new line
        document.getElementById('guess-btn').disabled = false;
    })
    .catch(error => console.error('Error:', error));
}

document.getElementById('multiplayer-settings-btn').addEventListener('click', function() {
    $('#multiSettingsModal').modal('show');
  });

document.getElementById('singleplayer-settings-btn').addEventListener('click', function() {
$('#singleSettingsModal').modal('show');
});
  
// function generateLink() {
//     console.log("Button clicked");  // Check if this gets logged
//     var formData = $('#multi-settings-form').serialize();
//     $.ajax({
//         type: "POST",
//         url: "/new_multiplayer_game",
//         data: formData,
//         success: function(response) {
//             console.log("Received response:", response);  // Log the response
//             var linkInput = document.getElementById('generated-link');
//             linkInput.value = response.url;
//             linkInput.style.display = '';
//             linkInput.select();
//         },
//         error: function(xhr, status, error) {
//             console.error("AJAX error:", status, error);
//         }
//     });
// }

function submitSinglePlayerSettings() {
    // Create an object to store the checkbox values
    const formData = {
        transportTypes: {
            bus: document.getElementById('categoryA1').checked,
            train: document.getElementById('categoryA2').checked,
            tram: document.getElementById('categoryA3').checked,
            metro: document.getElementById('categoryA4').checked
        },
        operatingTypes: {
            normal: document.getElementById('categoryB1').checked,
            night: document.getElementById('categoryB2').checked,
            service: document.getElementById('categoryB3').checked
        }
    };

    console.log("Submitting the following settings:", formData);

    // Send the form data to the Flask server using AJAX
    fetch('/update_single_settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
    })
    .then(response => response.json())
    .then(data => {
        console.log('Success:', data);
        alert('Muutokset tallennettiin onnistuneesti!');
        $('#singleSettingsModal').modal('hide');
    })
    .catch((error) => {
        console.error('Error:', error);
        alert('Virhe! Muutoksia ei tallennettu!');
    });
}

function toggleSubOptions(checkbox, subOptionsId) {
    const subOptions = document.getElementById(subOptionsId);
    if (checkbox.checked) {
        subOptions.style.display = 'block';
        // Check all sub-options when the main option is checked
        subOptions.querySelectorAll('input[type="checkbox"]').forEach(subOption => {
            subOption.checked = true;
        });
    } else {
        subOptions.style.display = 'none';
        // Uncheck all sub-options when the main option is unchecked
        subOptions.querySelectorAll('input[type="checkbox"]').forEach(subOption => {
            subOption.checked = false;
        });
    }
}  