import { Game } from './runtime.js';
const status = document.querySelector('#status');
try {
  const response = await fetch(new URL('./game.json', import.meta.url));
  if (!response.ok) throw new Error(`Scene request failed: HTTP ${response.status}`);
  const game = new Game(document.querySelector('#game'), await response.json(), new URL('./', import.meta.url), status);
  await game.load();
  // Read-only reference for diagnostics and developer tools; no external loop needed.
  window.viperGame = game;
  game.start();
} catch (error) {
  status.dataset.error = 'true';
  status.textContent = `Could not start Viper game: ${error.message}\nServe this folder over HTTP(S).`;
  console.error(error);
}
