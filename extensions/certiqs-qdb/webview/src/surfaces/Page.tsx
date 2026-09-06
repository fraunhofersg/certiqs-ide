import type { ReactNode } from 'react';

export function Page(props: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }): JSX.Element {
	return (
		<div className="qdb-page">
			<header className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h1 className="text-base font-semibold">{props.title}</h1>
					{props.subtitle ? <p className="qdb-muted mt-1">{props.subtitle}</p> : null}
				</div>
				{props.actions ? <div className="qdb-row">{props.actions}</div> : null}
			</header>
			{props.children}
		</div>
	);
}

export function ErrorText(props: { error?: string }): JSX.Element | null {
	if (!props.error) {
		return null;
	}
	return <p className="qdb-error">{props.error}</p>;
}
