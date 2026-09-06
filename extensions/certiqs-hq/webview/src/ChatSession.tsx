import { Button, Card, Input, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import type { HqSkill } from '../../src/protocol';
import type { SessionFile } from '../../src/knowledgeTypes';
import { rpc } from './hostRpc';
import { onHostMessage, post } from './vscodeApi';

export function ChatSession(): JSX.Element {
	const sessionId = document.body.dataset.sessionId ?? '';
	const [session, setSession] = useState<SessionFile | undefined>();
	const [skills, setSkills] = useState<HqSkill[]>([]);
	const [text, setText] = useState('');
	const [hint, setHint] = useState('');

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setSkills(message.payload.skills);
				if (message.payload.knowledge?.activeSession?.id === sessionId) {
					setSession(message.payload.knowledge.activeSession);
				}
			}
			if (message.type === 'knowledge' && message.payload.activeSession?.id === sessionId) {
				setSession(message.payload.activeSession);
			}
		});
		post({ type: 'ready' });
		void rpc<SessionFile | undefined>('getSession', { id: sessionId }).then(setSession);
		return dispose;
	}, [sessionId]);

	const send = async () => {
		const value = text.trim();
		if (!value || !sessionId) {
			return;
		}
		setText('');
		await rpc<SessionFile>('appendMessage', { id: sessionId, text: value, role: 'user' });
		const next = await rpc<SessionFile>('appendMessage', {
			id: sessionId,
			role: 'note',
			text: 'Recorded locally. No model was called. Use Context Lens to inspect loom/wiki/knot before a later provider hook.',
		});
		if (next) {
			setSession(next);
		}
	};

	const insertSkill = (slug: string) => {
		setText(current => current ? `${current} /${slug}` : `/${slug} `);
		setHint('');
	};

	const slash = text.startsWith('/') ? text.slice(1).toLowerCase() : '';
	const matches = slash ? skills.filter(skill => skill.slug.includes(slash)) : [];

	return (
		<div className="flex h-full min-h-0 flex-col p-5">
			<header className="mb-4">
				<p className="text-xs font-semibold tracking-wide text-accent">Chat Session</p>
				<h1 className="text-xl font-semibold">{session?.title ?? 'Session'}</h1>
				<p className="text-xs text-muted">Local notes only. Slash-insert a workspace skill; it is not executed.</p>
			</header>
			<div className="min-h-0 flex-1 space-y-2 overflow-auto">
				{(session?.messages ?? []).map(message => (
					<Card key={message.id} className="p-3">
						<p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{message.role}</p>
						<p className="whitespace-pre-wrap text-sm">{message.text}</p>
					</Card>
				))}
				{(session?.messages.length ?? 0) === 0 ? (
					<Card className="p-6 text-sm text-muted">Ask about the QKD implementation or its security assumptions. Messages stay in .certiqs/sessions.</Card>
				) : null}
			</div>
			<div className="mt-3">
				{matches.length > 0 ? (
					<div className="mb-2 rounded-md border border-separator p-2">
						{matches.map(skill => (
							<button key={skill.slug} type="button" className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-surface" onClick={() => insertSkill(skill.slug)}>
								/{skill.slug}
							</button>
						))}
					</div>
				) : null}
				<div className="flex gap-2">
					<TextField
						name="chat-composer"
						className="flex-1"
						value={text}
						onChange={value => {
							setText(value);
							setHint(value.startsWith('/') ? 'Skills' : '');
						}}
					>
						<Input
							placeholder={hint || 'Write a concrete request…'}
							onKeyDown={event => {
								if (event.key === 'Enter' && !event.shiftKey) {
									event.preventDefault();
									void send();
								}
							}}
						/>
					</TextField>
					<Button onPress={() => void send()}>Send</Button>
				</div>
			</div>
		</div>
	);
}
