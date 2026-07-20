import type { FlowSpec } from './types';
import { pipelineFlow } from './pipeline';

// The tab order of the walkthrough. To add a future feature explainer,
// write one more `*.ts` FlowSpec and append it here — nothing else changes.
export const flows: FlowSpec[] = [pipelineFlow];

export type { FlowSpec } from './types';
