// socket-client.js
// var socket = io();

// socket.on('connect', function() {
//     console.log('Connected to the server via Socket.IO!');
//     // Ensure you join the room using the correct session_id
//     var sessionId = 'YOUR_session_id'; // This should be dynamically assigned based on the game
//     socket.emit('join_room', {session_id: sessionId});
// });

// socket.on('start_game', function(data) {
//     if (data.session_id === sessionId) {
//         startGame();
//     }
// });

// function startGame() {
//     console.log("Game is starting!");
//     // Additional logic to transition to the game
//     window.location.href = '/index.html'; // Assuming you have a game start page
// }