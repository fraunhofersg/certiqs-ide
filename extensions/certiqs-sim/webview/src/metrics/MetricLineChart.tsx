import type { ReactNode } from 'react';
import {
	CartesianGrid,
	Line,
	LineChart as RechartsLineChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from 'recharts';

type MetricLineChartProps = {
	data: Record<string, unknown>[];
	height?: number;
	className?: string;
	children?: ReactNode;
};

export function MetricLineChart({ data, height = 200, className, children }: MetricLineChartProps) {
	return (
		<div className={className} style={{ width: '100%', height }}>
			<ResponsiveContainer width="100%" height="100%">
				<RechartsLineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 16 }}>
					{children}
				</RechartsLineChart>
			</ResponsiveContainer>
		</div>
	);
}

MetricLineChart.Grid = CartesianGrid;
MetricLineChart.XAxis = XAxis;
MetricLineChart.YAxis = YAxis;
MetricLineChart.Line = Line;
MetricLineChart.Tooltip = Tooltip;
