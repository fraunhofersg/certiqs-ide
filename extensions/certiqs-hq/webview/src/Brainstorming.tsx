import { Button, Card, Chip, Input, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import type { BrainstormBranch, SessionFile } from '../../src/knowledgeTypes';
import { rpc } from './hostRpc';
import { onHostMessage, post } from './vscodeApi';

export function Brainstorming(): JSX.Element {
	const sessionId = document.body.dataset.sessionId ?? '';
	const [session, setSession] = useState<SessionFile | undefined>();
	const [intent, setIntent] = useState('');
	const [branchTitle, setBranchTitle] = useState('');
	const [branchBody, setBranchBody] = useState('');
	const [spec, setSpec] = useState('');

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
		setSpec(next.spec ?? '');
	};

	const persist = (patch: Partial<SessionFile>) => rpc<SessionFile>('updateSession', { id: sessionId, patch });

	const addBranch = async () => {
		if (!branchTitle.trim()) {
			return;
		}
		const branch: BrainstormBranch = {
			id: `branch-${Date.now().toString(36)}`,
			title: branchTitle.trim(),
			body: branchBody.trim(),
		};
		await persist({ intent, spec, branches: [...(session?.branches ?? []), branch] });
		setBranchTitle('');
		setBranchBody('');
	};

	const toggle = async (id: string) => {
		const branches = (session?.branches ?? []).map(branch => branch.id === id ? { ...branch, selected: !branch.selected } : branch);
		await persist({ intent, spec, branches });
	};

	return (
		<div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-5">
			<header>
				<p className="text-xs font-semibold tracking-wide text-accent">Brainstorming</p>
				<h1 className="text-xl font-semibold">{session?.title ?? 'Brainstorming'}</h1>
				<p className="text-xs text-muted">Intent → divergence → convergence → spec. Local only; not a security conclusion.</p>
			</header>

			<Card className="p-4">
				<p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Intent</p>
				<textarea className="min-h-24 w-full rounded-md border border-separator bg-surface px-3 py-2 text-sm" value={intent} onChange={event => setIntent(event.target.value)} placeholder="The decision you need to make about the QKD implementation or its security…" />
				<div className="mt-2">
					<Button size="sm" variant="outline" onPress={() => void persist({ intent, spec, branches: session?.branches })}>Save intent</Button>
				</div>
			</Card>

			<Card className="p-4">
				<p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Divergence</p>
				<div className="mb-3 grid gap-2 md:grid-cols-[1fr_2fr_auto]">
					<TextField name="branch-title" value={branchTitle} onChange={setBranchTitle}><Input placeholder="Branch title" /></TextField>
					<TextField name="branch-body" value={branchBody} onChange={setBranchBody}><Input placeholder="Tradeoff or direction" /></TextField>
					<Button size="sm" onPress={() => void addBranch()}>Add branch</Button>
				</div>
				<div className="grid gap-2 md:grid-cols-2">
					{(session?.branches ?? []).map(branch => (
						<button
							key={branch.id}
							type="button"
							onClick={() => void toggle(branch.id)}
							className={`rounded-md border p-3 text-left ${branch.selected ? 'border-accent bg-accent/10' : 'border-separator'}`}
						>
							<div className="mb-1 flex items-center justify-between gap-2">
								<p className="text-sm font-semibold">{branch.title}</p>
								{branch.selected ? <Chip size="sm" variant="soft">selected</Chip> : null}
							</div>
							<p className="text-xs text-muted">{branch.body}</p>
						</button>
					))}
				</div>
			</Card>

			<Card className="p-4">
				<p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Spec</p>
				<textarea className="min-h-32 w-full rounded-md border border-separator bg-surface px-3 py-2 text-sm" value={spec} onChange={event => setSpec(event.target.value)} placeholder="Write or refine the spec from selected branches…" />
				<div className="mt-3 flex flex-wrap gap-2">
					<Button size="sm" onPress={() => void persist({ intent, spec, branches: session?.branches })}>Save spec</Button>
					<Button size="sm" variant="outline" onPress={() => void rpc('approveSpec', { id: sessionId })}>Approve spec</Button>
					<Button size="sm" variant="outline" onPress={() => void rpc('sendToArchitect', { id: sessionId })}>Send to Architect</Button>
				</div>
				{session?.specPath ? <p className="mt-2 font-mono text-[11px] text-muted">{session.specPath}</p> : null}
			</Card>
		</div>
	);
}
