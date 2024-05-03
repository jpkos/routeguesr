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
