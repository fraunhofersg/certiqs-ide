import { Architect } from './Architect';
import { Brainstorming } from './Brainstorming';
import { ChatSession } from './ChatSession';
import { ContextLens } from './ContextLens';
import { HqHome } from './HqHome';
import { Settings } from './Settings';

export function App(): JSX.Element {
	switch (document.body.dataset.surface) {
		case 'settings':
			return <Settings />;
		case 'lens':
			return <ContextLens />;
		case 'chat':
			return <ChatSession />;
		case 'brainstorm':
			return <Brainstorming />;
		case 'architect':
			return <Architect />;
		default:
			return <HqHome />;
	}
}
