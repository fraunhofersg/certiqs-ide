import { Applicability } from './surfaces/Applicability';
import { Countermeasures } from './surfaces/Countermeasures';
import { Documents } from './surfaces/Documents';
import { EvaluationActivities } from './surfaces/EvaluationActivities';
import { Hub } from './surfaces/Hub';
import { Inspector } from './surfaces/Inspector';
import { Search } from './surfaces/Search';
import { Sidebar } from './surfaces/Sidebar';
import { SystemDetail } from './surfaces/SystemDetail';
import { Systems } from './surfaces/Systems';
import { Vulnerabilities } from './surfaces/Vulnerabilities';
import { Wizard } from './surfaces/Wizard';

export function App(): JSX.Element {
	const surface = document.body.dataset.surface;
	switch (surface) {
		case 'inspector':
			return <Inspector />;
		case 'hub':
			return <Hub />;
		case 'systems':
			return <Systems />;
		case 'wizard':
			return <Wizard />;
		case 'system':
			return <SystemDetail />;
		case 'applicability':
			return <Applicability />;
		case 'search':
			return <Search />;
		case 'vulnerabilities':
			return <Vulnerabilities />;
		case 'eas':
			return <EvaluationActivities />;
		case 'countermeasures':
			return <Countermeasures />;
		case 'documents':
			return <Documents />;
		default:
			return <Sidebar />;
	}
}
