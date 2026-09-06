import { Button, Card, Input, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import type { ArchitectStep, SessionFile } from '../../src/knowledgeTypes';
import { rpc } from './hostRpc';
import { onHostMessage, post } from './vscodeApi';

export function Architect(): JSX.Element {
	const sessionId = document.body.dataset.sessionId ?? '';
	const [session, setSession] = useState<SessionFile | undefined>();
	const [intent, setIntent] = useState('');
	const [stepTitle, setStepTitle] = useState('');

	useEffect(() => {
		const dispose = onHostMessage(message => {
			const next = message.type === 'knowledge' ? message.payload.activeSession
				: message.type === 'state' ? message.payload.knowledge?.activeSession : undefined;
			if (next?.id === sessionId) {
				apply(next);
			}
		});
		post({ type: 'ready' });
		void rpc<SessionFile | undefined>('getSession', { id: sessionId }).then(next => {
			if (next) {
				apply(next);
			}
		});
		return dispose;
	}, [sessionId]);

	const apply = (next: SessionFile) => {
		setSession(next);
		setIntent(next.intent ?? '');
	};

	const persist = (patch: Partial<SessionFile>) => rpc<SessionFile>('updateSession', { id: sessionId, patch });

	const addStep = async () => {
		if (!stepTitle.trim()) {
			return;
		}
		const step: ArchitectStep = { id: `step-${Date.now().toString(36)}`, title: stepTitle.trim(), body: '', done: false };
		await persist({ intent, steps: [...(session?.steps ?? []), step] });
		setStepTitle('');
	};

	const toggle = async (id: string) => {
		const steps = (session?.steps ?? []).map(step => step.id === id ? { ...step, done: !step.done } : step);
		await persist({ intent, steps });
	};

	return (
		<div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-5">
			<header>
				<p className="text-xs font-semibold tracking-wide text-accent">Architect</p>
				<h1 className="text-xl font-semibold">{session?.title ?? 'Architect'}</h1>
				<p className="text-xs text-muted">Plan steps only. This surface does not edit the repository.</p>
			</header>

			<Card className="p-4">
				<p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Intent / spec</p>
				<textarea className="min-h-24 w-full rounded-md border border-separator bg-surface px-3 py-2 text-sm" value={intent} onChange={event => setIntent(event.target.value)} placeholder="What should be planned for the QKD system or its security review?" />
				<div className="mt-2">
					<Button size="sm" variant="outline" onPress={() => void persist({ intent, steps: session?.steps })}>Save</Button>
				</div>
				{session?.spec ? <p className="mt-3 whitespace-pre-wrap text-xs text-muted">{session.spec}</p> : null}
			</Card>

			<Card className="p-4">
				<p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Steps</p>
				<div className="mb-3 flex gap-2">
					<TextField name="step-title" className="flex-1" value={stepTitle} onChange={setStepTitle}><Input placeholder="Add a plan step" /></TextField>
					<Button size="sm" onPress={() => void addStep()}>Add</Button>
				</div>
				<ul className="space-y-2">
					{(session?.steps ?? []).map(step => (
						<li key={step.id}>
							<label className="flex items-start gap-2 rounded-md border border-separator p-3">
								<input type="checkbox" checked={Boolean(step.done)} onChange={() => void toggle(step.id)} />
								<div>
									<p className={`text-sm font-semibold ${step.done ? 'text-muted line-through' : ''}`}>{step.title}</p>
									{step.body ? <p className="text-xs text-muted">{step.body}</p> : null}
								</div>
							</label>
						</li>
					))}
				</ul>
			</Card>
		</div>
	);
}
