import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';

const root = document.getElementById('root');
if (!root) {
	throw new Error('Sim root element is missing.');
}

try {
	createRoot(root).render(
		<StrictMode>
			<App />
		</StrictMode>,
	);
} catch (error) {
	root.textContent = error instanceof Error ? error.message : 'Sim failed to start.';
}
