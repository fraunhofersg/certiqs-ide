import { Button, Card } from '@heroui/react';
import { openPage } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { Page } from './Page';

const CARDS = [
	{ surface: 'systems' as const, title: 'My systems', body: 'Own and public systems. Create with the wizard.' },
	{ surface: 'applicability' as const, title: 'Applicability check', body: 'Bucket catalogue attacks and derived EAs for a visible system.' },
	{ surface: 'search' as const, title: 'Search', body: 'Quick ILIKE or advanced nested AND/OR trees.' },
	{ surface: 'vulnerabilities' as const, title: 'Attacks', body: 'Vulnerability directory with module/component chips.' },
	{ surface: 'eas' as const, title: 'Evaluation activities', body: 'EA catalogue. Admin can create.' },
	{ surface: 'countermeasures' as const, title: 'Countermeasures', body: 'Grouped by hardware / software / both.' },
];

export function Hub(): JSX.Element {
	const state = useQdbState();
	return (
		<Page
			title="QKD compliance workbench"
			subtitle={state.notice}
			actions={
				<>
					<Button size="sm" variant="primary" onPress={() => openPage('wizard')}>New system</Button>
					<Button size="sm" variant="outline" onPress={() => openPage('search')}>Search</Button>
				</>
			}
		>
			<div className="qdb-grid">
				{CARDS.map(card => (
					<Card key={card.surface} className="p-4">
						<Card.Header>
							<Card.Title>{card.title}</Card.Title>
							<Card.Description>{card.body}</Card.Description>
						</Card.Header>
						<Card.Content>
							<Button size="sm" variant="outline" onPress={() => openPage(card.surface, state.selectedSystemId)}>Open</Button>
						</Card.Content>
					</Card>
				))}
				{state.isAdmin ? (
					<Card className="p-4">
						<Card.Header>
							<Card.Title>Document sources</Card.Title>
							<Card.Description>Admin registry of source PDFs. Upload is stored in extension global storage.</Card.Description>
						</Card.Header>
						<Card.Content>
							<Button size="sm" variant="outline" onPress={() => openPage('documents')}>Open</Button>
						</Card.Content>
					</Card>
				) : null}
			</div>
		</Page>
	);
}
