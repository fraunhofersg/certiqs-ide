import { Dashboard } from './Dashboard';
import { Overview } from './Overview';
import { RunControl } from './RunControl';
import { System } from './System';

export function App(): JSX.Element {
	const surface = document.body.dataset.surface;
	if (surface === 'dashboard') {
		return <Dashboard />;
	}
	if (surface === 'system') {
		return <System />;
	}
	if (surface === 'overview' || surface === 'welcome') {
		return <Overview />;
	}
	return <RunControl />;
}
